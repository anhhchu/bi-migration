# Databricks notebook source
import json
from pathlib import Path

from datasource_semantic_migration.metric_compiler import consolidate_metric_ir_index
from datasource_semantic_migration.notebook_results import format_notebook_result, render_volume_links_html
from datasource_semantic_migration.semantic_groups import build_grouping_request
from datasource_semantic_migration.tableau_parser import consolidate_datasource_ir_index, write_json_artifact


for widget_name in ("manifest_path", "inventory_path"):
    dbutils.widgets.text(widget_name, "")

manifest_path = Path(dbutils.widgets.get("manifest_path"))
inventory_path = Path(dbutils.widgets.get("inventory_path"))
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
internal_root = inventory_path.parent.parent
datasource_ir_index = consolidate_datasource_ir_index(
    inventory=inventory,
    inventory_path=inventory_path.as_posix(),
    ir_root=internal_root / "ir",
)
datasource_ir_index_path = write_json_artifact(
    datasource_ir_index,
    internal_root / "ir" / "datasource-ir-index.json",
)
metric_ir_index = consolidate_metric_ir_index(
    datasource_ir_index=datasource_ir_index,
    datasource_ir_index_path=datasource_ir_index_path.as_posix(),
    metric_ir_root=internal_root / "metric-ir",
)
metric_ir_index_path = write_json_artifact(
    metric_ir_index,
    internal_root / "metric-ir" / "metric-ir-index.json",
)
if len(inventory["mapping_files"]) != 1:
    raise ValueError("End-to-end migration requires exactly one table-mapping.yaml")
mapping_path = inventory["mapping_files"][0]["path"]
grouping_result_path = internal_root / "semantic-grouping-proposal.json"
grouping_request = build_grouping_request(
    inventory=inventory,
    datasource_ir_index=datasource_ir_index,
    metric_ir_index=metric_ir_index,
    mapping_path=mapping_path,
    grouping_result_path=grouping_result_path,
)
grouping_request_path = write_json_artifact(grouping_request, internal_root / "semantic-grouping-request.json")
dbutils.jobs.taskValues.set(key="datasource_ir_index_path", value=str(datasource_ir_index_path))
dbutils.jobs.taskValues.set(key="metric_ir_index_path", value=str(metric_ir_index_path))
dbutils.jobs.taskValues.set(key="grouping_request_path", value=str(grouping_request_path))
dbutils.jobs.taskValues.set(key="grouping_result_path", value=str(grouping_result_path))
result = {
    "datasource_count": len(grouping_request["datasources"]),
    "mapping_path": mapping_path,
    "grouping_request_path": str(grouping_request_path),
    "grouping_result_path": str(grouping_result_path),
}
print("\n=== Prepare Semantic Grouping ===")
print(format_notebook_result(result))
displayHTML(render_volume_links_html(result))
dbutils.notebook.exit(format_notebook_result(result))
