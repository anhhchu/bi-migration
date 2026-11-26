from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .action_items import entry_names


# MEASURE() composes already-aggregated measures, so it satisfies Tableau's aggregation requirement.
AGGREGATE_PATTERN = re.compile(
    r"\b(MEASURE|SUM|AVG|MEAN|COUNT|COUNT_IF|APPROX_COUNT_DISTINCT|MIN|MAX|MEDIAN|MODE|PERCENTILE\w*"
    r"|STDDEV\w*|VARIANCE|VAR_POP|VAR_SAMP|ANY_VALUE|FIRST|LAST|MIN_BY|MAX_BY|BOOL_AND|BOOL_OR)\s*\(",
    re.IGNORECASE,
)
# A bare column reference, the only expression the deterministic patch can wrap in SUM() safely.
BARE_COLUMN_PATTERN = re.compile(r"`[^`]+`|[A-Za-z_][A-Za-z0-9_]*")
# Aggregate families: a source field's default aggregation and the SQL functions that satisfy it.
# Only base fields are checked: calculations are often rewritten legitimately (LOD values taken with
# MAX, ratios built from MEASURE()), which this check cannot tell apart from mistakes.
SOURCE_AGGREGATE_FAMILIES = {
    "SUM": "SUM", "AVG": "AVG", "AVERAGE": "AVG", "COUNT": "COUNT", "COUNT_DISTINCT": "COUNT_DISTINCT",
    "COUNTD": "COUNT_DISTINCT", "MIN": "MIN", "MAX": "MAX", "MEDIAN": "MEDIAN", "STDEV": "STDDEV",
    "STDEVP": "STDDEV", "VAR": "VARIANCE", "VARP": "VARIANCE", "PERCENTILE": "PERCENTILE",
    "ROW_COUNT": "ROW_COUNT",
}
SATISFYING_FAMILIES = {
    # A row count may be written COUNT(1), COUNT(*), COUNT_IF, a SUM of 1s, or COUNT(DISTINCT key) across joins.
    "ROW_COUNT": {"COUNT", "COUNT_IF", "SUM", "COUNT_DISTINCT"},
    "SUM": {"SUM", "COUNT_IF"},
    "COUNT": {"COUNT", "COUNT_IF", "SUM"},
    "COUNT_DISTINCT": {"COUNT_DISTINCT"},
    "AVG": {"AVG"},
    "MIN": {"MIN"},
    "MAX": {"MAX"},
    "MEDIAN": {"MEDIAN", "PERCENTILE"},
    "STDDEV": {"STDDEV"},
    "VARIANCE": {"VARIANCE"},
    "PERCENTILE": {"PERCENTILE", "MEDIAN"},
}
# Totals written with higher-order functions (often to avoid double counting across joins), and window
# measures, cannot be read.
UNREADABLE_AGGREGATION_PATTERN = re.compile(
    r"\b(AGGREGATE|REDUCE|COLLECT_SET|COLLECT_LIST|ARRAY_AGG)\s*\(|\)\s*OVER\s*\(", re.IGNORECASE
)
# SQL aggregates the check does not map to a family: their presence means the check cannot judge the
# expression, so it is skipped rather than flagged (for example try_sum, ANY_VALUE, MAX_BY).
UNMAPPED_AGGREGATE_FUNCTIONS = {
    "ANY", "ANY_VALUE", "APPROX_COUNT_DISTINCT", "APPROX_PERCENTILE", "APPROX_TOP_K", "BIT_AND", "BIT_OR",
    "BIT_XOR", "BOOL_AND", "BOOL_OR", "CORR", "COUNT_MIN_SKETCH", "COVAR_POP", "COVAR_SAMP", "EVERY", "FIRST",
    "FIRST_VALUE", "KURTOSIS", "LAST", "LAST_VALUE", "LISTAGG", "MAX_BY", "MIN_BY", "MODE", "SKEWNESS", "SOME",
    "STRING_AGG", "TRY_AVG", "TRY_SUM",
}
UNMAPPED_AGGREGATE_PREFIXES = ("HLL_", "REGR_")
TARGET_FUNCTION_PATTERN = re.compile(r"\b([A-Za-z_]+)\s*\(\s*(DISTINCT\b)?", re.IGNORECASE)
TARGET_FUNCTION_FAMILIES = {
    "SUM": "SUM", "AVG": "AVG", "MEAN": "AVG", "COUNT": "COUNT", "COUNT_IF": "COUNT_IF", "MIN": "MIN",
    "MAX": "MAX", "MEDIAN": "MEDIAN", "VARIANCE": "VARIANCE", "VAR_POP": "VARIANCE", "VAR_SAMP": "VARIANCE",
}
SINGLE_AGGREGATE_PATTERN = re.compile(r"^\s*([A-Za-z_]+)\s*\(\s*(DISTINCT\s+)?(`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)\s*\)\s*$", re.IGNORECASE)
# Dispositions that settle a measure without a target: they need a person, not a repair.
EXCLUSION_STATUSES = {"EXCLUDED_UNSUPPORTED", "EXCLUDED_BY_IMPORT", "NOT_COMPARABLE"}
FQN_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(?:`([^`]+)`|([A-Za-z_][\w-]*))\."
                         r"(?:`([^`]+)`|([A-Za-z_][\w-]*))\."
                         r"(?:`([^`]+)`|([A-Za-z_][\w-]*))")


DEFAULT_POLICY = {
    "critical_metric_translation_coverage": 1.0,
    "overall_metric_translation_coverage": 0.95,
    "governed_disposition_coverage": 1.0,
    "retained_metric_evidence_coverage": 1.0,
    "measure_queryability": 1.0,
    "unsafe_relationship_count": 0,
    "blocking_finding_count": 0,
    "critical_regression_count": 0,
}


def normalized_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def document_hash(document: Any) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def metric_view_yaml(document: dict[str, Any]) -> str:
    return yaml.safe_dump(document, sort_keys=False, width=120)


def _join_sources(document: dict[str, Any]) -> list[str]:
    sources = [str(document.get("source") or "")]
    for join in document.get("joins") or []:
        if isinstance(join, dict):
            sources.extend(_join_sources(join))
    return sources


def target_lineage(document: dict[str, Any]) -> list[str]:
    """Every table the Metric View reads: its source and the source of every join, at any depth."""
    matches = []
    for source in _join_sources(document):
        for match in FQN_PATTERN.finditer(source):
            parts = [match.group(1) or match.group(2), match.group(3) or match.group(4), match.group(5) or match.group(6)]
            matches.append(".".join(parts))
    return sorted(set(matches))


def disallowed_tables(document: dict[str, Any], allowed_tables: Iterable[str]) -> list[str]:
    allowed = {table.casefold() for table in allowed_tables}
    return [table for table in target_lineage(document) if table.casefold() not in allowed]


def _definition(measure: dict[str, Any]) -> tuple[Any, Any]:
    expression = measure.get("expression") or {}
    return (measure.get("aggregation"), " ".join(str(expression.get("formula") or "").split()).casefold())


def _source_measure_index(
    source_metric_irs: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, dict[str, Any]]]]:
    """Source measures by name, plus same-named measures whose definitions differ (a Metric View holds one)."""
    result: dict[str, dict[str, Any]] = {}
    conflicts = []
    for metric_ir in source_metric_irs:
        for measure in metric_ir.get("measures", []):
            key = normalized_name(measure.get("display_name"))
            if key not in result:
                result[key] = measure
            elif _definition(measure) != _definition(result[key]):
                conflicts.append((key, measure))
    return result, conflicts


def _expected_families(source: dict[str, Any]) -> set[str]:
    """Aggregate families the source measure uses; empty when they cannot be known."""
    if (source.get("expression") or {}).get("kind") != "field_aggregate":
        return set()
    family = SOURCE_AGGREGATE_FAMILIES.get(str(source.get("aggregation") or "").upper())
    return {family} if family else set()


def _target_families(expression: str) -> set[str] | None:
    """Aggregate families used in a target expression, or None when they cannot be read reliably."""
    if UNREADABLE_AGGREGATION_PATTERN.search(expression):
        return None
    families = set()
    for match in TARGET_FUNCTION_PATTERN.finditer(expression):
        name = match.group(1).upper()
        if name == "MEASURE" or name in UNMAPPED_AGGREGATE_FUNCTIONS or name.startswith(UNMAPPED_AGGREGATE_PREFIXES):
            return None
        if name == "COUNT" and match.group(2):
            families.add("COUNT_DISTINCT")
        elif name in {"SUM", "AVG", "MEAN"} and match.group(2):
            # SUM(DISTINCT x) adds each value once; it is not the source's SUM or AVG.
            families.add(f"{TARGET_FUNCTION_FAMILIES[name]}_DISTINCT")
        elif name.startswith("PERCENTILE"):
            families.add("PERCENTILE")
        elif name.startswith("STDDEV"):
            families.add("STDDEV")
        elif name in TARGET_FUNCTION_FAMILIES:
            families.add(TARGET_FUNCTION_FAMILIES[name])
    return families


def _family_sql(family: str, column: str) -> str:
    return f"COUNT(DISTINCT {column})" if family == "COUNT_DISTINCT" else f"{family}({column})"


def _aggregation_difference(source: dict[str, Any], target_expression: str) -> dict[str, Any] | None:
    """How the target aggregates differently from the source, with a safe rewrite when there is one."""
    if source.get("status") == "NEEDS_AGGREGATION_COMPILATION":
        if AGGREGATE_PATTERN.search(target_expression):
            return None
        suggestion = f"SUM({target_expression.strip()})" if _is_bare_column(target_expression) else None
        return {"field": "aggregation", "source": "SOURCE_DEFAULT", "target": target_expression, "suggested": suggestion}
    expected = _expected_families(source)
    found = _target_families(target_expression)
    # Judge only expressions whose aggregates are all recognized; anything else is left to the query check.
    if not expected or not found:
        return None
    missing = sorted(family for family in expected if not (SATISFYING_FAMILIES.get(family, {family}) & found))
    if not missing:
        return None
    suggestion = None
    single = SINGLE_AGGREGATE_PATTERN.match(target_expression)
    if single and missing[0] != "ROW_COUNT" and _target_families(f"{single.group(1)}(x)"):
        suggestion = _family_sql(missing[0], single.group(3))
    return {"field": "aggregation", "source": ", ".join(missing), "target": target_expression, "suggested": suggestion}


def _target_measure_index(metric_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        normalized_name(item.get("display_name") or item.get("name")): item
        for item in metric_view.get("measures", [])
        if isinstance(item, dict)
    }


def _external_dependency(measure: dict[str, Any]) -> bool:
    return any(item.get("kind") == "external_field" for item in measure.get("dependencies", []))


def _query_result(
    query_results: dict[str, Any],
    source_name: str,
    target: dict[str, Any] | None,
) -> dict[str, Any]:
    if target is None:
        return {
            "status": "NOT_APPLICABLE",
            "reason": "No target Metric View measure exists, so there is nothing to query.",
        }
    candidate_names = [target.get("name"), target.get("display_name"), source_name]
    for candidate_name in candidate_names:
        result = query_results.get(normalized_name(str(candidate_name or "")))
        if result:
            return result
    return {
        "status": "NOT_RUN",
        "reason": (
            "The query harness did not record a result for the matched target measure. "
            "Check the target measure name and generated query artifact."
        ),
    }


def evaluate_candidate(
    *,
    source_metric_irs: list[dict[str, Any]],
    metric_view: dict[str, Any],
    target_profile: dict[str, Any],
    query_results: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    excluded_measures: Iterable[str] = (),
    allowed_tables: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Score each source measure against the candidate.

    excluded_measures names measures the import left out on purpose, with a reason; they need a
    person's decision, so repair does not try to translate them. allowed_tables, when given, are
    the approved mapping's tables; reading any other table blocks the candidate.
    """
    policy = {**DEFAULT_POLICY, **(policy or {})}
    # Match query results by normalized name, however the caller keyed them.
    query_results = {normalized_name(str(name)): result for name, result in (query_results or {}).items()}
    excluded = {normalized_name(name) for name in excluded_measures}
    source_measures, conflicting_measures = _source_measure_index(source_metric_irs)
    target_measures = _target_measure_index(metric_view)
    scorecards = []
    for key, source in sorted(source_measures.items()):
        name = source.get("display_name") or source.get("measure_id")
        target = target_measures.get(key)
        external = _external_dependency(source)
        query_result = _query_result(query_results, str(name), target)
        query_status = str(query_result.get("status", "NOT_RUN"))
        failure_codes = []
        repair_route = "NONE"
        differences = []
        if target is None and external:
            status = "BLOCKED_UNRESOLVED_MAPPING"
            failure_codes = ["EXTERNAL_DATASOURCE_UNMAPPED"]
            repair_route = "MAPPING_REVISION"
        elif target is None and key in excluded:
            status = "EXCLUDED_BY_IMPORT"
            failure_codes = ["EXCLUDED_WITH_REASON"]
            repair_route = "HUMAN_DECISION"
        elif target is None and source.get("status") == "UNSUPPORTED":
            status = "EXCLUDED_UNSUPPORTED"
            failure_codes = ["UNSUPPORTED_METRIC_SHAPE"]
            repair_route = "GOVERNED_FUNCTION_OR_EXCLUSION"
        elif target is None:
            status = "FAILED_SEMANTICS"
            failure_codes = ["MISSING_TARGET_MEASURE", "NEEDS_SEMANTIC_TRANSLATION"]
            repair_route = "GENIE_PATCH"
        else:
            target_expression = str(target.get("expr", ""))
            difference = _aggregation_difference(source, target_expression)
            if difference:
                status = "FAILED_SEMANTICS"
                failure_codes = ["AGGREGATION_MISMATCH"]
                # A safe rewrite exists only for a single aggregate of a bare column; otherwise Genie.
                repair_route = "DETERMINISTIC_METRIC_PATCH" if difference["suggested"] else "GENIE_PATCH"
                differences.append(difference)
            elif query_status == "FAIL":
                status = "FAILED_VALUE"
                failure_codes = ["MEASURE_QUERY_FAILED"]
                repair_route = "GENIE_PATCH"
            elif query_status != "PASS":
                # No query evidence means the measure is unverified, not passing.
                status = "FAILED_VALUE"
                failure_codes = ["QUERY_NOT_RUN"]
                repair_route = "EVALUATOR_CHECK"
            else:
                status = "PASS_SEMANTIC_ONLY"
        scorecards.append(
            {
                "metric_id": source.get("measure_id"),
                "source_name": name,
                "target_name": (target or {}).get("name"),
                "criticality": "standard",
                "status": status,
                "evidence_level": "SEMANTIC_ONLY",
                "translation": {"status": "PRESENT" if target else "MISSING", "differences": differences},
                "relationship_safety": {"status": "PASS"},
                "queryability": query_status,
                "query": query_result,
                "failure_codes": failure_codes,
                "repair_route": repair_route,
                "dependencies": source.get("dependencies", []),
                "source": source,
                "target": target,
            }
        )

    for key, source in conflicting_measures:
        scorecards.append(
            {
                "metric_id": source.get("measure_id"),
                "source_name": source.get("display_name"),
                "target_name": None,
                "criticality": "standard",
                "status": "FAILED_SEMANTICS",
                "evidence_level": "NONE",
                "translation": {"status": "CONFLICT", "differences": [{"field": "definition", "source": key}]},
                "relationship_safety": {"status": "PASS"},
                "queryability": "NOT_APPLICABLE",
                "query": {"status": "NOT_APPLICABLE", "reason": "Another measure with this name was evaluated instead."},
                "failure_codes": ["DUPLICATE_MEASURE_NAME"],
                "repair_route": "HUMAN_DECISION",
                "dependencies": source.get("dependencies", []),
                "source": source,
                "target": None,
            }
        )

    relationship_blockers = [
        item for item in target_profile.get("relationships", []) if item.get("status") == "BLOCKED"
    ]
    if allowed_tables is not None:
        relationship_blockers.extend(
            {"name": f"Reads {table}", "status": "BLOCKED", "reason": f"{table} is not a table in the approved mapping."}
            for table in disallowed_tables(metric_view, allowed_tables)
        )
    passed = [item for item in scorecards if item["status"].startswith("PASS_")]
    excluded_scorecards = [item for item in scorecards if item["status"] in EXCLUSION_STATUSES]
    governed = [item for item in scorecards if item["status"].startswith("PASS_")] + excluded_scorecards
    translated = [item for item in scorecards if item["target_name"] is not None]
    query_passed = [item for item in translated if item["queryability"] == "PASS"]
    query_failed = [item for item in translated if item["queryability"] == "FAIL"]
    query_not_run = [item for item in translated if item["queryability"] == "NOT_RUN"]
    total = len(scorecards)
    # Settled exclusions cannot carry passing evidence, so they are not counted against it.
    evidence_candidates = total - len(excluded_scorecards)
    coverage = {
        "source_business_metric_count": total,
        "translated_metric_count": len(translated),
        "governed_metric_count": len(governed),
        "evidenced_metric_count": len(passed),
        "evidence_candidate_count": evidence_candidates,
        "excluded_metric_count": len(excluded_scorecards),
        "query_candidate_count": len(translated),
        "query_pass_count": len(query_passed),
        "query_fail_count": len(query_failed),
        "query_not_run_count": len(query_not_run),
        "translation_coverage": len(translated) / total if total else 0.0,
        "governed_disposition_coverage": len(governed) / total if total else 0.0,
        "evidence_coverage": len(passed) / evidence_candidates if evidence_candidates else (1.0 if total else 0.0),
        "measure_queryability": len(query_passed) / len(translated) if translated else 0.0,
    }
    blocking = [
        item
        for item in scorecards
        if item["status"] in {"BLOCKED_UNRESOLVED_MAPPING", "FAILED_SEMANTICS", "FAILED_VALUE"}
    ]
    deterministic_repairs = any(item["repair_route"] == "DETERMINISTIC_METRIC_PATCH" for item in blocking)
    blocked_evidence = bool(relationship_blockers) or any(
        item["status"] == "BLOCKED_UNRESOLVED_MAPPING" for item in blocking
    )
    # A mapping or relationship blocker stops the attempt anyway, so Genie output would be discarded.
    needs_genie = not blocked_evidence and any(item["repair_route"] == "GENIE_PATCH" for item in blocking)
    gates = {
        "overall_metric_translation_coverage": coverage["translation_coverage"]
        >= policy["overall_metric_translation_coverage"],
        "governed_disposition_coverage": coverage["governed_disposition_coverage"]
        >= policy["governed_disposition_coverage"],
        "retained_metric_evidence_coverage": coverage["evidence_coverage"]
        >= policy["retained_metric_evidence_coverage"],
        "measure_queryability": coverage["measure_queryability"] >= policy["measure_queryability"],
        "unsafe_relationship_count": len(relationship_blockers) <= policy["unsafe_relationship_count"],
        "blocking_finding_count": len(blocking) <= policy["blocking_finding_count"],
    }
    if all(gates.values()):
        readiness = "READY"
    elif blocked_evidence:
        readiness = "BLOCKED_EVIDENCE"
    else:
        readiness = "NEEDS_REPAIR"
    signature_basis = [
        {"metric_id": item["metric_id"], "status": item["status"], "failure_codes": item["failure_codes"]}
        for item in scorecards
        if item["failure_codes"]
    ]
    return {
        "schema_version": "1.0",
        "readiness": readiness,
        "coverage": coverage,
        "gates": gates,
        "scorecards": scorecards,
        "blocking_findings": blocking,
        "relationship_blockers": relationship_blockers,
        "needs_genie": needs_genie,
        "has_deterministic_repairs": deterministic_repairs,
        "failure_signature": document_hash(signature_basis),
        "excluded_measures": sorted(excluded),
        "policy": policy,
    }


def import_exclusions(import_result_path: str | Path) -> list[str]:
    """Field names the import left out on purpose (items_not_translated), read from importbi-result.json."""
    path = Path(import_result_path)
    if not path.is_file():
        return []
    document = json.loads(path.read_text(encoding="utf-8")) or {}
    return [name for entry in document.get("items_not_translated") or [] for name in entry_names(entry)]


def _is_bare_column(expression: str) -> bool:
    return BARE_COLUMN_PATTERN.fullmatch(expression.strip()) is not None


def next_attempt_decision(
    before: dict[str, Any], after: dict[str, Any], *, genie_ran: bool
) -> dict[str, Any]:
    """Whether another repair attempt could do something this attempt did not.

    before and after are evaluations of one attempt. A retry repeats the same deterministic patch
    and, for findings Genie already saw, the same Genie request, so it only helps when the failures
    changed and some finding is new to both.
    """
    remaining = after.get("blocking_findings", [])
    if not remaining:
        return {"retry": False, "reason": "No failure is left that automatic repair can act on."}
    if after.get("failure_signature") == before.get("failure_signature"):
        return {"retry": False, "reason": "The same failures remain after this attempt, so another attempt would repeat it."}
    sent_to_genie = (
        {item.get("metric_id") for item in before.get("blocking_findings", []) if item.get("repair_route") == "GENIE_PATCH"}
        if genie_ran
        else set()
    )
    new_work = [
        item
        for item in remaining
        if item.get("repair_route") == "DETERMINISTIC_METRIC_PATCH"
        or (item.get("repair_route") == "GENIE_PATCH" and item.get("metric_id") not in sent_to_genie)
    ]
    if not new_work:
        return {
            "retry": False,
            "reason": "Genie already saw every remaining failure in this attempt and could not fix it.",
        }
    return {"retry": True, "reason": f"{len(new_work)} remaining failure(s) are new to automatic repair."}


def evaluate_progress(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    count_metrics = (
        "translated_metric_count",
        "governed_metric_count",
        "evidenced_metric_count",
        "query_pass_count",
    )
    before_coverage = before.get("coverage", {})
    after_coverage = after.get("coverage", {})
    count_deltas = {
        name: int(after_coverage.get(name, 0)) - int(before_coverage.get(name, 0))
        for name in count_metrics
    }
    blocking_before = len(before.get("blocking_findings", []))
    blocking_after = len(after.get("blocking_findings", []))
    relationship_before = len(before.get("relationship_blockers", []))
    relationship_after = len(after.get("relationship_blockers", []))
    measurable_improvement = (
        any(delta > 0 for delta in count_deltas.values())
        or blocking_after < blocking_before
        or relationship_after < relationship_before
        or after.get("readiness") == "READY"
    )
    return {
        "measurable_improvement": measurable_improvement,
        "count_deltas": count_deltas,
        "blocking_findings_before": blocking_before,
        "blocking_findings_after": blocking_after,
        "relationship_blockers_before": relationship_before,
        "relationship_blockers_after": relationship_after,
        "reason": (
            "At least one governed metric count increased or a blocker was removed."
            if measurable_improvement
            else "No translated, governed, evidenced, or query-passing metric was added and no blocker was removed."
        ),
    }


def build_deterministic_patch(evaluation: dict[str, Any], metric_view: dict[str, Any]) -> dict[str, Any]:
    operations = []
    for scorecard in evaluation.get("scorecards", []):
        if "AGGREGATION_MISMATCH" not in scorecard.get("failure_codes", []):
            continue
        target = scorecard.get("target") or {}
        expression = str(target.get("expr", "")).strip()
        suggestions = [
            item.get("suggested")
            for item in scorecard.get("translation", {}).get("differences", [])
            if item.get("field") == "aggregation" and item.get("suggested")
        ]
        # Older evaluations carry no suggestion; a bare column still gets the SUM default.
        after = suggestions[0] if suggestions else (f"SUM({expression})" if _is_bare_column(expression) else None)
        if after:
            operations.append(
                {
                    "op": "set_measure_expression",
                    "measure": target.get("name"),
                    "before": expression,
                    "after": after,
                    "failure_codes": ["AGGREGATION_MISMATCH"],
                }
            )
    return {
        "schema_version": "1.0",
        "patch_id": document_hash({"candidate": document_hash(metric_view), "operations": operations})[:24],
        "target": "METRIC_VIEW",
        "operations": operations,
        "preconditions": [{"metric_view_hash": document_hash(metric_view)}],
        "expected_test_ids": [item.get("measure") for item in operations],
        "confidence": 1.0 if operations else 0.0,
        "provenance": {"generator": "datasource-semantic-migration"},
    }


def apply_metric_patch(metric_view: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(metric_view)
    measures = {item.get("name"): item for item in updated.get("measures", []) if isinstance(item, dict)}
    for operation in patch.get("operations", []):
        if operation.get("op") != "set_measure_expression":
            raise ValueError(f"Unsupported patch operation: {operation.get('op')}")
        measure = measures.get(operation.get("measure"))
        if measure is None:
            raise ValueError(f"Patch measure does not exist: {operation.get('measure')}")
        if str(measure.get("expr", "")).strip() != operation.get("before"):
            raise ValueError(f"Patch precondition failed for measure {operation.get('measure')}")
        measure["expr"] = operation["after"]
    return updated


def create_metric_view_sql(metric_view_fqn: str, document: dict[str, Any]) -> str:
    quoted = ".".join(f"`{part}`" for part in metric_view_fqn.split("."))
    return f"CREATE OR REPLACE VIEW {quoted} WITH METRICS LANGUAGE YAML AS $$\n{metric_view_yaml(document)}$$"
