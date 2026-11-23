# Databricks notebook source
import json
from pathlib import Path

from datasource_semantic_migration.notebook_results import (
    format_notebook_result,
    render_volume_links_html,
    summarize_semantic_groups,
)
from datasource_semantic_migration.semantic_groups import build_semantic_groups
from datasource_semantic_migration.tableau_parser import write_json_artifact


for widget_name in (
    "manifest_path",
    "inventory_path",
    "datasource_ir_index_path",
    "metric_ir_index_path",
    "grouping_proposal_path",
    "candidate_catalog",
    "candidate_schema",
):
    dbutils.widgets.text(widget_name, "")

manifest_path = Path(dbutils.widgets.get("manifest_path"))
inventory_path = Path(dbutils.widgets.get("inventory_path"))
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
internal_root = inventory_path.parent.parent
datasource_ir_index_path = Path(dbutils.widgets.get("datasource_ir_index_path"))
metric_ir_index_path = Path(dbutils.widgets.get("metric_ir_index_path"))
grouping_proposal_path = Path(dbutils.widgets.get("grouping_proposal_path"))
datasource_ir_index = json.loads(datasource_ir_index_path.read_text(encoding="utf-8"))
metric_ir_index = json.loads(metric_ir_index_path.read_text(encoding="utf-8"))
if len(inventory["mapping_files"]) != 1:
    raise ValueError("End-to-end migration requires exactly one table-mapping.yaml")
groups_index = build_semantic_groups(
    inventory=inventory,
    datasource_ir_index=datasource_ir_index,
    metric_ir_index=metric_ir_index,
    mapping_path=inventory["mapping_files"][0]["path"],
    grouping_proposal_path=grouping_proposal_path,
    run_root=manifest["runtime"]["run_root"],
    candidate_catalog=dbutils.widgets.get("candidate_catalog"),
    candidate_schema=dbutils.widgets.get("candidate_schema"),
)
groups_index_path = write_json_artifact(groups_index, internal_root / "semantic-groups-index.json")
dbutils.jobs.taskValues.set(key="groups_index_path", value=str(groups_index_path))
result = {
    "datasource_ir_index_path": str(datasource_ir_index_path),
    "metric_ir_index_path": str(metric_ir_index_path),
    "groups_index_path": str(groups_index_path),
    "proposed_group_count": groups_index["summary"]["semantic_group_count"],
    "semantic_groups": summarize_semantic_groups(groups_index),
    "summary": groups_index["summary"],
}
print("\n=== Build Semantic Groups ===")
print(format_notebook_result(result))
displayHTML(render_volume_links_html(result))
dbutils.notebook.exit(format_notebook_result(result))
