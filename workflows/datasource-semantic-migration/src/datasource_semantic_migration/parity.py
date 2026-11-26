"""Number checks: compare a candidate Metric View with reference values computed on the same extract data.

The shadow Metric View is the candidate with its `source` replaced by a query over the extract, renaming
extract columns to the names the candidate's measures and dimensions use. Measures, dimensions, and filters
are unchanged, so the comparison tests their logic on identical data; it does not test the candidate's own
source query (remodeling, joins), which reads different data.

Reference values come only from the parsed source definition, through a source-specific reference builder
(for Tableau, a deterministic formula translation), never from the candidate. Everything here is pure; the
number-check notebook runs the SQL.
"""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .metric_repair import normalized_name

# Counts must match exactly; sums and averages within a relative tolerance for engine differences.
RELATIVE_TOLERANCE = 1e-4
EXACT_FAMILIES = {"ROW_COUNT", "COUNT", "COUNT_DISTINCT"}
MAXIMUM_GROUP_VALUES = 50
MAXIMUM_DIMENSIONS = 2
SELECT_ALIAS_PATTERN = re.compile(
    r"(?:(?<![\w`])(`?[A-Za-z_]\w*`?)\.)?(`[^`]+`|[A-Za-z_]\w*)\s+AS\s+(`[^`]+`|[A-Za-z_]\w*)", re.IGNORECASE
)


def column_key(name: str | None) -> str:
    """Comparable form of a column or field name: Business Unit, business_unit, BUSINESS-UNIT."""
    return re.sub(r"[^a-z0-9]+", "_", (name or "").casefold()).strip("_")


def quote(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def _unquote(identifier: str) -> str:
    return identifier[1:-1].replace("``", "`") if identifier.startswith("`") else identifier


def source_lineage(source_sql: str) -> dict[str, str]:
    """Output column -> the column it is read from, for plain `[alias.]column AS output` select items."""
    return {
        column_key(_unquote(output)): column_key(_unquote(column))
        for _, column, output in SELECT_ALIAS_PATTERN.findall(source_sql or "")
    }


def _bare_column(expression: str) -> str | None:
    match = re.fullmatch(r"\s*(?:source\.)?(`[^`]+`|[A-Za-z_]\w*)\s*", expression or "", flags=re.IGNORECASE)
    return _unquote(match.group(1)) if match else None


def bind_columns(
    output_columns: list[tuple[str, str]],
    extract_columns: list[str],
    *,
    metric_view: dict[str, Any],
    column_mappings: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Which extract column feeds each candidate source output column.

    In order: a user column mapping (Tableau field -> Databricks column, resolved through the source
    query's lineage), an equal normalized name, then a dimension or measure named after an extract
    column whose expression is that output column. Unbound columns are listed, never guessed.
    """
    extract_by_key = {column_key(name): name for name in extract_columns}
    mapped = {column_key(databricks): tableau for tableau, databricks in (column_mappings or {}).items()}
    lineage = source_lineage(str(metric_view.get("source") or ""))
    by_item_name: dict[str, str] = {}
    for item in [*metric_view.get("dimensions", []), *metric_view.get("measures", [])]:
        column = _bare_column(str(item.get("expr", "")))
        if column and column_key(item.get("name")) in extract_by_key:
            by_item_name.setdefault(column_key(column), extract_by_key[column_key(item.get("name"))])
    bound: dict[str, str] = {}
    how: dict[str, str] = {}
    for name, _ in output_columns:
        key = column_key(name)
        read_from = lineage.get(key, key)
        tableau = mapped.get(read_from) or mapped.get(key)
        if tableau and column_key(tableau) in extract_by_key:
            bound[name], how[name] = extract_by_key[column_key(tableau)], "column mapping"
        elif key in extract_by_key:
            bound[name], how[name] = extract_by_key[key], "same name"
        elif key in by_item_name:
            bound[name], how[name] = by_item_name[key], "named item"
    return {
        "bound": bound,
        "how": how,
        "unbound": [name for name, _ in output_columns if name not in bound],
    }


def shadow_source_sql(extract_table: str, output_columns: list[tuple[str, str]], binding: dict[str, Any]) -> str:
    """The candidate's source replaced by the extract: same output columns, extract data.

    Unbound columns are typed NULLs so the shadow view still compiles; measures using them are
    reported as not comparable rather than compared.
    """
    items = [
        f"{quote(binding['bound'][name])} AS {quote(name)}"
        if name in binding["bound"]
        else f"CAST(NULL AS {data_type}) AS {quote(name)}"
        for name, data_type in output_columns
    ]
    return "SELECT " + ", ".join(items) + f" FROM {extract_table}"


def shadow_metric_view(candidate: dict[str, Any], source_sql: str) -> dict[str, Any]:
    shadow = copy.deepcopy(candidate)
    shadow["source"] = source_sql
    # Joins read other Databricks tables; the extract already holds Tableau's joined result.
    shadow.pop("joins", None)
    return shadow


def expression_columns(expression: str, output_names: list[str]) -> set[str]:
    """Source output columns an expression reads."""
    used = set()
    for name in output_names:
        pattern = rf"(?<![\w`])(?:source\.)?(?:{re.escape(name)}|`{re.escape(name)}`)(?![\w`])"
        if re.search(pattern, expression or "", flags=re.IGNORECASE):
            used.add(name)
    return used


def plan_measures(
    *,
    metric_view: dict[str, Any],
    source_measures: list[dict[str, Any]],
    output_columns: list[tuple[str, str]],
    binding: dict[str, Any],
    reference_for: Callable[[dict[str, Any]], tuple[str, str]],
) -> list[dict[str, Any]]:
    """For every candidate measure: the reference expression, or why it cannot be compared.

    reference_for turns a parsed source measure into (reference SQL over the extract, aggregate
    family); the source system supplies it and raises ValueError, with the reason, when it cannot.
    """
    output_names = [name for name, _ in output_columns]
    sources = {normalized_name(item.get("display_name")): item for item in source_measures}
    unbound = set(binding["unbound"])
    plans = []
    for measure in metric_view.get("measures", []):
        name = str(measure.get("name"))
        plan = {"measure": name, "comparable": False, "reason": None, "reference_sql": None, "family": None}
        missing = sorted(expression_columns(str(measure.get("expr", "")), output_names) & unbound)
        source = sources.get(normalized_name(name))
        if missing:
            plan["reason"] = f"Column(s) {', '.join(missing)} not found in the extract; add a column mapping."
        elif source is None:
            plan["reason"] = "No matching measure in the source definition."
        else:
            try:
                reference_sql, family = reference_for(source)
            except ValueError as error:
                plan["reason"] = f"No reference value: {error}."
            else:
                plan.update(comparable=True, family=family, reference_sql=reference_sql)
        plans.append(plan)
    return plans


def candidate_dimensions(metric_view: dict[str, Any], binding: dict[str, Any]) -> list[dict[str, str]]:
    """Dimensions that are a single bound column, so both sides can group by the same values."""
    result = []
    for dimension in metric_view.get("dimensions", []):
        column = _bare_column(str(dimension.get("expr", "")))
        output = next((name for name in binding["bound"] if column and name.casefold() == column.casefold()), None)
        if output:
            result.append({"dimension": str(dimension["name"]), "extract_column": binding["bound"][output]})
    return result


def choose_dimensions(dimensions: list[dict[str, str]], distinct_counts: dict[str, int]) -> list[dict[str, str]]:
    """Up to two low-cardinality dimensions, so a grouped comparison stays small and readable."""
    usable = [
        item for item in dimensions if 2 <= distinct_counts.get(item["extract_column"], 0) <= MAXIMUM_GROUP_VALUES
    ]
    usable.sort(key=lambda item: (distinct_counts[item["extract_column"]], item["dimension"].casefold()))
    chosen, seen = [], set()
    for item in usable:
        if item["extract_column"] not in seen:
            chosen.append(item)
            seen.add(item["extract_column"])
        if len(chosen) == MAXIMUM_DIMENSIONS:
            break
    return chosen


def comparison_queries(
    *,
    shadow_view: str,
    extract_table: str,
    plans: list[dict[str, Any]],
    dimension: dict[str, str] | None,
) -> dict[str, str]:
    """One query per side for every comparable measure, at the total or grouped by one dimension."""
    comparable = [plan for plan in plans if plan["comparable"]]
    candidate_items = [f"MEASURE({quote(plan['measure'])}) AS m{index}" for index, plan in enumerate(comparable)]
    reference_items = [f"{plan['reference_sql']} AS m{index}" for index, plan in enumerate(comparable)]
    if dimension is None:
        return {
            "candidate": f"SELECT {', '.join(candidate_items)} FROM {shadow_view}",
            "reference": f"SELECT {', '.join(reference_items)} FROM {extract_table}",
        }
    return {
        "candidate": (
            f"SELECT {quote(dimension['dimension'])} AS g, {', '.join(candidate_items)} FROM {shadow_view} GROUP BY ALL"
        ),
        "reference": (
            f"SELECT {quote(dimension['extract_column'])} AS g, {', '.join(reference_items)} "
            f"FROM {extract_table} GROUP BY ALL"
        ),
    }


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def values_match(candidate: Any, reference: Any, family: str) -> tuple[bool, bool]:
    """(matches, exactly) for one value pair; nulls and zero totals count as equal."""
    left, right = _number(candidate), _number(reference)
    if left is None and right is None:
        return True, True
    if left is None or right is None:
        return (left or 0.0) == (right or 0.0), True
    if left == right:
        return True, True
    if family in EXACT_FAMILIES:
        return False, False
    close = math.isclose(left, right, rel_tol=RELATIVE_TOLERANCE, abs_tol=1e-9)
    return close, False


def _key(value: Any) -> str:
    return "∅" if value is None else str(value)


def compare_results(
    plans: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
    *,
    grouped_by: str | None,
) -> dict[str, dict[str, Any]]:
    """Per comparable measure: whether every group (or the total) matches, with the first differences."""
    comparable = [plan for plan in plans if plan["comparable"]]
    candidate_by_group = {_key(row.get("g")): row for row in candidate_rows}
    reference_by_group = {_key(row.get("g")): row for row in reference_rows}
    groups = sorted(set(candidate_by_group) | set(reference_by_group)) if grouped_by else ["total"]
    if not grouped_by:
        candidate_by_group = {"total": candidate_rows[0] if candidate_rows else {}}
        reference_by_group = {"total": reference_rows[0] if reference_rows else {}}
    results = {}
    for index, plan in enumerate(comparable):
        column = f"m{index}"
        exact, differences = True, []
        for group in groups:
            candidate_value = candidate_by_group.get(group, {}).get(column)
            reference_value = reference_by_group.get(group, {}).get(column)
            matches, is_exact = values_match(candidate_value, reference_value, plan["family"])
            exact = exact and is_exact
            if not matches:
                differences.append({"group": group, "candidate": candidate_value, "reference": reference_value})
        results[plan["measure"]] = {
            "grouped_by": grouped_by,
            "status": "MISMATCH" if differences else ("EXACT" if exact else "WITHIN_TOLERANCE"),
            "groups_compared": len(groups),
            "differences": differences[:5],
            "difference_count": len(differences),
        }
    return results


def measure_outcomes(plans: list[dict[str, Any]], comparisons: list[dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """One outcome per measure across the total and grouped comparisons, as scorecard statuses."""
    outcomes = []
    for plan in plans:
        name = plan["measure"]
        if not plan["comparable"]:
            outcomes.append({"measure": name, "status": "NOT_COMPARABLE", "reason": plan["reason"], "checks": []})
            continue
        checks = [comparison[name] for comparison in comparisons if name in comparison]
        if not checks:
            outcomes.append({"measure": name, "status": "NOT_COMPARABLE", "reason": "The comparison query did not run.", "checks": []})
        elif any(check["status"] == "MISMATCH" for check in checks):
            outcomes.append({"measure": name, "status": "FAILED_VALUE", "reason": "Numbers differ from the extract.", "checks": checks})
        elif all(check["status"] == "EXACT" for check in checks):
            outcomes.append({"measure": name, "status": "PASS_EXACT", "reason": None, "checks": checks})
        else:
            outcomes.append({"measure": name, "status": "PASS_WITH_TOLERANCE", "reason": None, "checks": checks})
    return outcomes


def parity_summary(outcomes: list[dict[str, Any]], *, available: bool, reason: str | None = None) -> dict[str, Any]:
    """Counts and one status for the Parity stage."""
    counts = {status: sum(item["status"] == status for item in outcomes) for status in (
        "PASS_EXACT", "PASS_WITH_TOLERANCE", "FAILED_VALUE", "NOT_COMPARABLE"
    )}
    compared = counts["PASS_EXACT"] + counts["PASS_WITH_TOLERANCE"] + counts["FAILED_VALUE"]
    if not available or compared == 0:
        status = "NOT_COMPARABLE"
    elif counts["FAILED_VALUE"]:
        status = "MISMATCH"
    elif counts["NOT_COMPARABLE"]:
        status = "PARTIAL"
    else:
        status = "MATCH"
    return {"status": status, "reason": reason, "measure_count": len(outcomes), "compared_count": compared, **counts}


def load_parity(group_internal_path: str | Path) -> dict[str, Any] | None:
    """The group's latest number check result, if one ran."""
    path = Path(group_internal_path) / "parity" / "parity-results.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
