# Databricks notebook source
import json
from datetime import datetime, timezone
from pathlib import Path

from datasource_semantic_migration.notebook_results import (
    format_notebook_result,
    render_volume_links_html,
    summarize_semantic_groups,
)
from datasource_semantic_migration.reporting import build_grouping_review, render_grouping_review_html
from datasource_semantic_migration.tableau_parser import write_json_artifact


for widget_name in ("manifest_path", "groups_index_path", "migration_job_id"):
    dbutils.widgets.text(widget_name, "")

manifest_path = Path(dbutils.widgets.get("manifest_path"))
groups_index_path = Path(dbutils.widgets.get("groups_index_path"))
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
groups_index = json.loads(groups_index_path.read_text(encoding="utf-8"))
group_summaries = summarize_semantic_groups(groups_index)
migration_job_id = dbutils.widgets.get("migration_job_id")
workspace_host = spark.conf.get("spark.databricks.workspaceUrl").removeprefix("https://").rstrip("/")
migration_job_url = f"https://{workspace_host}/jobs/{migration_job_id}"
review = build_grouping_review(
    workflow_run_id=manifest["workflow_run_id"],
    groups_index_path=groups_index_path.as_posix(),
    grouping_proposal_path=groups_index["grouping_proposal_path"],
    groups=group_summaries,
    excluded_helpers=groups_index.get("ungrouped_datasources", []),
    migration_job_id=migration_job_id,
    migration_job_url=migration_job_url,
)
reports_path = Path(manifest["runtime"]["reports_path"])
review_path = write_json_artifact(review, reports_path / "semantic-grouping-review.json")
review_html_path = reports_path / "semantic-grouping-review.html"
review_html_path.write_text(render_grouping_review_html(review), encoding="utf-8")
output_volume_path = Path(manifest["runtime"]["run_root"]).parents[1]
pending_proposal_path = output_volume_path / "_control" / "latest-pending-proposal.json"
pending_proposal = {
    "schema_version": "1.0",
    "status": "PENDING_APPROVAL",
    "workflow_run_id": manifest["workflow_run_id"],
    "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "groups_index_path": groups_index_path.as_posix(),
    "grouping_review_path": review_path.as_posix(),
    "grouping_review_html_path": review_html_path.as_posix(),
    "semantic_groups": [group["group_name"] for group in group_summaries],
}
write_json_artifact(pending_proposal, pending_proposal_path)
manifest["status"] = "GROUPING_REVIEW_REQUIRED"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

result = {
    "status": review["status"],
    "semantic_group_count": len(group_summaries),
    "semantic_groups": group_summaries,
    "groups_index_path": groups_index_path.as_posix(),
    "grouping_review_path": review_path.as_posix(),
    "grouping_review_html_path": review_html_path.as_posix(),
    "next_step": review["next_step"],
    "migration_job_id": review["migration_job_id"],
    "migration_job_url": migration_job_url,
    "migration_handoff": "The migration Job will resolve this proposal automatically.",
}
print("\n=== Finalize Semantic Grouping ===")
print(f"Open migration Job: {migration_job_url}")
print(format_notebook_result(result))
displayHTML(render_grouping_review_html(review))
displayHTML(render_volume_links_html(result))
dbutils.notebook.exit(format_notebook_result(result))
