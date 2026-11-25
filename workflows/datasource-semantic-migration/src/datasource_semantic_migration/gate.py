"""Release-gate style evidence for a candidate Metric View.

Reports each group as a sequence of stages (Translation, Contract, Design, Parity,
Performance, Certify) with one status per stage, so a reader can see what was
proven, what is missing, and the single next step. Stages this workflow does not
run yet are reported as NOT_RUN rather than implied by an overall "pass".
"""

from __future__ import annotations

import re
from typing import Any

from .action_items import entry_field_count, entry_names

PASS, WARN, FAIL, NOT_RUN = "PASS", "WARN", "FAIL", "NOT_RUN"

# Division by another expression is a ratio; division by a numeric constant only rescales the value.
_DIVISION = re.compile(r"(?<![/*])/(?![/*])(?!\s*[\d.]+\b(?!\s*\())")
_DISTINCT = re.compile(r"\b(COUNT\s*\(\s*DISTINCT|APPROX_COUNT_DISTINCT)\b", re.IGNORECASE)
_AVERAGE_LIKE = re.compile(r"\b(AVG|MEAN|MEDIAN|MODE|PERCENTILE\w*|STDDEV\w*|VARIANCE|VAR_POP|VAR_SAMP)\s*\(", re.IGNORECASE)
_EXTREME = re.compile(r"\b(MIN|MAX|MIN_BY|MAX_BY)\s*\(", re.IGNORECASE)
_LATEST = re.compile(r"\b(LAST|FIRST|ANY_VALUE)\s*\(", re.IGNORECASE)
_ADDITIVE = re.compile(r"\b(SUM|COUNT|COUNT_IF)\s*\(", re.IGNORECASE)
_TEXT_RESULT = re.compile(
    r"\bTHEN\s+'[^']*'|\bCONCAT\s*\(|\bAS\s+STRING\s*\)|\bFORMAT_(NUMBER|STRING)\s*\(", re.IGNORECASE
)


def infer_additivity(expression: str) -> dict[str, str]:
    """Classify how a measure can be totalled across dimensions. Inferred from SQL; owners confirm."""
    expr = expression or ""
    # Drop string literals and quoted identifiers such as `Current Period T/F` before looking for division.
    without_strings = re.sub(r"`[^`]*`|'[^']*'|\"[^\"]*\"", "x", expr)
    if _TEXT_RESULT.search(expr):
        return {"additivity": "label", "basis": "Returns text for display, so it is not totalled."}
    if _DIVISION.search(without_strings) or re.search(r"\btry_divide\s*\(", expr, re.IGNORECASE):
        return {"additivity": "non_additive", "basis": "Ratio of aggregates: recompute it, never sum it across rows."}
    if _DISTINCT.search(expr):
        return {"additivity": "non_additive", "basis": "Distinct count: subtotals do not add up to the total."}
    if _AVERAGE_LIKE.search(expr):
        return {"additivity": "non_additive", "basis": "Average or distribution statistic: recompute it, never sum it."}
    if _LATEST.search(expr):
        return {"additivity": "semi_additive", "basis": "Point-in-time value: do not sum it over time."}
    if _EXTREME.search(expr):
        return {"additivity": "semi_additive", "basis": "Minimum or maximum: re-aggregate with MIN/MAX, not SUM."}
    if _ADDITIVE.search(expr):
        return {"additivity": "additive", "basis": "Sum or count: safe to total across any dimension."}
    if "MEASURE(" in expr.upper():
        return {"additivity": "derived", "basis": "Built from other measures; follows their additivity."}
    return {"additivity": "unknown", "basis": "No aggregate recognized; confirm how it should be totalled."}


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _stage(key: str, label: str, status: str, summary: str, next_step: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "summary": summary, "next_step": next_step, **extra}


def _translation_stage(
    *, has_candidate: bool, coverage: dict[str, Any], untranslated: list[dict[str, Any]], source: str
) -> dict[str, Any]:
    if not has_candidate:
        return _stage(
            "translation", "Translation", FAIL, "No candidate Metric View was created.",
            "Open the full report for the import error, fix the mapping or inputs, and propose again.",
        )
    translated = coverage.get("translated_metric_count")
    total = coverage.get("source_business_metric_count")
    ratio = f"{translated} of {total} {source} measures translated" if total else "Translation coverage not recorded"
    if untranslated:
        all_names = [name for item in untranslated for name in (entry_names(item) or ["unnamed"])]
        names = ", ".join(_short(name) for name in all_names[:3])
        if len(all_names) > 3:
            names += ", …"
        return _stage(
            "translation", "Translation", WARN,
            f"{ratio}; {entry_field_count(untranslated)} item(s) not migrated, each with a stated reason ({names}).",
            "Confirm each item is acceptable to leave out, or rebuild it in the dashboard or SQL.",
        )
    return _stage("translation", "Translation", PASS, f"{ratio}; nothing left out.")


def _contract_stage(*, metric_view: dict[str, Any] | None, group_mapping: dict[str, Any] | None) -> dict[str, Any]:
    tables = []
    for entry in (group_mapping or {}).get("table_mappings", []):
        target = entry.get("target", {})
        tables.append(
            {"table": target.get("table"), "grain": target.get("grain") or entry.get("source", {}).get("grain")}
        )
    measures = [
        {"name": item.get("name"), "expression": str(item.get("expr", "")), **infer_additivity(str(item.get("expr", "")))}
        for item in (metric_view or {}).get("measures", [])
        if item.get("name")
    ]
    counts: dict[str, int] = {}
    for measure in measures:
        counts[measure["additivity"]] = counts.get(measure["additivity"], 0) + 1
    missing_grain = [item["table"] for item in tables if not item["grain"]]
    unknown = [item["name"] for item in measures if item["additivity"] == "unknown"]
    breakdown = ", ".join(f"{count} {kind.replace('_', '-')}" for kind, count in sorted(counts.items())) or "no measures"
    summary = f"Grain recorded for {len(tables) - len(missing_grain)} of {len(tables)} table(s). Measures: {breakdown}."
    if not tables or missing_grain or unknown:
        problems = []
        if not tables:
            problems.append("no mapped tables were recorded for this group")
        if missing_grain:
            problems.append(f"add grain for {', '.join(str(table) for table in missing_grain)} in table-mapping.yaml")
        if unknown:
            problems.append(f"confirm how to total {', '.join(str(name) for name in unknown[:5])}")
        status, next_step = WARN, "; ".join(problems).capitalize() + "."
    else:
        status, next_step = PASS, None
    return _stage(
        "contract", "Contract", status, summary + " Additivity is inferred from each expression; owners confirm it.",
        next_step, tables=tables, measures=measures,
    )


def _design_stage(*, scorecard_evaluation: dict[str, Any] | None, repair: dict[str, Any], review_actions: list[dict[str, Any]]) -> dict[str, Any]:
    blocking_actions = [action for action in review_actions if action.get("priority") == "BLOCKING"]
    if blocking_actions:
        titles = "; ".join(str(action.get("title")) for action in blocking_actions)
        return _stage("design", "Design", FAIL, f"Blocking findings: {titles}.", "Follow the blocking actions below.")
    if not scorecard_evaluation:
        return _stage(
            "design", "Design", NOT_RUN, "Per-measure checks have not run yet.",
            "Wait for the evaluation and repair step to finish.",
        )
    scorecards = scorecard_evaluation.get("scorecards", [])
    blocking = scorecard_evaluation.get("blocking_findings", [])
    relationship_blockers = scorecard_evaluation.get("relationship_blockers", [])
    query_failed = [item for item in scorecards if item.get("status") == "FAILED_VALUE"]
    passed = sum(item.get("status") == "PASS_SEMANTIC_ONLY" for item in scorecards)
    summary = (
        f"{passed} of {len(scorecards)} measure(s) pass structure and query checks; "
        f"{len(blocking)} need a fix; {len(relationship_blockers)} unsafe join(s)."
    )
    if blocking or relationship_blockers:
        names = ", ".join(str(item.get("source_name", "unnamed")) for item in blocking[:5])
        repair_status = repair.get("status")
        repair_note = f" Automatic repair stopped ({repair_status})." if repair_status and repair_status != "READY" else ""
        return _stage(
            "design", "Design", FAIL, summary + repair_note,
            f"Fix {names or 'the unsafe joins'} as shown in the repair report, then run the Datasource semantic repair Job.",
            query_failures=len(query_failed),
        )
    unmet = [name.replace("_", " ") for name, met in (scorecard_evaluation.get("gates") or {}).items() if not met]
    if unmet:
        # Repair's own acceptance gates decide readiness; the gate must not report a pass they do not.
        return _stage(
            "design", "Design", WARN, summary + f" Acceptance checks not met: {', '.join(unmet)}.",
            "Review the repair report's coverage gates; translate or explicitly exclude the remaining measures.",
            query_failures=0,
        )
    if review_actions:
        titles = "; ".join(str(action.get("title")) for action in review_actions)
        return _stage("design", "Design", WARN, summary, f"Review: {titles}.", query_failures=0)
    return _stage("design", "Design", PASS, summary, query_failures=0)


def build_gate(
    *,
    has_candidate: bool,
    repair: dict[str, Any],
    scorecard_evaluation: dict[str, Any] | None,
    metric_view: dict[str, Any] | None,
    group_mapping: dict[str, Any] | None,
    untranslated: list[dict[str, Any]],
    review_actions: list[dict[str, Any]],
    source: str = "Tableau",
) -> dict[str, Any]:
    """source is the display name of the BI tool the Metric View was migrated from."""
    coverage = repair.get("coverage_after") or {}
    stages = [
        _translation_stage(has_candidate=has_candidate, coverage=coverage, untranslated=untranslated, source=source),
        _contract_stage(metric_view=metric_view, group_mapping=group_mapping),
        _design_stage(scorecard_evaluation=scorecard_evaluation, repair=repair, review_actions=review_actions),
        _stage(
            "parity", "Parity", NOT_RUN,
            f"Numbers have not been compared with {source}. No trusted reference values were provided.",
            f"Provide expected values from trusted {source} reports to compare against.",
        ),
        _stage(
            "performance", "Performance", NOT_RUN, "Query speed has not been measured.",
            "Time the Metric View on the dashboard's real query patterns.",
        ),
        _stage(
            "certify", "Certify", NOT_RUN, "Candidate only; not certified for production use.",
            "Certify in the release gate after parity passes.",
        ),
    ]
    first_fail = next((stage for stage in stages if stage["status"] == FAIL), None)
    first_warn = next((stage for stage in stages if stage["status"] == WARN), None)
    design = next(stage for stage in stages if stage["key"] == "design")
    if first_fail:
        status, headline, next_stage = "BLOCKED", f"Blocked at {first_fail['label']}.", first_fail
    elif design["status"] == NOT_RUN:
        status, headline, next_stage = "CHECKS_PENDING", "Per-measure checks are still running.", design
    elif first_warn:
        status, headline, next_stage = "NEEDS_REVIEW", f"Needs review at {first_warn['label']}.", first_warn
    else:
        status = "READY_FOR_PARITY"
        headline = f"Translation, contract, and design checks pass. Next: compare numbers with {source}."
        next_stage = next(stage for stage in stages if stage["key"] == "parity")
    return {
        "schema_version": "1.0",
        "status": status,
        "headline": headline,
        "next_step": next_stage["next_step"],
        "stages": stages,
    }
