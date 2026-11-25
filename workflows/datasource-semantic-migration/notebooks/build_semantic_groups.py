# Databricks notebook source
import json
from pathlib import Path

from datasource_semantic_migration.notebook_results import (
    format_notebook_result,
    render_volume_links_html,
    summarize_semantic_groups,
)
import yaml

from datasource_semantic_migration.semantic_groups import build_semantic_groups
from datasource_semantic_migration.table_mapping import load_table_mapping
from datasource_semantic_migration.artifacts import write_json_artifact


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
mapping_files = [item["path"] for item in inventory["mapping_files"]]
if not mapping_files:
    raise ValueError("No table mapping found. Add a YAML, JSON, or CSV file to the input folder's mappings/ directory.")
# Merge every mapping file into one normalized document that Genie and later steps read.
mapping_path = internal_root / "table-mapping.normalized.yaml"
mapping_path.write_text(yaml.safe_dump(load_table_mapping(mapping_files), sort_keys=False), encoding="utf-8")
mapping_path = mapping_path.as_posix()
groups_index = build_semantic_groups(
    inventory=inventory,
    datasource_ir_index=datasource_ir_index,
    metric_ir_index=metric_ir_index,
    mapping_path=mapping_path,
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
