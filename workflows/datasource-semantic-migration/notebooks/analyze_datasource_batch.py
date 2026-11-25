# Databricks notebook source
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from datasource_semantic_migration.sources.tableau.metric_compiler import write_metric_ir_for_datasource_entry
from datasource_semantic_migration.notebook_results import format_notebook_result, render_volume_links_html
from datasource_semantic_migration.sources.tableau.parser import write_asset_ir_result


for widget_name in ("inventory_path", "asset_indexes", "analysis_batch_workers"):
    dbutils.widgets.text(widget_name, "")

inventory_path = Path(dbutils.widgets.get("inventory_path"))
inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
asset_indexes = json.loads(dbutils.widgets.get("asset_indexes"))
if not isinstance(asset_indexes, list) or not asset_indexes:
    raise ValueError("asset_indexes must be a non-empty JSON array")
if any(not isinstance(index, int) for index in asset_indexes):
    raise ValueError("asset_indexes must contain integers")
internal_root = inventory_path.parent.parent


def analyze_asset(asset_index):
    parse_result = write_asset_ir_result(
        inventory=inventory,
        asset_index=asset_index,
        ir_root=internal_root / "ir",
    )
    metric_results = [
        write_metric_ir_for_datasource_entry(
            datasource_entry=datasource,
            metric_ir_root=internal_root / "metric-ir",
        )
        for datasource in parse_result["datasources"]
    ]
    return {
        "asset_index": asset_index,
        "asset_id": parse_result["asset_id"],
        "source_path": parse_result["source_path"],
        "datasource_count": len(parse_result["datasources"]),
        "dimension_count": sum(item["dimension_count"] for item in metric_results),
        "measure_count": sum(item["measure_count"] for item in metric_results),
        "finding_count": sum(item["finding_count"] for item in metric_results),
    }


configured_workers = int(dbutils.widgets.get("analysis_batch_workers"))
worker_count = min(configured_workers, len(asset_indexes))
with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="datasource-analysis") as executor:
    files = sorted(executor.map(analyze_asset, asset_indexes), key=lambda item: item["asset_index"])

result = {
    "batch_size": len(files),
    "worker_count": worker_count,
    "files": files,
    "totals": {
        "datasource_count": sum(item["datasource_count"] for item in files),
        "dimension_count": sum(item["dimension_count"] for item in files),
        "measure_count": sum(item["measure_count"] for item in files),
        "finding_count": sum(item["finding_count"] for item in files),
    },
}
print("\n=== Analyze Datasource Batch ===")
print(format_notebook_result(result))
displayHTML(render_volume_links_html(result))
dbutils.notebook.exit(format_notebook_result(result))
