# Databricks notebook source
import json
from datetime import datetime, timezone
from pathlib import Path

from datasource_semantic_migration.notebook_results import (
    format_notebook_result,
    render_volume_links_html,
    summarize_semantic_groups,
)
from datasource_semantic_migration.proposal_handoff import resolve_proposal
from datasource_semantic_migration.tableau_parser import write_json_artifact


for widget_name in (
    "proposal_run_id",
    "output_volume_path",
    "migration_run_id",
    "migration_job_id",
    "approved_by",
    "force_rerun",
):
    dbutils.widgets.text(widget_name, "")

output_volume_path = Path(dbutils.widgets.get("output_volume_path").rstrip("/"))
if not output_volume_path.as_posix().startswith("/Volumes/"):
    raise ValueError("output_volume_path must be a Unity Catalog Volume path")
force_rerun = dbutils.widgets.get("force_rerun").strip().lower() in {"true", "1", "yes"}
resolved = resolve_proposal(
    output_volume_path,
    dbutils.widgets.get("proposal_run_id"),
    force_rerun=force_rerun,
    migration_job_id=dbutils.widgets.get("migration_job_id").strip() or None,
)
proposal = resolved.candidate
groups_index_path = proposal.groups_index_path
print(
    f"Migrating proposal {proposal.run_folder} "
    f"({'chosen by proposal_run_id' if resolved.resolution == 'explicit' else 'the only proposal awaiting approval'}"
    f"{'; force_rerun' if resolved.forced else ''})."
)
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


def triggering_user() -> str | None:
    """The user who started this migration run; current_user() is the Job's run-as identity."""
    try:
        from databricks.sdk import WorkspaceClient

        return WorkspaceClient().jobs.get_run(int(dbutils.widgets.get("migration_run_id"))).creator_user_name
    except Exception as error:  # attribution must never block approval
        print(f"Could not read the triggering user from the Jobs API: {error}")
        return None


approved_by = (
    dbutils.widgets.get("approved_by").strip()
    or triggering_user()
    or spark.sql("SELECT current_user()").first()[0]
)
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
approval["proposal_run_folder"] = proposal.run_folder
approval["resolution"] = resolved.resolution
approval["force_rerun"] = resolved.forced
approval_path = write_json_artifact(approval, Path(manifest["runtime"]["reports_path"]) / "grouping-approval.json")
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
    "proposal_run_folder": proposal.run_folder,
    "resolution": resolved.resolution,
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
