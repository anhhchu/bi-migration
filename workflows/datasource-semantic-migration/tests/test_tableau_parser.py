from __future__ import annotations

import json
import shutil
from pathlib import Path

from datasource_semantic_migration.artifacts import sha256_file
from datasource_semantic_migration.sources.tableau.discovery import discover_inputs
from datasource_semantic_migration.ir_index import consolidate_datasource_ir_index
from datasource_semantic_migration.sources.tableau.parser import parse_tableau_datasource, write_asset_ir_result


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse(path: Path):
    content_hash = sha256_file(path)
    return parse_tableau_datasource(
        tds_path=path,
        source_path=f"/Volumes/main/bi_migration/tableau_datasources/datasources/{path.name}",
        document_path=path.name,
        workflow_run_id="run-123",
        package_hash=content_hash,
        datasource_id="datasource-123",
        created_at="2026-11-22T00:00:00Z",
        inventory_hash="0" * 64,
    )


def test_superstore_parser_preserves_datasource_semantics():
    ir = _parse(_root() / "datasource-samples" / "Superstore.tds")

    assert ir["datasource_name"] == "Sample - Superstore"
    assert ir["source_system"] == "tableau"
    assert ir["source_version"]
    assert len(ir["connections"]) == 2
    assert [relation["name"] for relation in ir["relations"]] == ["Orders", "People", "Returns"]
    assert len(ir["relationships"]) == 2
    assert len(ir["fields"]) == 26
    assert len(ir["calculations"]) == 10
    assert len(ir["parameters"]) == 2
    assert ir["warnings"] == []

    profit_ratio = next(item for item in ir["calculations"] if item["name"] == "Profit Ratio")
    assert profit_ratio["formula"] == "sum([Profit])/sum([Sales])"
    order_people = ir["relationships"][0]
    assert order_people["expression"]["children"] == [
        {"operator": "[Region]"},
        {"operator": "[Region (People)]"},
    ]


def test_parser_handles_physical_relation_without_object_graph():
    ir = _parse(_root() / "tests" / "fixtures" / "minimal" / "input" / "datasources" / "orders.tds")

    assert ir["datasource_name"] == "Orders"
    assert len(ir["relations"]) == 1
    assert ir["relations"][0]["table"] == "[LEGACY_DW].[SALES].[ORDERS]"
    assert [field["remote_name"] for field in ir["fields"]] == ["ORDER_ID", "SALES"]
    assert ir["calculations"][0]["name"] == "Profit Ratio"


def test_parser_preserves_join_tree(tmp_path):
    source = tmp_path / "joined.tds"
    source.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<datasource caption="Joined Orders">
  <connection class="snowflake">
    <relation type="join" join="left">
      <clause type="join"><expression op="="><expression op="[Orders].[Customer ID]"/><expression op="[Customers].[Customer ID]"/></expression></clause>
      <relation type="table" name="Orders" table="[ORDERS]"/>
      <relation type="table" name="Customers" table="[CUSTOMERS]"/>
    </relation>
  </connection>
</datasource>
""",
        encoding="utf-8",
    )

    ir = _parse(source)

    assert len(ir["relations"]) == 3
    assert ir["relations"][0]["relation_type"] == "join"
    assert ir["relations"][0]["join_type"] == "left"
    assert len(ir["relations"][0]["children"]) == 2
    assert ir["relations"][0]["clauses"][0]["expression"]["operator"] == "="


def test_asset_parse_and_index_are_deterministic(tmp_path):
    datasources = tmp_path / "datasources"
    datasources.mkdir()
    shutil.copy2(_root() / "datasource-samples" / "Superstore.tds", datasources / "Superstore.tds")
    inventory = discover_inputs(
        datasources_path=datasources,
        mappings_path=tmp_path / "mappings",
        extraction_root=tmp_path / "extracted",
        workflow_run_id="run-123",
        created_at="2026-11-22T00:00:00Z",
    )
    inventory["assets"][0]["source_path"] = (
        "/Volumes/main/bi_migration/tableau_datasources/datasources/Superstore.tds"
    )
    ir_root = tmp_path / "ir"

    first = write_asset_ir_result(inventory=inventory, asset_index=0, ir_root=ir_root)
    second = write_asset_ir_result(inventory=inventory, asset_index=0, ir_root=ir_root)
    assert first == second

    inventory_path = "/Volumes/main/bi_migration/semantic_workflows/runs/run-123/_internal/inventory/input-inventory.json"
    index = consolidate_datasource_ir_index(
        inventory=inventory,
        inventory_path=inventory_path,
        ir_root=ir_root,
    )
    assert index["summary"]["datasource_count"] == 1
    assert index["summary"]["relationship_count"] == 2
    assert json.loads(Path(index["datasources"][0]["output_path"]).read_text())["datasource_name"] == (
        "Sample - Superstore"
    )
