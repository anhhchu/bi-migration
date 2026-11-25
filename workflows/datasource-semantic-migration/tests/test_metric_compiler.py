from __future__ import annotations

import json
from pathlib import Path

from datasource_semantic_migration.artifacts import sha256_file
from datasource_semantic_migration.ir_index import consolidate_metric_ir_index
from datasource_semantic_migration.sources.tableau.metric_compiler import (
    compile_metric_ir,
    formula_references,
    write_metric_ir_result,
)
from datasource_semantic_migration.sources.tableau.parser import parse_tableau_datasource


def _superstore_datasource_ir():
    path = Path(__file__).resolve().parents[1] / "datasource-samples" / "Superstore.tds"
    content_hash = sha256_file(path)
    return parse_tableau_datasource(
        tds_path=path,
        source_path="/Volumes/main/bi_migration/tableau_datasources/datasources/Superstore.tds",
        document_path="Superstore.tds",
        workflow_run_id="run-123",
        package_hash=content_hash,
        datasource_id="datasource-123",
        created_at="2026-11-22T00:00:00Z",
        inventory_hash="0" * 64,
    )


def test_formula_references_ignore_literals_and_resolve_qualification():
    references = formula_references(
        'IF [Region] = "[Not A Field]" THEN [Parameters].[Region Parameter] END // [Ignored Comment]'
    )

    assert [(item.qualifier, item.field_name) for item in references] == [
        (None, "Region"),
        ("Parameters", "Region Parameter"),
    ]


def test_superstore_metric_ir_resolves_graph_and_semantic_gaps():
    metric_ir = compile_metric_ir(_superstore_datasource_ir())

    assert len(metric_ir["dimensions"]) == 24
    assert len(metric_ir["measures"]) == 12
    assert len(metric_ir["parameters"]) == 2
    assert metric_ir["calculation_graph"]["cyclic_nodes"] == []
    assert len(metric_ir["calculation_graph"]["edges"]) == 2

    profit_ratio = next(item for item in metric_ir["measures"] if item["display_name"] == "Profit Ratio")
    assert profit_ratio["aggregation"] == "FORMULA"
    assert profit_ratio["status"] == "READY"
    sales_forecast = next(item for item in metric_ir["measures"] if item["display_name"] == "Sales Forecast")
    assert {item["kind"] for item in sales_forecast["dependencies"]} == {"field", "parameter"}
    order_profitable = next(
        item for item in metric_ir["dimensions"] if item["display_name"] == "Order Profitable?"
    )
    assert order_profitable["expression"]["classification"]["semantic_type"] == "LOD_FIXED"
    assert any(item["code"] == "EXTERNAL_DATASOURCE_REFERENCE" for item in metric_ir["findings"])


def test_cycles_and_table_calculations_are_not_marked_ready():
    datasource_ir = {
        "schema_version": "1.0",
        "workflow_run_id": "run-123",
        "datasource_id": "datasource-123",
        "datasource_name": "Synthetic",
        "source_path": "/Volumes/main/bi_migration/tableau_datasources/datasources/synthetic.tds",
        "document_path": "synthetic.tds",
        "package_hash": "0" * 64,
        "relations": [{"name": "Orders"}],
        "fields": [
            {
                "field_id": "[Sales]",
                "name": "Sales",
                "datatype": "real",
                "default_aggregation": "Sum",
                "role": "measure",
                "relation_name": "Orders",
                "format": None,
            }
        ],
        "calculations": [
            {
                "calculation_id": "[A]",
                "name": "A",
                "formula": "[B] + 1",
                "role": "measure",
                "datatype": "real",
                "format": None,
            },
            {
                "calculation_id": "[B]",
                "name": "B",
                "formula": "[A] + 1",
                "role": "measure",
                "datatype": "real",
                "format": None,
            },
            {
                "calculation_id": "[Running Sales]",
                "name": "Running Sales",
                "formula": "WINDOW_SUM(SUM([Sales]))",
                "role": "measure",
                "datatype": "real",
                "format": None,
            },
        ],
        "parameters": [],
    }

    metric_ir = compile_metric_ir(datasource_ir)

    assert metric_ir["calculation_graph"]["cyclic_nodes"] == ["[A]", "[B]"]
    statuses = {item["display_name"]: item["status"] for item in metric_ir["measures"]}
    assert statuses["A"] == "BLOCKED_CYCLE"
    assert statuses["B"] == "BLOCKED_CYCLE"
    assert statuses["Running Sales"] == "UNSUPPORTED"


def test_metric_ir_artifacts_and_index_are_deterministic(tmp_path):
    datasource_ir = _superstore_datasource_ir()
    source_ir_path = tmp_path / "datasource-ir.json"
    source_ir_path.write_text(json.dumps(datasource_ir, indent=2, sort_keys=True), encoding="utf-8")
    datasource_ir_index = {
        "workflow_run_id": "run-123",
        "created_at": "2026-11-22T00:00:00Z",
        "datasources": [
            {
                "datasource_id": datasource_ir["datasource_id"],
                "output_path": source_ir_path.as_posix(),
            }
        ],
    }
    metric_ir_root = tmp_path / "metric-ir"

    first = write_metric_ir_result(
        datasource_ir_index=datasource_ir_index,
        datasource_index=0,
        metric_ir_root=metric_ir_root,
    )
    second = write_metric_ir_result(
        datasource_ir_index=datasource_ir_index,
        datasource_index=0,
        metric_ir_root=metric_ir_root,
    )
    assert first == second

    index = consolidate_metric_ir_index(
        datasource_ir_index=datasource_ir_index,
        datasource_ir_index_path=(
            "/Volumes/main/bi_migration/semantic_workflows/runs/run-123/_internal/ir/datasource-ir-index.json"
        ),
        metric_ir_root=metric_ir_root,
    )
    assert index["summary"]["datasource_count"] == 1
    assert index["summary"]["measure_count"] == 12
    assert index["summary"]["status_counts"]["READY"] > 0


def test_tableau_table_count_field_is_a_row_count():
    datasource_ir = {
        "workflow_run_id": "run", "datasource_id": "ds", "datasource_name": "Sales", "source_path": "/Volumes/a/b/c/d.tds",
        "document_path": "d.tds", "package_hash": "0" * 64, "parameters": [], "calculations": [], "relations": [], "relationships": [],
        "fields": [
            {"field_id": "[__tableau_internal_object_id__].[Orders_27BA4ABADA204F3DB93FDC2725F0E5E2]", "name": "Orders",
             "role": "measure", "datatype": "integer", "default_aggregation": "sum"},
            {"field_id": "[Sales]", "name": "Sales", "role": "measure", "datatype": "real", "default_aggregation": "sum"},
        ],
    }

    measures = {item["display_name"]: item["aggregation"] for item in compile_metric_ir(datasource_ir)["measures"]}

    assert measures == {"Orders": "ROW_COUNT", "Sales": "SUM"}
