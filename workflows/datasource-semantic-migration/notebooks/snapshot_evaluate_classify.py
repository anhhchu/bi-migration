# Databricks notebook source
import json
from pathlib import Path

import yaml

from datasource_semantic_migration.metric_repair import evaluate_candidate
from datasource_semantic_migration.notebook_results import format_notebook_result, render_volume_links_html
from datasource_semantic_migration.artifacts import write_json_artifact


for widget_name in ("group_path", "repair_series_id", "attempt", "max_attempts", "job_run_id"):
    dbutils.widgets.text(widget_name, "")

group_path = Path(dbutils.widgets.get("group_path").rstrip("/"))
group_internal_path = group_path / "_internal"
if not (group_internal_path / "group-manifest.json").is_file():
    group_internal_path = group_path
attempt = int(dbutils.widgets.get("attempt") or "1")
max_attempts = int(dbutils.widgets.get("max_attempts") or "3")
repair_series_id = dbutils.widgets.get("repair_series_id").strip() or dbutils.widgets.get("job_run_id").strip()
attempt_dir = group_internal_path / "repair" / "runs" / repair_series_id / f"attempt-{attempt:02d}"
attempt_dir.mkdir(parents=True, exist_ok=True)

manifest = json.loads((group_internal_path / "group-manifest.json").read_text(encoding="utf-8"))
target_profile = json.loads((group_internal_path / "target-profile.json").read_text(encoding="utf-8"))
metric_view_path = group_path / "metric-view.yaml"
if not metric_view_path.is_file():
    raise FileNotFoundError(f"Candidate Metric View YAML is missing: {metric_view_path}")
metric_view = yaml.safe_load(metric_view_path.read_text(encoding="utf-8")) or {}
source_metric_irs = [
    json.loads(Path(datasource["metric_ir_path"]).read_text(encoding="utf-8"))
    for datasource in manifest["datasources"]
]

quoted_fqn = ".".join(f"`{part}`" for part in manifest["candidate_metric_view_fqn"].split("."))
query_results = {}
for measure in metric_view.get("measures", []):
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
    metric_view=metric_view,
    target_profile=target_profile,
    query_results=query_results,
)
evaluation.update(
    {
        "workflow_run_id": manifest["workflow_run_id"],
        "group_id": manifest["group_id"],
        "repair_series_id": repair_series_id,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "metric_view_fqn": manifest["candidate_metric_view_fqn"],
    }
)
(attempt_dir / "candidate-before.yaml").write_text(
    yaml.safe_dump(metric_view, sort_keys=False, width=120), encoding="utf-8"
)
write_json_artifact(
    {"schema_version": "1.0", "datasources": source_metric_irs},
    attempt_dir / "source-metric-ir.json",
)
write_json_artifact(
    {
        "schema_version": "1.0",
        "metric_view_fqn": manifest["candidate_metric_view_fqn"],
        "dimensions": metric_view.get("dimensions", []),
        "measures": metric_view.get("measures", []),
        "parameters": metric_view.get("parameters", []),
        "source": metric_view.get("source"),
    },
    attempt_dir / "target-metric-ir.json",
)
write_json_artifact(query_results, attempt_dir / "query-results-before.json")
write_json_artifact(evaluation["scorecards"], attempt_dir / "metric-scorecards.json")
write_json_artifact(evaluation, attempt_dir / "evaluation-summary.json")
write_json_artifact(
    {
        "readiness": evaluation["readiness"],
        "blocking_findings": evaluation["blocking_findings"],
        "relationship_blockers": evaluation["relationship_blockers"],
        "needs_genie": evaluation["needs_genie"],
        "failure_signature": evaluation["failure_signature"],
    },
    attempt_dir / "failure-classification.json",
)
for key, value in {
    "attempt_dir": str(attempt_dir),
    "repair_series_id": repair_series_id,
    "needs_genie": "true" if evaluation["needs_genie"] else "false",
    "readiness": evaluation["readiness"],
}.items():
    dbutils.jobs.taskValues.set(key=key, value=value)
result = {
    "repair_series_id": repair_series_id,
    "attempt": attempt,
    "readiness": evaluation["readiness"],
    "coverage": evaluation["coverage"],
    "blocking_findings": len(evaluation["blocking_findings"]),
    "needs_genie": evaluation["needs_genie"],
    "attempt_dir": str(attempt_dir),
}
print("\n=== Snapshot, Evaluate, Classify ===")
print(format_notebook_result(result))
displayHTML(render_volume_links_html(result))
dbutils.notebook.exit(format_notebook_result(result))
