"""Group migration findings into action categories with a reason a person is needed.

Every finding lands in exactly one place:
* an action category (who acts, why a person is needed, what to do), or
* "handled automatically" (shown for transparency, no action requested).

The rules are deterministic so the same run always produces the same list.
"""

from __future__ import annotations

import re
from typing import Any

from .source_systems import fill_source

CATEGORIES: dict[str, dict[str, str]] = {
    "data_mapping": {
        "label": "Data and mapping",
        "owner": "Data or pipeline owner",
        "why_human": (
            "Only someone who knows the data can say which governed table, join, or grain is correct. "
            "The workflow never guesses a table."
        ),
    },
    "business_definition": {
        "label": "Business definition",
        "owner": "Metric owner",
        "why_human": (
            "These are decisions about business meaning: whether a loss is acceptable, which definition is "
            "authoritative, or whether a data restriction applies."
        ),
    },
    "calculation": {
        "label": "Calculation",
        "owner": "Metric View author",
        "why_human": "Automatic repair tried and could not fix these expressions.",
    },
    "access_platform": {
        "label": "Access and platform",
        "owner": "Workspace admin",
        "why_human": "The fix is a permission grant or a platform setting, which the workflow cannot change.",
    },
    "number_checks": {
        "label": "Number checks",
        "owner": "Metric owner",
        "why_human": (
            "{source}'s report numbers are not stored in its semantic model files, so someone must supply trusted values "
            "or decide which number is right."
        ),
    },
    "sign_off": {
        "label": "Sign-off",
        "owner": "Accountable owner",
        "why_human": "Production use needs a named person to approve it.",
    },
}

_ACCESS_ERRORS = re.compile(r"PERMISSION_DENIED|INSUFFICIENT_PERMISSIONS|does not have .*privilege|USE CATALOG|USE SCHEMA", re.IGNORECASE)
_PLATFORM_ERRORS = re.compile(r"WAREHOUSE|TIMEOUT|TIMED OUT|RESOURCE_EXHAUSTED|SERVICE_UNAVAILABLE", re.IGNORECASE)
_DATA_ERRORS = re.compile(r"TABLE_OR_VIEW_NOT_FOUND|UNRESOLVED_COLUMN|cannot be resolved|SCHEMA_NOT_FOUND", re.IGNORECASE)
_DASHBOARD_LAYER = re.compile(r"^action groups?\b|^action \(|dashboard action", re.IGNORECASE)
# Reasons Genie gives for leaving out visual helpers (map points, axis labels, paging controls).
_HELPER_REASON = re.compile(
    r"\b(helpers?|axis|labels?|layout|navigation|pagination|paging|tooltips?|map points?|visual|UI)\b", re.IGNORECASE
)
# Items left out because their formula (or one they depend on) forms a dependency cycle.
_CYCLE_REASON = re.compile(r"BLOCKED_CYCLE|\bcycle\b|circular|\bblocked\b", re.IGNORECASE)
# A person is needed only when the Metric View averages a field the BI tool would sum.
_AVERAGED = re.compile(r"^\s*(AVG|MEAN|MEDIAN|PERCENTILE\w*|STDDEV\w*|VARIANCE|VAR_POP|VAR_SAMP)\s*\(", re.IGNORECASE)
# INDEX() numbers rows in a worksheet table; it is layout, not a business measure.
_ROW_NUMBERING = re.compile(r"\bINDEX\(\)", re.IGNORECASE)


_JARGON = (
    (re.compile(r"\bDatasource IR\b", re.IGNORECASE), "the parsed {source} datasource"),
    (re.compile(r"\bMetric IR\b", re.IGNORECASE), "the parsed {source} measures"),
    (re.compile(r"\bIR\b"), "parsed {source} definition"),
)


def plain_language(text: str, source: str = "Tableau") -> str:
    """Replace internal terms (IR = intermediate representation) in text shown to users."""
    for pattern, replacement in _JARGON:
        text = pattern.sub(fill_source(replacement, source), text)
    return text


def _item(title: str, detail: str, what_to_do: str, *, blocking: bool, **extra: Any) -> dict[str, Any]:
    return {"title": title, "detail": detail, "what_to_do": what_to_do, "blocking": blocking, **extra}


def _query_error(scorecard: dict[str, Any]) -> str:
    query = scorecard.get("query") or {}
    return str(query.get("error") or query.get("reason") or "")


def _scorecard_item(
    scorecard: dict[str, Any], repair_status: str | None, source: str
) -> tuple[str, dict[str, Any]]:
    name = str(scorecard.get("source_name") or "Unnamed measure")
    codes = set(scorecard.get("failure_codes", []))
    expression = (scorecard.get("target") or {}).get("expr")
    formula = ((scorecard.get("source") or {}).get("expression") or {}).get("formula")
    tried = f" Automatic repair stopped with {repair_status}." if repair_status and repair_status != "READY" else ""
    extra = {"expression": expression, "source_formula": formula}
    if "EXTERNAL_DATASOURCE_UNMAPPED" in codes:
        return "data_mapping", _item(
            name, f"Uses a field from another {source} datasource that table-mapping.yaml does not map.",
            "Add that datasource's tables to table-mapping.yaml, then propose again.", blocking=True, **extra,
        )
    if "MEASURE_QUERY_FAILED" in codes:
        error = _query_error(scorecard)
        if _ACCESS_ERRORS.search(error):
            return "access_platform", _item(
                name, f"The query was refused: {error}",
                "Grant SELECT on the mapped tables to the Job's run-as identity, then rerun repair.",
                blocking=True, **extra,
            )
        if _PLATFORM_ERRORS.search(error):
            return "access_platform", _item(
                name, f"The SQL warehouse could not run the query: {error}",
                "Check that the configured warehouse is running and sized, then rerun repair.", blocking=True, **extra,
            )
        if _DATA_ERRORS.search(error):
            return "data_mapping", _item(
                name, f"The query references a table or column that does not exist: {error}",
                "Fix the target table or column in table-mapping.yaml (or the table itself), then propose again.",
                blocking=True, **extra,
            )
        return "calculation", _item(
            name, f"The measure query failed: {error or 'no error captured'}.{tried}",
            "Correct the expression in groups/<group>/metric-view.yaml, then run the Datasource semantic repair Job.",
            blocking=True, **extra,
        )
    if "DUPLICATE_MEASURE_NAME" in codes:
        return "business_definition", _item(
            name, f"Two {source} datasources in this group define a measure with this name differently; a Metric View can hold only one.",
            "Decide which definition is authoritative, or rename one in metric-view.yaml, then run the Datasource semantic repair Job.",
            blocking=True, **extra,
        )
    if "QUERY_NOT_RUN" in codes:
        return "access_platform", _item(
            name, "The measure exists, but its test query has no recorded result, so it is unverified.",
            "Run the Datasource semantic repair Job again; if it stays unverified, report it as a workflow issue.",
            blocking=True, **extra,
        )
    if "UNSUPPORTED_METRIC_SHAPE" in codes:
        return "business_definition", _item(
            name, f"Uses a {source} feature with no Metric View equivalent.",
            "Decide: drop it, rebuild it in the dashboard, or build it as a SQL view.", blocking=False, **extra,
        )
    return "calculation", _item(
        name, f"The generated definition does not match the {source} formula.{tried}",
        "Correct the expression in groups/<group>/metric-view.yaml, then run the Datasource semantic repair Job.",
        blocking=True, **extra,
    )


def entry_names(entry: dict[str, Any]) -> list[str]:
    """Names in a not-migrated entry; Genie writes either `name` or a comma-separated `items`."""
    raw = entry.get("name") or entry.get("items") or entry.get("item") or ""
    if isinstance(raw, list):
        return [str(name).strip() for name in raw if str(name).strip()]
    return [name.strip() for name in str(raw).split(",") if name.strip()]


def entry_field_count(entries: list[dict[str, Any]]) -> int:
    """Number of fields in not-migrated entries; one entry may list several fields."""
    return sum(len(entry_names(entry)) or 1 for entry in entries)


def reconcile_import_exclusions(
    scorecard_evaluation: dict[str, Any] | None, untranslated: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Drop "missing measure" failures for measures the import deliberately left out with a reason."""
    if not scorecard_evaluation:
        return scorecard_evaluation
    excluded = {name.casefold() for entry in untranslated for name in entry_names(entry)}
    kept = [
        finding
        for finding in scorecard_evaluation.get("blocking_findings", [])
        if not (
            "MISSING_TARGET_MEASURE" in finding.get("failure_codes", [])
            and str(finding.get("source_name", "")).casefold() in excluded
        )
    ]
    return {**scorecard_evaluation, "blocking_findings": kept}


def _merge_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse items that share the same explanation and fix into one item listing every name."""
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in items:
        if item.get("expression"):
            merged[(id(item),)] = {**item, "names": [item["title"]]}
            continue
        key = (item["detail"], item["what_to_do"], item["blocking"])
        if key in merged:
            merged[key]["names"].append(item["title"])
        else:
            merged[key] = {**item, "names": [item["title"]]}
    result = []
    for item in merged.values():
        if len(item["names"]) > 1:
            item["title"] = f"{len(item['names'])} items"
        result.append(item)
    return result


def build_action_groups(
    *,
    scorecard_evaluation: dict[str, Any] | None,
    evaluation_findings: list[dict[str, Any]],
    business_untranslated: list[dict[str, Any]],
    approximations: list[dict[str, Any]],
    aggregation_items: list[dict[str, str]],
    group_mapping: dict[str, Any] | None,
    repair: dict[str, Any],
    has_candidate: bool,
    source: str = "Tableau",
) -> dict[str, Any]:
    """source is the display name of the BI tool the Metric View was migrated from."""
    buckets: dict[str, list[dict[str, Any]]] = {key: [] for key in CATEGORIES}
    automatic: list[dict[str, str]] = []
    repair_status = repair.get("status")

    if not has_candidate:
        buckets["calculation"].append(
            _item(
                "No candidate Metric View", "The import step did not create a Metric View.",
                "Open the full report for the import error, fix the inputs, and propose again.", blocking=True,
            )
        )

    for scorecard in (scorecard_evaluation or {}).get("blocking_findings", []):
        category, item = _scorecard_item(scorecard, repair_status, source)
        buckets[category].append(item)

    for blocker in (scorecard_evaluation or {}).get("relationship_blockers", []):
        buckets["data_mapping"].append(
            _item(
                str(blocker.get("name") or "Join"),
                str(blocker.get("reason") or "This join could duplicate rows (fan-out) or has an unsafe cardinality."),
                "Confirm the join keys and cardinality in table-mapping.yaml relationships, then propose again.",
                blocking=True,
            )
        )

    # Per-measure checks replace most import errors, but not these: repair cannot change them.
    lasting_codes = {"DISALLOWED_LINEAGE", "APPROVED_LINEAGE_NOT_FOUND", "METRIC_YAML_INVALID"}
    for finding in evaluation_findings:
        if (
            scorecard_evaluation
            and finding.get("severity") == "ERROR"
            and finding.get("code") in lasting_codes
        ):
            tables = ", ".join(str(table) for table in finding.get("tables") or finding.get("allowed_tables") or [])
            buckets["data_mapping"].append(
                _item(
                    str(finding.get("code")).replace("_", " ").capitalize(),
                    str(finding.get("message") or (f"Tables: {tables}." if tables else finding.get("code"))),
                    "Fix the tables the Metric View reads so they match table-mapping.yaml, then propose again.",
                    blocking=True,
                )
            )

    if not scorecard_evaluation:
        for finding in evaluation_findings:
            if finding.get("severity") == "ERROR":
                code = str(finding.get("code", ""))
                category = "data_mapping" if "DATASOURCE" in code or "MAPPING" in code else "calculation"
                buckets[category].append(
                    _item(
                        str(finding.get("calculation_name") or code or "Finding"),
                        str(finding.get("message") or code),
                        "Follow the full report's guidance for this finding.", blocking=True,
                    )
                )

    for entry in (group_mapping or {}).get("table_mappings", []):
        target = entry.get("target", {})
        if not (target.get("grain") or entry.get("source", {}).get("grain")):
            buckets["data_mapping"].append(
                _item(
                    f"Grain for {target.get('table')}",
                    "The mapping does not say what one row of this table represents.",
                    "Add grain (and business_keys) for this table in table-mapping.yaml.", blocking=False,
                )
            )

    already_reported = {
        str(item["title"]).casefold() for items in buckets.values() for item in items if item.get("blocking")
    }
    needs_people: list[dict[str, Any]] = []
    for entry in business_untranslated:
        automatic_before = len(automatic)
        names = entry_names(entry) or ["Unnamed item"]
        if all(name.casefold() in already_reported for name in names):
            # Already a blocking item (e.g. an unmapped datasource): still left out, but not listed twice.
            needs_people.append(entry)
            continue
        name = ", ".join(names) if len(names) <= 3 else f"{', '.join(names[:3])} and {len(names) - 3} more"
        reason = plain_language(str(entry.get("reason") or ""), source)
        kind = str(entry.get("kind") or "")
        if _DASHBOARD_LAYER.search(name) or "no semantic-layer equivalent" in reason.casefold():
            automatic.append({"title": name, "detail": f"Dashboard behaviour, not part of the model: {reason}"})
        elif _ROW_NUMBERING.search(reason):
            automatic.append({"title": name, "detail": "Row numbering for a worksheet table; rebuilt by the dashboard."})
        elif _HELPER_REASON.search(reason):
            automatic.append({"title": name, "detail": f"Visual helper for the dashboard, not a business measure: {reason}"})
        elif _CYCLE_REASON.search(reason):
            buckets["calculation"].append(
                _item(
                    name,
                    f"Not migrated because the formula, or one it depends on, forms a dependency loop as parsed: {reason}",
                    "Rebuild this logic in SQL or the dashboard. Loops in date-shift calculations are often a parser "
                    "limitation; report the datasource so the parser can be improved.",
                    blocking=False,
                    names=names,
                )
            )
        elif kind == "filter":
            buckets["business_definition"].append(
                _item(
                    name,
                    f"{source} restricts this datasource to selected values, and the workflow could not read which ones.",
                    "Confirm whether the Metric View needs the same restriction; if so, add it as the Metric View filter.",
                    blocking=False,
                )
            )
        else:
            buckets["business_definition"].append(
                _item(
                    name, reason or "Not migrated.",
                    "Decide: accept it as not migrated, rebuild it in the dashboard, or build it as a SQL view.",
                    blocking=False,
                )
            )

        if len(automatic) == automatic_before:
            needs_people.append(entry)

    for entry in approximations:
        buckets["business_definition"].append(
            _item(
                str(entry.get("name") or "Approximation"), str(entry.get("detail") or "Translated approximately."),
                "Translated with a difference in form only (for example Yes/No for a boolean). Confirm reports can show it this way, or correct it in metric-view.yaml.",
                blocking=False,
            )
        )

    for entry in aggregation_items:
        expression = entry.get("expression", "")
        if not expression:
            continue  # Not in the Metric View; reported with the import's reason instead.
        if not _AVERAGED.match(expression):
            automatic.append(
                {
                    "title": entry["name"],
                    "detail": "Aggregated explicitly in the Metric View (SUM, COUNT, or built from aggregates).",
                }
            )
        else:
            buckets["business_definition"].append(
                _item(
                    entry["name"],
                    f"{source} would total this with SUM by default, but the Metric View averages it.",
                    "Confirm the aggregation matches how reports total this field, or change it in metric-view.yaml.",
                    blocking=False, expression=expression,
                )
            )

    if repair.get("candidate_changed") and not repair.get("rolled_back"):
        automatic.append({"title": "Automatic repair", "detail": f"Repair changed the Metric View ({repair_status})."})

    buckets["number_checks"].append(
        _item(
            f"Compare numbers with {source}",
            f"Definitions were checked, but no values were compared with {source}.",
            f"Provide expected values from trusted {source} reports (measure, filters, expected value).",
            blocking=False,
        )
    )
    buckets["sign_off"].append(
        _item(
            "Certify for production",
            "This is a candidate Metric View.",
            "After the number checks pass, an accountable owner certifies it.",
            blocking=False,
        )
    )

    merged_automatic: dict[str, dict[str, Any]] = {}
    for entry in automatic:
        bucket = merged_automatic.setdefault(entry["detail"], {"detail": entry["detail"], "names": []})
        bucket["names"].append(entry["title"])
    automatic = [
        {
            "title": entry["names"][0] if len(entry["names"]) == 1 else f"{len(entry['names'])} items",
            "detail": entry["detail"],
            "names": entry["names"],
        }
        for entry in merged_automatic.values()
    ]

    groups = [
        {"category": key, **fill_source(CATEGORIES[key], source), "items": _merge_items(items), "blocking": any(item["blocking"] for item in items)}
        for key, items in buckets.items()
        if items
    ]
    return {
        "groups": groups,
        "automatic": automatic,
        "untranslated_needing_people": entry_field_count(needs_people),
        "_needs_people": needs_people,
        "blocking_count": sum(item["blocking"] for group in groups for item in group["items"]),
        "review_count": sum(not item["blocking"] for group in groups for item in group["items"]),
    }
