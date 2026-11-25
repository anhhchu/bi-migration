# Databricks notebook source
import json
from pathlib import Path

from datasource_semantic_migration.analysis_batches import build_analysis_batches
from datasource_semantic_migration.config import WorkflowConfig
from datasource_semantic_migration.sources.tableau.discovery import discover_inputs, write_inventory
from datasource_semantic_migration.manifest import build_workflow_manifest
from datasource_semantic_migration.notebook_results import format_notebook_result, render_volume_links_html


for widget_name in (
    "input_volume_path",
    "workflow_run_id",
    "job_run_id",
    "job_start_time",
    "output_volume_path",
    "candidate_catalog",
    "candidate_schema",
    "staging_schema",
    "warehouse_id",
    "analysis_batch_size",
    "analysis_batch_workers",
):
    dbutils.widgets.text(widget_name, "")

config = WorkflowConfig.from_dict(
    {
        "output_volume_path": dbutils.widgets.get("output_volume_path"),
        "candidate_catalog": dbutils.widgets.get("candidate_catalog"),
        "candidate_schema": dbutils.widgets.get("candidate_schema"),
        "staging_schema": dbutils.widgets.get("staging_schema"),
        "warehouse_id": dbutils.widgets.get("warehouse_id"),
        "analysis_batch_size": dbutils.widgets.get("analysis_batch_size"),
        "analysis_batch_workers": dbutils.widgets.get("analysis_batch_workers"),
    }
)
manifest = build_workflow_manifest(
    workflow_run_id=dbutils.widgets.get("workflow_run_id"),
    job_run_id=dbutils.widgets.get("job_run_id"),
    input_volume_path=dbutils.widgets.get("input_volume_path"),
    config=config,
    created_at=dbutils.widgets.get("job_start_time").strip() or None,
)
manifest_path = Path(manifest["runtime"]["run_root"]) / "manifest.json"
manifest_path.parent.mkdir(parents=True, exist_ok=True)
inventory = discover_inputs(
    datasources_path=manifest["input"]["datasources_path"],
    mappings_path=manifest["input"]["mappings_path"],
    extraction_root=Path(manifest["runtime"]["internal_path"]) / "extracted",
    workflow_run_id=manifest["workflow_run_id"],
)
inventory_path = write_inventory(
    inventory,
    Path(manifest["runtime"]["internal_path"]) / "inventory" / "input-inventory.json",
)
manifest["status"] = "RUNNING"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
analysis_batches = build_analysis_batches(inventory, config.analysis_batch_size)

dbutils.jobs.taskValues.set(key="manifest_path", value=str(manifest_path))
dbutils.jobs.taskValues.set(key="inventory_path", value=str(inventory_path))
dbutils.jobs.taskValues.set(key="analysis_batches", value=analysis_batches)
result = {
    "manifest_path": str(manifest_path),
    "inventory_path": str(inventory_path),
    "analysis_batch_count": len(analysis_batches),
    "analysis_file_count": inventory["summary"]["unique_count"],
    "analysis_batch_size": config.analysis_batch_size,
    "summary": inventory["summary"],
}
print("\n=== Inventory Inputs ===")
print(format_notebook_result(result))
displayHTML(render_volume_links_html(result))
dbutils.notebook.exit(format_notebook_result(result))
