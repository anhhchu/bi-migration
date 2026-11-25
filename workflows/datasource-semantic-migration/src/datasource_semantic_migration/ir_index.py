"""Combine per-datasource parse and compile results into the IR indexes; shared by every source system."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import __version__


def consolidate_datasource_ir_index(
    *,
    inventory: dict[str, Any],
    inventory_path: str,
    ir_root: str | Path,
) -> dict[str, Any]:
    datasource_entries = []
    parse_results = []
    for asset in inventory["assets"]:
        if asset["duplicate_of"] is not None:
            continue
        result_path = Path(ir_root) / "assets" / asset["asset_id"] / "parse-result.json"
        if not result_path.is_file():
            raise FileNotFoundError(f"Datasource parse result does not exist: {result_path}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        parse_results.append(result_path.as_posix())
        datasource_entries.extend(result["datasources"])
    datasource_entries.sort(key=lambda item: (item["source_path"].casefold(), item["document_path"].casefold()))
    duplicates = [
        {
            "source_path": asset["source_path"],
            "relative_path": asset["relative_path"],
            "duplicate_of": asset["duplicate_of"],
        }
        for asset in inventory["assets"]
        if asset["duplicate_of"] is not None
    ]
    return {
        "schema_version": "1.0",
        "workflow_run_id": inventory["workflow_run_id"],
        "created_at": inventory["created_at"],
        "inventory_path": inventory_path,
        "inventory_hash": inventory["inventory_hash"],
        "ir_root": Path(ir_root).as_posix(),
        "status": "COMPLETE",
        "summary": {
            "package_count": inventory["summary"]["unique_count"],
            "datasource_count": len(datasource_entries),
            "duplicate_count": inventory["summary"]["duplicate_count"],
            "connection_count": sum(item["connection_count"] for item in datasource_entries),
            "relation_count": sum(item["relation_count"] for item in datasource_entries),
            "relationship_count": sum(item["relationship_count"] for item in datasource_entries),
            "field_count": sum(item["field_count"] for item in datasource_entries),
            "calculation_count": sum(item["calculation_count"] for item in datasource_entries),
            "parameter_count": sum(item["parameter_count"] for item in datasource_entries),
            "warning_count": sum(item["warning_count"] for item in datasource_entries),
        },
        "datasources": datasource_entries,
        "duplicates": duplicates,
        "parse_results": parse_results,
        "provenance": {
            "generator": {"name": "datasource-semantic-migration", "version": __version__}
        },
    }


def consolidate_metric_ir_index(
    *,
    datasource_ir_index: dict[str, Any],
    datasource_ir_index_path: str,
    metric_ir_root: str | Path,
) -> dict[str, Any]:
    entries = []
    compile_results = []
    for datasource in datasource_ir_index["datasources"]:
        result_path = Path(metric_ir_root) / "assets" / datasource["datasource_id"] / "compile-result.json"
        if not result_path.is_file():
            raise FileNotFoundError(f"Metric IR compile result does not exist: {result_path}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        entries.append(result)
        compile_results.append(result_path.as_posix())
    entries.sort(key=lambda item: (item["datasource_name"] or "").casefold())
    combined_status_counts: dict[str, int] = defaultdict(int)
    for entry in entries:
        for status, count in entry["status_counts"].items():
            combined_status_counts[status] += count
    return {
        "schema_version": "1.0",
        "workflow_run_id": datasource_ir_index["workflow_run_id"],
        "created_at": datasource_ir_index["created_at"],
        "datasource_ir_index_path": datasource_ir_index_path,
        "metric_ir_root": Path(metric_ir_root).as_posix(),
        "status": "COMPLETE",
        "summary": {
            "datasource_count": len(entries),
            "dimension_count": sum(item["dimension_count"] for item in entries),
            "measure_count": sum(item["measure_count"] for item in entries),
            "parameter_count": sum(item["parameter_count"] for item in entries),
            "finding_count": sum(item["finding_count"] for item in entries),
            "status_counts": dict(sorted(combined_status_counts.items())),
        },
        "datasources": entries,
        "compile_results": compile_results,
        "provenance": {
            "generator": {"name": "datasource-semantic-migration", "version": __version__}
        },
    }
