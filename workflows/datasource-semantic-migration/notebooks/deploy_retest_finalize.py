# Databricks notebook source
import json
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

from datasource_semantic_migration.metric_repair import (
    create_metric_view_sql,
    document_hash,
    evaluate_candidate,
    evaluate_progress,
    target_lineage,
)
from datasource_semantic_migration.notebook_results import format_notebook_result, render_volume_links_html
from datasource_semantic_migration.reporting import (
    build_group_review,
    build_repair_review,
    build_workflow_review,
    render_repair_html,
    render_workflow_html,
)
from datasource_semantic_migration.tableau_parser import write_json_artifact

# Used for Catalog Explorer links in the HTML reports.
WORKSPACE_URL = "https://" + spark.conf.get("spark.databricks.workspaceUrl").removeprefix("https://").rstrip("/")


for widget_name in (
    "group_path",
    "attempt_dir",
    "repair_series_id",
    "attempt",
    "max_attempts",
    "repair_job_id",
    "requested_by",
):
    dbutils.widgets.text(widget_name, "")

group_path = Path(dbutils.widgets.get("group_path").rstrip("/"))
group_internal_path = group_path / "_internal"
if not (group_internal_path / "group-manifest.json").is_file():
    group_internal_path = group_path
attempt_dir = Path(dbutils.widgets.get("attempt_dir"))
repair_series_id = dbutils.widgets.get("repair_series_id").strip()
attempt = int(dbutils.widgets.get("attempt") or "1")
max_attempts = int(dbutils.widgets.get("max_attempts") or "3")
repair_job_id = int(dbutils.widgets.get("repair_job_id") or "0")
requested_by = dbutils.widgets.get("requested_by").strip()
manifest = json.loads((group_internal_path / "group-manifest.json").read_text(encoding="utf-8"))
target_profile = json.loads((group_internal_path / "target-profile.json").read_text(encoding="utf-8"))
source_metric_irs = [
    json.loads(Path(datasource["metric_ir_path"]).read_text(encoding="utf-8"))
    for datasource in manifest["datasources"]
]
before = yaml.safe_load((attempt_dir / "candidate-before.yaml").read_text(encoding="utf-8")) or {}
deterministic = yaml.safe_load((attempt_dir / "candidate-deterministic.yaml").read_text(encoding="utf-8")) or {}
genie_path = attempt_dir / "candidate-genie.yaml"
genie_patch_path = attempt_dir / "genie-patch.json"
genie_patch = json.loads(genie_patch_path.read_text(encoding="utf-8")) if genie_patch_path.is_file() else None
if genie_patch is not None:
    missing_patch_fields = {
        "schema_version", "patch_id", "status", "failure_ids", "operations", "notes", "confidence"
    } - set(genie_patch)
    if missing_patch_fields:
        raise ValueError(f"Genie patch is missing required fields: {sorted(missing_patch_fields)}")
    if genie_patch["status"] not in {"APPLIED", "NOOP", "UNRESOLVABLE"}:
        raise ValueError(f"Unsupported Genie patch status: {genie_patch['status']}")
    if genie_patch["status"] == "APPLIED" and not genie_path.is_file():
        raise FileNotFoundError(f"Applied Genie patch did not write candidate YAML: {genie_path}")
candidate = yaml.safe_load(genie_path.read_text(encoding="utf-8")) if genie_path.is_file() else deterministic
candidate = candidate or {}
allowed_tables = set(manifest["target_tables"])
unexpected_tables = sorted(set(target_lineage(candidate)) - allowed_tables)
if unexpected_tables:
    raise RuntimeError(f"Candidate patch references disallowed tables: {unexpected_tables}")
if not candidate.get("measures"):
    raise RuntimeError("Candidate patch defines no measures")

before_hash = document_hash(before)
candidate_hash = document_hash(candidate)
changed = before_hash != candidate_hash
metric_view_fqn = manifest["candidate_metric_view_fqn"]
if changed:
    spark.sql(create_metric_view_sql(metric_view_fqn, candidate))

quoted_fqn = ".".join(f"`{part}`" for part in metric_view_fqn.split("."))
query_results = {}
for measure in candidate.get("measures", []):
    name = str(measure.get("name", ""))
    escaped_name = name.replace("`", "``")
    query_sql = f"SELECT MEASURE(`{escaped_name}`) FROM {quoted_fqn}"
    try:
        spark.sql(query_sql).limit(1).collect()
        query_results[name.casefold()] = {"status": "PASS", "sql": query_sql}
    except Exception as error:
        query_results[name.casefold()] = {"status": "FAIL", "sql": query_sql, "error": str(error)[:1000]}

evaluation = evaluate_candidate(
    source_metric_irs=source_metric_irs,
    metric_view=candidate,
    target_profile=target_profile,
    query_results=query_results,
)
initial_evaluation = json.loads((attempt_dir / "evaluation-summary.json").read_text(encoding="utf-8"))
before_query_results = json.loads((attempt_dir / "query-results-before.json").read_text(encoding="utf-8"))
regressions = [
    {"measure": name, "before": "PASS", "after": query_results.get(name, {}).get("status", "MISSING")}
    for name, result in before_query_results.items()
    if result.get("status") == "PASS" and query_results.get(name, {}).get("status") != "PASS"
]
rolled_back = False
rollback_reason = None
if regressions and changed:
    spark.sql(create_metric_view_sql(metric_view_fqn, before))
    candidate = before
    candidate_hash = before_hash
    changed = False
    rolled_back = True
    rollback_reason = "QUERY_REGRESSION"
    evaluation["readiness"] = "REGRESSION_REJECTED"

attempted_evaluation = evaluation
progress = evaluate_progress(initial_evaluation, attempted_evaluation)
if changed and not rolled_back and not progress["measurable_improvement"]:
    spark.sql(create_metric_view_sql(metric_view_fqn, before))
    candidate = before
    candidate_hash = before_hash
    changed = False
    rolled_back = True
    rollback_reason = "NO_MEASURABLE_PROGRESS"
    query_results = before_query_results
    evaluation = initial_evaluation

(attempt_dir / "candidate-after.yaml").write_text(
    yaml.safe_dump(candidate, sort_keys=False, width=120), encoding="utf-8"
)
write_json_artifact(query_results, attempt_dir / "query-results-after.json")
write_json_artifact(attempted_evaluation, attempt_dir / "evaluation-attempted.json")
write_json_artifact(
    {"regressions": regressions, "rolled_back": rolled_back, "rollback_reason": rollback_reason},
    attempt_dir / "regression-results.json",
)
write_json_artifact(evaluation, attempt_dir / "evaluation-after.json")

next_run_id = None
if evaluation["readiness"] == "READY":
    status = "READY"
elif genie_patch and genie_patch["status"] == "UNRESOLVABLE":
    status = "UNRESOLVABLE_AUTOMATICALLY"
elif initial_evaluation["needs_genie"] and genie_patch is None:
    status = "GENIE_OUTPUT_MISSING"
elif evaluation["readiness"] in {"BLOCKED_EVIDENCE", "REGRESSION_REJECTED"}:
    status = evaluation["readiness"]
elif not progress["measurable_improvement"]:
    status = "NO_PROGRESS"
elif attempt >= max_attempts:
    status = "EXHAUSTED"
else:
    status = "RETRYING"
    response = WorkspaceClient().jobs.run_now(
        job_id=repair_job_id,
        job_parameters={
            "group_path": str(group_path),
            "repair_series_id": repair_series_id,
            "attempt": str(attempt + 1),
            "max_attempts": str(max_attempts),
            "requested_by": requested_by,
        },
    )
    next_run_id = response.response.run_id if response.response else None

summary = {
    "schema_version": "1.0",
    "workflow_run_id": manifest["workflow_run_id"],
    "group_id": manifest["group_id"],
    "repair_series_id": repair_series_id,
    "attempt": attempt,
    "max_attempts": max_attempts,
    "status": status,
    "readiness": evaluation["readiness"],
    "coverage_before": initial_evaluation["coverage"],
    "coverage_after": evaluation["coverage"],
    "gates_before": initial_evaluation["gates"],
    "gates_after": evaluation["gates"],
    "policy": evaluation["policy"],
    "candidate_changed": changed,
    "candidate_hash_before": before_hash,
    "candidate_hash_after": candidate_hash,
    "failure_signature": evaluation["failure_signature"],
    "regressions": regressions,
    "rolled_back": rolled_back,
    "rollback_reason": rollback_reason,
    "progress": progress,
    "next_run_id": next_run_id,
    "attempt_dir": str(attempt_dir),
}
write_json_artifact(summary, attempt_dir / "summary.json")
write_json_artifact(summary, group_internal_path / "repair" / "latest.json")
if changed and not rolled_back:
    (group_path / "metric-view.yaml").write_text(
        yaml.safe_dump(candidate, sort_keys=False, width=120), encoding="utf-8"
    )

evaluation_path = group_internal_path / "evaluation.json"
group_evaluation = json.loads(evaluation_path.read_text(encoding="utf-8")) if evaluation_path.is_file() else {}
group_evaluation["repair"] = summary
group_evaluation["status"] = "PASS_SEMANTIC_ONLY" if status == "READY" else "PARTIAL"
write_json_artifact(group_evaluation, evaluation_path)
final_result_path = group_internal_path / "final-result.json"
final_result = json.loads(final_result_path.read_text(encoding="utf-8")) if final_result_path.is_file() else {}
final_result.update(
    {
        "status": "PASS_SEMANTIC_ONLY" if status == "READY" else "PARTIAL",
        "repair_status": status,
        "repair_summary_path": str(attempt_dir / "summary.json"),
    }
)
write_json_artifact(final_result, final_result_path)

run_root = group_path.parents[1]
report_path = Path(manifest.get("report_path") or run_root / "reports" / "groups" / manifest["group_id"])
group_info = {
    "group_id": manifest["group_id"],
    "display_name": manifest.get("display_name") or manifest.get("group_name"),
    "group_path": str(group_path),
    "internal_path": str(group_internal_path),
    "report_path": str(report_path),
    "source_summary_path": str(group_internal_path / "source-summary.json"),
}
group_mapping_path = group_path / "mapping.yaml"
group_review = build_group_review(
    group=group_info,
    final_result=final_result,
    evaluation=group_evaluation,
    # metric-view.yaml was rewritten above when the candidate changed, so it is the deployed definition.
    metric_view=yaml.safe_load((group_path / "metric-view.yaml").read_text(encoding="utf-8")),
    scorecard_evaluation=evaluation,
    group_mapping=yaml.safe_load(group_mapping_path.read_text(encoding="utf-8")) if group_mapping_path.is_file() else None,
)
write_json_artifact(group_review, report_path / "migration-review.json")
(report_path / "migration-review.html").write_text(
    render_workflow_html({"workspace_url": WORKSPACE_URL, **build_workflow_review(workflow_run_id=manifest["workflow_run_id"], groups=[group_review])}),
    encoding="utf-8",
)
repair_review = build_repair_review(summary=summary, evaluation=evaluation)
write_json_artifact(repair_review, report_path / "repair-review.json")
(report_path / "repair-review.html").write_text(render_repair_html(repair_review), encoding="utf-8")

reports_root = run_root / "reports"
available_group_reviews = []
for review_path in sorted((reports_root / "groups").glob("*/migration-review.json")):
    available_group_reviews.append(json.loads(review_path.read_text(encoding="utf-8")))
workflow_review = build_workflow_review(
    workflow_run_id=manifest["workflow_run_id"],
    groups=available_group_reviews or [group_review],
)
write_json_artifact(workflow_review, reports_root / "index.json")
(reports_root / "index.html").write_text(render_workflow_html({"workspace_url": WORKSPACE_URL, **workflow_review}), encoding="utf-8")
print("\n=== Deploy, Retest, Finalize ===")
print(format_notebook_result(summary))
displayHTML(render_volume_links_html(summary))
dbutils.notebook.exit(format_notebook_result(summary))
