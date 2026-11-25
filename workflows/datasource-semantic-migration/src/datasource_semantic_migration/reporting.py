from __future__ import annotations

from html import escape
import re
from typing import Any

from .action_items import (
    build_action_groups,
    entry_field_count,
    entry_names,
    plain_language,
    reconcile_import_exclusions,
)
from .gate import build_gate
from .source_systems import fill_source, source_label, source_system_of
from .report_html import render_workflow_html  # noqa: F401  (re-exported for notebooks)
from .proposal_handoff import build_handoff


def build_grouping_review(
    *,
    workflow_run_id: str,
    groups_index_path: str,
    grouping_proposal_path: str,
    groups: list[dict[str, Any]],
    excluded_helpers: list[dict[str, Any]],
    migration_job_id: str | None = None,
    migration_job_url: str | None = None,
    run_folder: str | None = None,
) -> dict[str, Any]:
    handoff = build_handoff(
        workflow_run_id=workflow_run_id,
        run_folder=run_folder or workflow_run_id,
        migration_job_id=migration_job_id,
        migration_job_url=migration_job_url,
    )
    return {
        "schema_version": "1.0",
        "workflow_run_id": workflow_run_id,
        "status": "AWAITING_APPROVAL",
        "headline": (
            f"Review {len(groups)} proposed semantic group(s) before starting Metric View migration."
        ),
        "groups_index_path": groups_index_path,
        "grouping_proposal_path": grouping_proposal_path,
        "groups": groups,
        "excluded_helpers": excluded_helpers,
        "migration_job_id": migration_job_id,
        "migration_job_url": migration_job_url,
        "handoff": handoff,
        "next_step": (
            "After confirming memberships, targets, and group names, start the migration Job with "
            f"proposal_run_id={workflow_run_id} so it migrates exactly this proposal."
        ),
    }


def render_grouping_review_html(review: dict[str, Any]) -> str:
    sections = []
    for group in review["groups"]:
        datasource_rows = "".join(
            f"<tr><td>{escape(item['name'])}</td><td>{escape(item['file'])}</td>"
            f"<td>{escape(item['role'])}</td></tr>"
            for item in group["datasources"]
        ) or "<tr><td colspan='3'>No datasources recorded.</td></tr>"
        target_rows = "".join(f"<li><code>{escape(table)}</code></li>" for table in group["target_tables"])
        sections.append(
            f"<section><div class='section-head'><div><p class='eyebrow'>Group {group['group_index'] + 1}</p>"
            f"<h2>{escape(group['group_name'])}</h2></div><span class='badge'>{escape(group['status'])}</span></div>"
            "<h3>Datasource membership</h3><table><thead><tr><th>Datasource</th><th>File</th><th>Role</th>"
            f"</tr></thead><tbody>{datasource_rows}</tbody></table><h3>Approved target tables</h3>"
            f"<ul>{target_rows or '<li>No approved targets.</li>'}</ul>"
            f"<p><strong>Candidate:</strong> <code>{escape(group['candidate_metric_view'])}</code></p></section>"
        )
    helper_rows = "".join(
        f"<tr><td><code>{escape(str(item.get('datasource_id', '—')))}</code></td>"
        f"<td>{escape(str(item.get('reason', '—')))}</td></tr>"
        for item in review["excluded_helpers"]
    ) or "<tr><td colspan='2'>No ungrouped UI helpers.</td></tr>"
    migration_job_id = review.get("migration_job_id")
    migration_job_url = review.get("migration_job_url") or (f"/jobs/{migration_job_id}" if migration_job_id else None)
    migration_link = (
        f"<a class='button' href='{escape(str(migration_job_url), quote=True)}' target='_blank' "
        "rel='noopener noreferrer'>Open migration Job</a>"
        if migration_job_url
        else ""
    )
    handoff = review.get("handoff") or build_handoff(
        workflow_run_id=review["workflow_run_id"],
        run_folder=review["workflow_run_id"],
        migration_job_id=migration_job_id,
        migration_job_url=migration_job_url,
    )
    ui_steps = "".join(f"<li>{escape(step)}</li>" for step in handoff["jobs_ui_steps"])
    handoff_html = (
        "<div class='next'><strong>Approve this proposal</strong>"
        "<p>Confirm the group membership and target tables below, then start the migration Job for this exact run.</p>"
        f"<p class='run-id'>proposal_run_id <code>{escape(handoff['proposal_run_id'])}</code>"
        f"<span>Run folder <code>{escape(handoff['run_folder'])}</code></span></p>"
        f"<h3>In the Jobs UI</h3><ol>{ui_steps}</ol>"
        f"<h3>From the Databricks CLI</h3><pre>{escape(handoff['cli_command'])}</pre>"
        f"<p class='muted'>{escape(handoff['automatic_resolution'])} "
        "Each proposal can be migrated once; use force_rerun=true only to migrate it again deliberately.</p>"
        f"{migration_link}</div>"
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Semantic grouping review</title>"
        "<style>body{font:14px system-ui;margin:0;background:#f5f6f7;color:#0b2026}main{max-width:1100px;margin:auto;padding:32px}"
        "h1{font-size:30px;margin:4px 0}h2{font-size:20px;margin:4px 0}h3{margin-top:24px}.eyebrow{color:#5d6b70;text-transform:uppercase;font-weight:700;letter-spacing:.08em}"
        "section{background:white;border:1px solid #dce0e2;border-radius:8px;padding:20px;margin-top:18px}.section-head{display:flex;justify-content:space-between;gap:24px}"
        ".badge{font-weight:700;color:#b52815}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #e7e9ea;padding:9px;text-align:left;vertical-align:top}"
        "th{background:#f7f8f9}code{overflow-wrap:anywhere}.next{border-left:4px solid #ff3621;padding:16px;background:white;margin:24px 0}"
        ".button{display:inline-block;margin-top:12px;padding:9px 14px;border-radius:4px;background:#ff3621;color:white;text-decoration:none;font-weight:700}"
        ".run-id{font-size:16px}.run-id code{font-size:18px;font-weight:700}.run-id span{margin-left:18px;color:#5d6b70;font-size:13px}"
        "pre{background:#0b2026;color:white;padding:12px;border-radius:4px;overflow-x:auto;white-space:pre-wrap;word-break:break-all}"
        ".muted{color:#5d6b70}</style>"
        "</head><body><main>"
        f"<p class='eyebrow'>Workflow {escape(review['workflow_run_id'])}</p><h1>Review semantic groups</h1>"
        f"<p>{escape(review['headline'])}</p>{handoff_html}{''.join(sections)}"
        f"<section><h2>Excluded UI helpers</h2><table><thead><tr><th>Datasource ID</th><th>Reason</th></tr>"
        f"</thead><tbody>{helper_rows}</tbody></table></section></main></body></html>\n"
    )


def _is_technical_untranslated(item: dict[str, Any]) -> bool:
    reason = item.get("reason", "").casefold()
    return "hidden relationship key" in reason or "generated ui field" in reason


def _created_items(value: Any) -> tuple[int, list[str]]:
    """Count and names for a created-items field; the import may record a list of names or only a count."""
    if isinstance(value, bool):
        return 0, []
    if isinstance(value, int):
        return value, []
    names = [str(name) for name in value or []]
    return len(names), names


def _action(action_id: str, priority: str, title: str, description: str, items: list[str]) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "priority": priority,
        "title": title,
        "description": description,
        "items": items,
    }


def build_group_review(
    *,
    group: dict[str, Any],
    final_result: dict[str, Any],
    evaluation: dict[str, Any],
    metric_view: dict[str, Any] | None = None,
    scorecard_evaluation: dict[str, Any] | None = None,
    group_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = source_label(group)
    agent_result = evaluation.get("agent_result") or {}
    measure_expressions = {
        str(item.get("name")): str(item.get("expr", "")).strip()
        for item in (metric_view or {}).get("measures", [])
        if item.get("name")
    }
    dimension_count, dimensions = _created_items(agent_result.get("dimensions_created"))
    measure_count, measures = _created_items(agent_result.get("measures_created"))
    parameter_count, parameters = _created_items(agent_result.get("parameters_created"))
    # A result rebuilt from the catalog cannot know which source fields were left out.
    untranslated_known = agent_result.get("status") != "RECOVERED_FROM_CATALOG"
    untranslated = agent_result.get("items_not_translated", [])
    business_untranslated = [item for item in untranslated if not _is_technical_untranslated(item)]
    technical_exclusions = [item for item in untranslated if _is_technical_untranslated(item)]
    approximations = agent_result.get("approximations", [])
    findings = evaluation.get("findings", [])
    blocking_findings = [item for item in findings if item.get("severity") == "ERROR"]
    warning_findings = [item for item in findings if item.get("severity") == "WARNING"]
    repair = evaluation.get("repair") or {}
    translated_count = dimension_count + measure_count

    actions = []
    external_fields = sorted(
        {
            item.get("calculation_name", item.get("message", "External datasource reference"))
            for item in blocking_findings
            if item.get("code") == "EXTERNAL_DATASOURCE_REFERENCE"
        }
    )
    if external_fields:
        actions.append(
            _action(
                "map_external_datasource",
                "BLOCKING",
                "Map or explicitly exclude external datasource calculations",
                "Add the referenced datasource and its approved Databricks target to the input contract, or record an intentional exclusion before rerunning.",
                external_fields,
            )
        )
    other_blocking = [
        item.get("calculation_name") or item.get("code", "Blocking finding")
        for item in blocking_findings
        if item.get("code") != "EXTERNAL_DATASOURCE_REFERENCE"
    ]
    if other_blocking:
        actions.append(
            _action(
                "resolve_blocking_findings",
                "BLOCKING",
                "Resolve blocking semantic findings",
                "Correct the approved mapping or candidate definition, then rerun evaluation.",
                sorted(other_blocking),
            )
        )
    aggregation_items = sorted(
        {
            item.get("calculation_name", "Unnamed calculation")
            for item in warning_findings
            if item.get("code") == "AGGREGATION_REQUIRES_COMPILATION"
        }
    )
    # Measures built from other measures (MEASURE(...)) inherit their aggregation; only raw ones need a check.
    aggregation_items = [
        name for name in aggregation_items if "MEASURE(" not in measure_expressions.get(name, "").upper()
    ]
    # SUM is the BI tools' default for numeric fields, so only other aggregations need a person.
    aggregations_needing_review = [
        name for name in aggregation_items if not re.match(r"^\s*SUM\s*\(", measure_expressions.get(name, ""), re.IGNORECASE)
    ]
    if aggregations_needing_review:
        aggregation_action = _action(
            "confirm_aggregations",
            "REVIEW",
            "Check how these measures are totalled",
            f"In {source} these formulas are calculated per row, and each report decides how to total them. "
            "A Metric View must fix one way to total each measure, so the workflow chose one (shown below). "
            "If a choice matches how your reports total the field, no action is needed.",
            aggregations_needing_review,
        )
        aggregation_action["details"] = [
            {"name": name, "expression": measure_expressions.get(name) or "Expression not recorded"}
            for name in aggregations_needing_review
        ]
        aggregation_action["how_to_fix"] = (
            f"To change one, edit that measure's expr in {group['group_path']}/metric-view.yaml "
            "(for example SUM to AVG), then run the Datasource semantic repair Job with "
            f"group_path={group['group_path']}. Repair redeploys the Metric View and re-checks it."
        )
        actions.append(aggregation_action)
    if approximations:
        actions.append(
            _action(
                "review_approximations",
                "REVIEW",
                "Review differences in form",
                "These measures and fields give the same results as the source but are shown differently, for example Yes/No for a boolean. Confirm each one suits your reports.",
                [item.get("name", "Unnamed approximation") for item in approximations],
            )
        )
    # Measures the import left out on purpose (with a reason) are not missing-measure failures.
    scorecard_evaluation = reconcile_import_exclusions(scorecard_evaluation, business_untranslated)
    action_groups = build_action_groups(
        scorecard_evaluation=scorecard_evaluation,
        evaluation_findings=findings,
        business_untranslated=business_untranslated,
        approximations=approximations,
        aggregation_items=[
            {"name": name, "expression": measure_expressions.get(name, "")}
            for name in aggregation_items
        ],
        group_mapping=group_mapping,
        repair=repair,
        has_candidate=bool(final_result.get("metric_view_fqn")),
        source=source,
    )
    # Dashboard-only items are not part of the model, so they do not lower semantic coverage.
    human_untranslated = action_groups.pop("_needs_people")
    # Count fields, not entries: one entry such as "Profit, Margin" leaves out two fields.
    untranslated_field_count = entry_field_count(human_untranslated)
    semantic_item_count = translated_count + untranslated_field_count
    coverage_percent = (
        round(100 * translated_count / semantic_item_count, 1) if semantic_item_count else 0.0
    ) if untranslated_known else None
    gate = build_gate(
        has_candidate=bool(final_result.get("metric_view_fqn")),
        repair=repair,
        scorecard_evaluation=scorecard_evaluation,
        metric_view=metric_view,
        group_mapping=group_mapping,
        untranslated=human_untranslated,
        review_actions=[
            {"priority": "BLOCKING" if action_group["blocking"] else "REVIEW", "title": action_group["label"]}
            for action_group in action_groups["groups"]
            # Business decisions are reported under Translation; Design covers expressions, data, and access.
            if action_group["category"] in {"calculation", "access_platform", "data_mapping"}
        ],
        source=source,
    )
    readiness = {"BLOCKED": "BLOCKED", "NEEDS_REVIEW": "NEEDS_REVIEW", "CHECKS_PENDING": "NEEDS_REVIEW"}.get(
        gate["status"], "READY"
    )
    headline = gate["headline"]
    group_path = group["group_path"]
    internal_path = group.get("internal_path") or f"{group_path}/_internal"
    report_path = group.get("report_path")
    return {
        "group_id": group["group_id"],
        "display_name": group.get("display_name"),
        "source_system": source_system_of(group),
        "status": final_result["status"],
        "readiness": readiness,
        "headline": headline,
        "candidate": {
            "metric_view_fqn": final_result.get("metric_view_fqn"),
            "definition_path": f"{group_path}/metric-view.yaml",
            "sql_definition_path": f"{group_path}/metric-view.sql",
        },
        "coverage": {
            "semantic_coverage_percent": coverage_percent,
            "dimensions_created": dimension_count,
            "measures_created": measure_count,
            "parameters_created": parameter_count,
            "business_items_not_translated": untranslated_field_count,
            "technical_items_excluded": len(technical_exclusions),
            "dimension_names": dimensions,
            "measure_names": measures,
            "parameters": parameters,
        },
        "validation": agent_result.get("validation", {}),
        "blocking_findings": blocking_findings,
        "warning_findings": warning_findings,
        "items_not_translated": business_untranslated,
        "technical_exclusions": technical_exclusions,
        "approximations": approximations,
        "recommended_actions": actions,
        "gate": gate,
        "action_groups": action_groups,
        "notes": agent_result.get("notes", []),
        "repair": repair,
        "report_path": report_path,
        "artifacts": {
            "source_summary": group.get("source_summary_path"),
            "mapping": f"{group_path}/mapping.yaml",
            "target_profile": f"{internal_path}/target-profile.json",
            "import_prompt": f"{internal_path}/importbi-prompt.md",
            "import_result": f"{internal_path}/importbi-result.json",
            "evaluation": final_result.get("evaluation_path"),
            "final_result": f"{internal_path}/final-result.json",
            "repair_latest": f"{internal_path}/repair/latest.json",
        },
    }


def build_workflow_review(*, workflow_run_id: str, groups: list[dict[str, Any]]) -> dict[str, Any]:
    blocking = sum(group["readiness"] == "BLOCKED" for group in groups)
    ready = sum(group["readiness"] == "READY" for group in groups)
    needs_review = sum(group["readiness"] == "NEEDS_REVIEW" for group in groups)
    status = "READY" if groups and ready == len(groups) else "ACTION_REQUIRED" if blocking else "REVIEW_REQUIRED"
    actions = [
        {**action, "group_id": group["group_id"]}
        for group in groups
        for action in group["recommended_actions"]
    ]
    return {
        "schema_version": "1.0",
        "workflow_run_id": workflow_run_id,
        "status": status,
        "headline": (
            f"{len(groups)} semantic group(s) evaluated: {ready} ready, {needs_review} need review, {blocking} blocked."
        ),
        "totals": {
            "semantic_groups": len(groups),
            "candidates_created": sum(bool(group["candidate"]["metric_view_fqn"]) for group in groups),
            "ready": ready,
            "needs_review": needs_review,
            "blocked": blocking,
            "dimensions_created": sum(group["coverage"]["dimensions_created"] for group in groups),
            "measures_created": sum(group["coverage"]["measures_created"] for group in groups),
            "business_items_not_translated": sum(
                group["coverage"]["business_items_not_translated"] for group in groups
            ),
            "approximations": sum(len(group["approximations"]) for group in groups),
            "actions": sum(
                group["action_groups"]["blocking_count"] + group["action_groups"]["review_count"]
                if group.get("action_groups")
                else len(group["recommended_actions"])
                for group in groups
            ),
        },
        "recommended_actions": actions,
        "groups": groups,
    }


METRIC_STATUS_GUIDE = {
    "PASS_SEMANTIC_ONLY": {
        "meaning": "The target measure exists and passed structural semantic checks.",
        "limitation": "This does not prove numeric parity with {source} source data.",
    },
    "FAILED_SEMANTICS": {
        "meaning": "The target measure is missing or its definition conflicts with known {source} semantics.",
        "limitation": "No claim about numeric values is made because the definition is not yet valid.",
    },
    "FAILED_SEMANTIC": {
        "meaning": "Alias of FAILED_SEMANTICS used by older artifacts.",
        "limitation": "The metric definition requires repair before value comparison.",
    },
    "FAILED_VALUE": {
        "meaning": "The target measure exists, but its generated Metric View query failed.",
        "limitation": "Inspect the recorded SQL and engine error; this is not necessarily a numeric mismatch.",
    },
    "BLOCKED_UNRESOLVED_MAPPING": {
        "meaning": "The {source} calculation depends on a datasource or field absent from the approved mapping.",
        "limitation": "Automatic repair cannot invent an approved target.",
    },
    "EXCLUDED_UNSUPPORTED": {
        "meaning": "The source item is intentionally excluded under a governed unsupported-item disposition.",
        "limitation": "It counts as governed, but not translated or evidenced.",
    },
}

FAILURE_CODE_GUIDE = {
    "MISSING_TARGET_MEASURE": {
        "meaning": "This {source} measure has no matching measure in the Metric View.",
        "action": (
            "Automatic repair asks Genie to add it. If it is still missing, add the measure to "
            "groups/<group>/metric-view.yaml and run the Datasource semantic repair Job, or accept it as not migrated."
        ),
    },
    "NEEDS_SEMANTIC_TRANSLATION": {
        "meaning": "The formula could not be translated by rule, so it needs Genie or a person to translate it.",
        "action": (
            "Automatic repair tries Genie first. If that fails, write the equivalent SQL expression in "
            "groups/<group>/metric-view.yaml and run the Datasource semantic repair Job."
        ),
    },
    "AGGREGATION_MISMATCH": {
        "meaning": (
            "{source} calculates this formula per row, so the Metric View must say how to total it "
            "(SUM, AVG, COUNT, or built from other measures with MEASURE()). The generated expression does neither."
        ),
        "action": (
            "Wrap the expression in the aggregate your reports use, e.g. SUM(<expression>), in "
            "groups/<group>/metric-view.yaml, then run the Datasource semantic repair Job."
        ),
    },
    "MEASURE_QUERY_FAILED": {
        "meaning": "Running SELECT MEASURE(...) on the Metric View returned an error; the error text is shown with it.",
        "action": (
            "Common causes: a column renamed or missing in the mapped table, no SELECT permission on the table, "
            "or a type mismatch. Fix the table or mapping (then propose again), or fix the expression in "
            "groups/<group>/metric-view.yaml and run the Datasource semantic repair Job."
        ),
    },
    "EXTERNAL_DATASOURCE_UNMAPPED": {
        "meaning": "The calculation uses a field from another {source} datasource that table-mapping.yaml does not map.",
        "action": "Add that datasource's tables to table-mapping.yaml, then run Propose semantic groups again.",
    },
    "UNSUPPORTED_METRIC_SHAPE": {
        "meaning": (
            "The calculation uses a {source} feature with no Metric View equivalent, such as a table calculation "
            "(INDEX, RUNNING_SUM) that depends on the worksheet layout."
        ),
        "action": "No fix in the Metric View. Rebuild it in the dashboard or a SQL view, or accept it as not migrated.",
    },
}

COVERAGE_GATE_GUIDE = {
    "translation_coverage": {
        "label": "Translation Coverage",
        "numerator": "translated_metric_count",
        "denominator": "source_business_metric_count",
        "threshold": "overall_metric_translation_coverage",
        "definition": "Source business metrics with a matching target Metric View measure.",
    },
    "governed_disposition_coverage": {
        "label": "Governed Disposition Coverage",
        "numerator": "governed_metric_count",
        "denominator": "source_business_metric_count",
        "threshold": "governed_disposition_coverage",
        "definition": "Source metrics that either pass or have an explicit governed exclusion/not-comparable disposition.",
    },
    "evidence_coverage": {
        "label": "Evidence Coverage",
        "numerator": "evidenced_metric_count",
        "denominator": "source_business_metric_count",
        "threshold": "retained_metric_evidence_coverage",
        "definition": "Source metrics with retained passing evidence. Semantic-only evidence proves structure, not {source} numeric parity.",
    },
    "measure_queryability": {
        "label": "Measure Queryability",
        "numerator": "query_pass_count",
        "denominator": "query_candidate_count",
        "threshold": "measure_queryability",
        "definition": "Translated target measures whose generated MEASURE query executed successfully. NOT_RUN is not a pass.",
    },
}


def _coverage_gate_details(
    before: dict[str, Any],
    after: dict[str, Any],
    policy: dict[str, Any],
    source: str,
) -> list[dict[str, Any]]:
    details = []
    for metric_name, guide in fill_source(COVERAGE_GATE_GUIDE, source).items():
        numerator_key = guide["numerator"]
        denominator_key = guide["denominator"]
        numerator = int(after.get(numerator_key, 0))
        denominator = int(after.get(denominator_key, 0))
        before_numerator = int(before.get(numerator_key, round(float(before.get(metric_name, 0)) * denominator)))
        before_denominator = int(before.get(denominator_key, denominator))
        threshold = float(policy.get(guide["threshold"], 1.0))
        value = float(after.get(metric_name, 0))
        required = int(threshold * denominator + 0.999999) if denominator else 0
        details.append(
            {
                "metric": metric_name,
                "label": guide["label"],
                "definition": guide["definition"],
                "before": float(before.get(metric_name, 0)),
                "after": value,
                "threshold": threshold,
                "passed": value >= threshold,
                "before_formula": f"{before_numerator}/{before_denominator}" if before_denominator else "0/0",
                "after_formula": f"{numerator}/{denominator}" if denominator else "0/0",
                "gap_count": max(required - numerator, 0),
            }
        )
    return details


def _scorecard_explanation(scorecard: dict[str, Any], source: str) -> dict[str, Any]:
    status = str(scorecard.get("status", "UNKNOWN"))
    status_help = fill_source(METRIC_STATUS_GUIDE, source).get(
        status,
        {"meaning": "No plain-language definition is registered for this status.", "limitation": "Review the raw scorecard."},
    )
    failure_details = [
        {"code": code, **fill_source(FAILURE_CODE_GUIDE, source).get(code, {"meaning": "Unknown failure code.", "action": "Review manually."})}
        for code in scorecard.get("failure_codes", [])
    ]
    query = scorecard.get("query") or {"status": scorecard.get("queryability", "NOT_RUN")}
    query_status = str(query.get("status", "NOT_RUN"))
    if query_status == "PASS":
        query_reason = "The generated Metric View query executed successfully."
    elif query_status == "FAIL":
        query_reason = str(query.get("error") or "The generated Metric View query failed without a captured error.")
    else:
        query_reason = str(query.get("reason") or "No query result was recorded.")
    return {
        **scorecard,
        "status_meaning": status_help["meaning"],
        "status_limitation": status_help["limitation"],
        "failure_details": failure_details,
        "query_detail": {
            "status": query_status,
            "reason": query_reason,
            "sql": query.get("sql"),
        },
        "recommended_action": failure_details[0]["action"] if failure_details else "No repair action required.",
    }


def build_repair_review(*, summary: dict[str, Any], evaluation: dict[str, Any], source: str = "Tableau") -> dict[str, Any]:
    """source is the display name of the BI tool the Metric View was migrated from."""
    before = summary.get("coverage_before", {})
    after = summary.get("coverage_after", {})
    policy = summary.get("policy") or evaluation.get("policy") or {}
    scorecards = [_scorecard_explanation(item, source) for item in evaluation.get("scorecards", [])]
    gates = _coverage_gate_details(before, after, policy, source)
    failed_gates = [item for item in gates if not item["passed"]]
    blocking_findings = [_scorecard_explanation(item, source) for item in evaluation.get("blocking_findings", [])]
    not_run = [item for item in scorecards if item["query_detail"]["status"] == "NOT_RUN"]
    not_applicable = [item for item in scorecards if item["query_detail"]["status"] == "NOT_APPLICABLE"]
    query_failed = [item for item in scorecards if item["query_detail"]["status"] == "FAIL"]
    status = str(summary.get("status"))
    readiness = str(summary.get("readiness"))
    decision_reasons = [
        f"{item['label']} is {item['after']:.1%}; target is {item['threshold']:.1%}. "
        f"Resolve {item['gap_count']} additional metric(s)."
        for item in failed_gates
    ]
    if evaluation.get("relationship_blockers"):
        decision_reasons.append(f"{len(evaluation['relationship_blockers'])} unsafe relationship check(s) remain blocked.")
    progress = summary.get("progress") or {}
    if status == "NO_PROGRESS":
        decision_reasons.insert(
            0,
            str(
                progress.get("reason")
                or "The repair changed the candidate but did not improve coverage or remove a blocker, so retry stopped."
            ),
        )
    if summary.get("rolled_back"):
        decision_reasons.insert(
            0,
            f"Candidate changes were rolled back ({summary.get('rollback_reason') or 'unspecified reason'}).",
        )
    if not decision_reasons:
        decision_reasons.append("All configured semantic repair gates passed.")
    return {
        "schema_version": "1.0",
        "workflow_run_id": summary.get("workflow_run_id"),
        "group_id": summary.get("group_id"),
        "repair_series_id": summary.get("repair_series_id"),
        "attempt": summary.get("attempt"),
        "status": status,
        "readiness": readiness,
        "headline": (
            f"Repair finished as {status}: {len(failed_gates)} coverage gate(s) failed, "
            f"{len(blocking_findings)} metric(s) require action, and {len(query_failed)} query test(s) failed."
        ),
        "coverage_before": before,
        "coverage_after": after,
        "candidate_changed": summary.get("candidate_changed", False),
        "rolled_back": summary.get("rolled_back", False),
        "regressions": summary.get("regressions", []),
        "rollback_reason": summary.get("rollback_reason"),
        "progress": progress,
        "decision_reasons": decision_reasons,
        "coverage_gates": gates,
        "blocking_findings": blocking_findings,
        "relationship_blockers": evaluation.get("relationship_blockers", []),
        "scorecards": scorecards,
        "query_execution": {
            "translated_measures": int(after.get("query_candidate_count", 0)),
            "passed": int(after.get("query_pass_count", 0)),
            "failed": int(after.get("query_fail_count", 0)),
            "not_run": int(after.get("query_not_run_count", 0)),
            "not_run_metrics": [item["source_name"] for item in not_run],
            "not_applicable_metrics": [item["source_name"] for item in not_applicable],
        },
        "status_guide": fill_source(METRIC_STATUS_GUIDE, source),
        "failure_code_guide": fill_source(FAILURE_CODE_GUIDE, source),
        "attempt_dir": summary.get("attempt_dir"),
        "artifacts": {
            "query_results_before": f"{summary.get('attempt_dir')}/query-results-before.json",
            "query_results_after": f"{summary.get('attempt_dir')}/query-results-after.json",
            "evaluation_before": f"{summary.get('attempt_dir')}/evaluation-summary.json",
            "evaluation_attempted": f"{summary.get('attempt_dir')}/evaluation-attempted.json",
            "evaluation_after": f"{summary.get('attempt_dir')}/evaluation-after.json",
            "metric_scorecards": f"{summary.get('attempt_dir')}/metric-scorecards.json",
        },
        "next_run_id": summary.get("next_run_id"),
    }


def render_repair_html(review: dict[str, Any]) -> str:
    coverage_parts = []
    for item in review["coverage_gates"]:
        result_label = "PASS" if item["passed"] else f"FAIL — {item['gap_count']} metric(s) short"
        result_class = "pass" if item["passed"] else "fail"
        coverage_parts.append(
            f"<tr><td><strong>{escape(item['label'])}</strong><br><small>{escape(item['definition'])}</small></td>"
            f"<td>{escape(item['before_formula'])}<br>{item['before']:.1%}</td>"
            f"<td>{escape(item['after_formula'])}<br>{item['after']:.1%}</td>"
            f"<td>{item['threshold']:.1%}</td><td class='{result_class}'>{escape(result_label)}</td></tr>"
        )
    coverage_rows = "".join(coverage_parts)
    decision_rows = "".join(f"<li>{escape(item)}</li>" for item in review["decision_reasons"])
    blocking_parts = []
    for item in review["blocking_findings"]:
        failure_details = "<br>".join(
            f"<code>{escape(detail['code'])}</code>: {escape(detail['meaning'])}"
            for detail in item["failure_details"]
        )
        blocking_parts.append(
            f"<tr><td>{escape(item.get('source_name', '—'))}</td><td>{failure_details}</td>"
            f"<td>{escape(item['query_detail']['status'])}<br><small>{escape(item['query_detail']['reason'])}</small></td>"
            f"<td>{escape(item['recommended_action'])}</td></tr>"
        )
    blocking_rows = "".join(blocking_parts) or "<tr><td colspan='4'>No blocking findings.</td></tr>"
    scorecard_parts = []
    for item in review["scorecards"]:
        query_sql = item["query_detail"].get("sql")
        sql_details = (
            f"<details><summary>SQL</summary><code>{escape(query_sql)}</code></details>" if query_sql else ""
        )
        scorecard_parts.append(
            f"<tr><td>{escape(item.get('source_name', '—'))}</td><td>{escape(item.get('target_name') or '—')}</td>"
            f"<td><code>{escape(item.get('status', '—'))}</code><br><small>{escape(item['status_meaning'])}</small></td>"
            f"<td>{escape(item['query_detail']['status'])}<br><small>{escape(item['query_detail']['reason'])}</small>"
            f"{sql_details}</td></tr>"
        )
    scorecard_rows = "".join(scorecard_parts)
    status_rows = "".join(
        f"<tr><td><code>{escape(code)}</code></td><td>{escape(detail['meaning'])}</td><td>{escape(detail['limitation'])}</td></tr>"
        for code, detail in review["status_guide"].items()
    )
    failure_rows = "".join(
        f"<tr><td><code>{escape(code)}</code></td><td>{escape(detail['meaning'])}</td><td>{escape(detail['action'])}</td></tr>"
        for code, detail in review["failure_code_guide"].items()
    )
    query = review["query_execution"]
    artifact_rows = "".join(
        f"<tr><td>{escape(name.replace('_', ' ').title())}</td><td><code>{escape(path)}</code></td></tr>"
        for name, path in review["artifacts"].items()
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Metric View repair review</title>"
        "<style>body{font:14px system-ui;margin:0;background:#f5f6f7;color:#0b2026}main{max-width:1100px;margin:auto;padding:32px}"
        "section{background:white;border:1px solid #dce0e2;border-radius:8px;padding:20px;margin-top:18px}"
        "h1{font-size:30px}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #e7e9ea;padding:9px;text-align:left;vertical-align:top}"
        "th{background:#f7f8f9}.badge{color:#b52815;font-weight:700}.pass{color:#237804;font-weight:700}.fail{color:#b52815;font-weight:700}"
        "small{color:#5d6b70}code{overflow-wrap:anywhere}details{margin-top:6px}</style></head><body><main>"
        f"<p>Semantic group: {escape(str(review['group_id']))}</p><h1>Metric View repair review</h1>"
        f"<p class='badge'>{escape(str(review['status']))}</p><p>{escape(review['headline'])}</p>"
        f"<section><h2>Decision</h2><ul>{decision_rows}</ul></section>"
        f"<section><h2>Coverage gates</h2><table><thead><tr><th>Gate and meaning</th><th>Before</th><th>After</th><th>Required</th><th>Result</th></tr></thead><tbody>{coverage_rows}</tbody></table></section>"
        f"<section><h2>Query execution</h2><p>{query['passed']} of {query['translated_measures']} translated measures executed successfully; "
        f"{query['failed']} failed and {query['not_run']} were not run.</p><p><strong>Not run:</strong> {escape(', '.join(query['not_run_metrics']) or 'None')}. "
        f"<strong>Not applicable because no target exists:</strong> {escape(', '.join(query['not_applicable_metrics']) or 'None')}.</p></section>"
        f"<section><h2>Actions required</h2><table><thead><tr><th>Metric</th><th>Problem and meaning</th><th>Query</th><th>Next action</th></tr></thead><tbody>{blocking_rows}</tbody></table></section>"
        f"<section><h2>Metric scorecards</h2><table><thead><tr><th>Source metric</th><th>Target measure</th><th>Semantic status</th><th>Query evidence</th></tr></thead><tbody>{scorecard_rows}</tbody></table></section>"
        f"<section><h2>Status glossary</h2><table><thead><tr><th>Status</th><th>Meaning</th><th>Limitation</th></tr></thead><tbody>{status_rows}</tbody></table></section>"
        f"<section><h2>Failure-code glossary</h2><table><thead><tr><th>Code</th><th>Meaning</th><th>Action</th></tr></thead><tbody>{failure_rows}</tbody></table></section>"
        f"<section><h2>Evidence artifacts</h2><table><thead><tr><th>Artifact</th><th>Volume path</th></tr></thead><tbody>{artifact_rows}</tbody></table></section>"
        "</main></body></html>\n"
    )
