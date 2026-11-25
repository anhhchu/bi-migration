# Databricks notebook source
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from datasource_semantic_migration.notebook_results import format_notebook_result, render_volume_links_html
from datasource_semantic_migration.reporting import build_group_review, build_workflow_review, render_workflow_html
from datasource_semantic_migration.artifacts import write_json_artifact

# Used for Catalog Explorer links in the HTML reports.
WORKSPACE_URL = "https://" + spark.conf.get("spark.databricks.workspaceUrl").removeprefix("https://").rstrip("/")


for widget_name in ("manifest_path", "groups_index_path"):
    dbutils.widgets.text(widget_name, "")

manifest_path = Path(dbutils.widgets.get("manifest_path"))
groups_index_path = Path(dbutils.widgets.get("groups_index_path"))
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
groups_index = json.loads(groups_index_path.read_text(encoding="utf-8"))
group_reviews = []
for group in groups_index["groups"]:
    group_path = Path(group["group_path"])
    group_internal_path = Path(group.get("internal_path") or group_path / "_internal")
    group_report_path = Path(group.get("report_path") or Path(manifest["runtime"]["reports_path"]) / "groups" / group["group_id"])
    final_result_path = group_internal_path / "final-result.json"
    evaluation_path = group_internal_path / "evaluation.json"
    if final_result_path.is_file():
        final_result = json.loads(final_result_path.read_text(encoding="utf-8"))
    else:
        final_result = {
            "group_id": group["group_id"],
            "status": "FAILED",
            "metric_view_fqn": None,
            "evaluation_path": str(evaluation_path),
        }
    if evaluation_path.is_file():
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    else:
        evaluation = {
            "agent_result": None,
            "findings": [
                {
                    "code": "EVALUATION_MISSING",
                    "severity": "ERROR",
                    "message": "The semantic-group child Job did not produce an evaluation artifact.",
                }
            ],
        }
    metric_view_path = group_path / "metric-view.yaml"
    metric_view = yaml.safe_load(metric_view_path.read_text(encoding="utf-8")) if metric_view_path.is_file() else None
    group_mapping_path = group_path / "mapping.yaml"
    group_mapping = yaml.safe_load(group_mapping_path.read_text(encoding="utf-8")) if group_mapping_path.is_file() else None
    # Latest per-measure scorecards from repair, if repair ran.
    scorecard_evaluation = None
    repair_attempt_dir = (evaluation.get("repair") or {}).get("attempt_dir")
    if repair_attempt_dir and (Path(repair_attempt_dir) / "evaluation-after.json").is_file():
        scorecard_evaluation = json.loads((Path(repair_attempt_dir) / "evaluation-after.json").read_text(encoding="utf-8"))
    review = build_group_review(
        group=group,
        final_result=final_result,
        evaluation=evaluation,
        metric_view=metric_view or None,
        scorecard_evaluation=scorecard_evaluation,
        group_mapping=group_mapping or None,
    )
    group_reviews.append(review)
    write_json_artifact(review, group_report_path / "migration-review.json")
    (group_report_path / "migration-review.html").write_text(
        render_workflow_html({"workspace_url": WORKSPACE_URL, **build_workflow_review(workflow_run_id=manifest["workflow_run_id"], groups=[review])}),
        encoding="utf-8",
    )

summary = build_workflow_review(workflow_run_id=manifest["workflow_run_id"], groups=group_reviews)
reports_path = Path(manifest["runtime"]["reports_path"])
summary_path = write_json_artifact(summary, reports_path / "index.json")
html_path = reports_path / "index.html"
html_path.write_text(render_workflow_html({"workspace_url": WORKSPACE_URL, **summary}), encoding="utf-8")
manifest["status"] = summary["status"]
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

runs_root = Path(manifest["runtime"]["run_root"]).parent
cutoff = datetime.now(timezone.utc) - timedelta(days=manifest["deployment"]["retention_days"])
for run_path in runs_root.iterdir():
    if run_path == Path(manifest["runtime"]["run_root"]) or not run_path.is_dir():
        continue
    modified = datetime.fromtimestamp(run_path.stat().st_mtime, tz=timezone.utc)
    if modified < cutoff:
        shutil.rmtree(run_path)

result = {
    "status": summary["status"],
    "headline": summary["headline"],
    "totals": summary["totals"],
    "next_actions": [
        {
            "group_id": action["group_id"],
            "priority": action["priority"],
            "title": action["title"],
            "items": action["items"],
        }
        for action in summary["recommended_actions"]
    ],
    "workflow_summary_path": str(summary_path),
    "workflow_summary_html_path": str(html_path),
}
print("\n=== Finalize Workflow ===")
print(format_notebook_result(result))
displayHTML(render_volume_links_html(result))
dbutils.notebook.exit(format_notebook_result(result))
