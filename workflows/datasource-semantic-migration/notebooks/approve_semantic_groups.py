# Databricks notebook source
import json
from datetime import datetime, timezone
from pathlib import Path

from datasource_semantic_migration.notebook_results import (
    format_notebook_result,
    render_volume_links_html,
    summarize_semantic_groups,
)
from datasource_semantic_migration.tableau_parser import write_json_artifact


for widget_name in ("proposal_run_id", "output_volume_path", "migration_run_id", "approved_by"):
    dbutils.widgets.text(widget_name, "")

output_volume_path = Path(dbutils.widgets.get("output_volume_path").rstrip("/"))
if not output_volume_path.as_posix().startswith("/Volumes/"):
    raise ValueError("output_volume_path must be a Unity Catalog Volume path")
proposal_run_id = dbutils.widgets.get("proposal_run_id").strip()
pending_proposal_path = output_volume_path / "_control" / "latest-pending-proposal.json"
pending_proposal = None
if proposal_run_id:
    groups_index_path = output_volume_path / "runs" / proposal_run_id / "_internal" / "semantic-groups-index.json"
else:
    if not pending_proposal_path.is_file():
        raise FileNotFoundError("No pending semantic-group proposal exists. Run Propose semantic groups first.")
    pending_proposal = json.loads(pending_proposal_path.read_text(encoding="utf-8"))
    if pending_proposal.get("status") != "PENDING_APPROVAL":
        raise ValueError(
            "The latest proposal has already started migration. Run a new proposal or provide proposal_run_id."
        )
    groups_index_path = Path(pending_proposal["groups_index_path"])
groups_index = json.loads(groups_index_path.read_text(encoding="utf-8"))
if groups_index.get("status") != "COMPLETE" or not groups_index.get("groups"):
    raise ValueError("Semantic groups index is incomplete or contains no groups")
blocked = [group["group_id"] for group in groups_index["groups"] if group["status"] != "READY_FOR_PREFLIGHT"]
if blocked:
    raise ValueError(f"Semantic groups are not ready for migration: {blocked}")

run_root = groups_index_path.parent.parent
manifest_path = run_root / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest["workflow_run_id"] != groups_index["workflow_run_id"]:
    raise ValueError("Manifest and semantic groups index belong to different workflow runs")
approved_by = dbutils.widgets.get("approved_by").strip() or spark.sql("SELECT current_user()").first()[0]
group_selectors = [
    f"{index}|{group['display_name']}"
    for index, group in enumerate(groups_index["groups"])
    if group["status"] == "READY_FOR_PREFLIGHT"
]
approval = {
    "schema_version": "1.0",
    "workflow_run_id": groups_index["workflow_run_id"],
    "migration_run_id": dbutils.widgets.get("migration_run_id"),
    "approved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "approved_by": approved_by,
    "groups_index_path": groups_index_path.as_posix(),
    "approved_groups": [group["display_name"] for group in groups_index["groups"]],
}
approval_path = write_json_artifact(approval, Path(manifest["runtime"]["reports_path"]) / "grouping-approval.json")
if pending_proposal and pending_proposal.get("groups_index_path") == groups_index_path.as_posix():
    pending_proposal.update(
        {
            "status": "MIGRATION_STARTED",
            "migration_run_id": dbutils.widgets.get("migration_run_id"),
            "approved_at": approval["approved_at"],
            "approved_by": approved_by,
        }
    )
    write_json_artifact(pending_proposal, pending_proposal_path)
manifest["status"] = "MIGRATION_RUNNING"
manifest["grouping_approval_path"] = approval_path.as_posix()
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

for key, value in {
    "manifest_path": manifest_path.as_posix(),
    "groups_index_path": groups_index_path.as_posix(),
    "group_selectors": group_selectors,
}.items():
    dbutils.jobs.taskValues.set(key=key, value=value)
result = {
    "status": "APPROVED_FOR_MIGRATION",
    "approved_by": approved_by,
    "approval_path": approval_path.as_posix(),
    "groups_index_path": groups_index_path.as_posix(),
    "migration_iterations": len(group_selectors),
    "semantic_groups": summarize_semantic_groups(groups_index),
}
print("\n=== Approve Semantic Groups ===")
print(format_notebook_result(result))
displayHTML(render_volume_links_html(result))
dbutils.notebook.exit(format_notebook_result(result))
