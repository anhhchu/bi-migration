from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from datasource_semantic_migration.artifacts import sha256_file
from datasource_semantic_migration.semantic_groups import build_grouping_request
from datasource_semantic_migration.sources.tableau.extract_origin import extract_origin
from datasource_semantic_migration.sources.tableau.metric_compiler import compile_metric_ir
from datasource_semantic_migration.sources.tableau.parser import parse_tableau_datasource
from datasource_semantic_migration.table_mapping import TableMappingError

SAMPLES = Path(__file__).resolve().parents[1] / "datasource-samples"


def _extract_is_source(name: str, hyper: str) -> str:
    """A published Alteryx-style datasource: its only connection is the .hyper itself."""
    return f"""<?xml version='1.0' encoding='utf-8'?>
<datasource caption='{name}' inline='true' version='18.1'>
  <connection class='federated'>
    <named-connections>
      <named-connection caption='{name}' name='hyper.{name}'>
        <connection class='hyper' dbname='Data/{hyper}' schema='Extract' tablename='Extract'/>
      </named-connection>
    </named-connections>
    <relation connection='hyper.{name}' name='Extract' table='[Extract].[Extract]' type='table'/>
  </connection>
  <column datatype='real' name='[Amount]' role='measure' type='quantitative'/>
</datasource>
"""


TABLEAU_EXTRACT = """<?xml version='1.0' encoding='utf-8'?>
<datasource caption='Finance' inline='true' version='18.1'>
  <connection class='federated'>
    <named-connections>
      <named-connection caption='Finance Data' name='textscan.finance'>
        <connection class='textscan' directory='C:/Users/author/Data' filename='Finance Data.csv'/>
      </named-connection>
    </named-connections>
    <relation connection='textscan.finance' name='Finance Data.csv' table='[Finance Data#csv]' type='table'/>
  </connection>
  <extract enabled='true'>
    <connection class='hyper' dbname='Data/Finance data.hyper' schema='Extract' tablename='Extract'/>
  </extract>
  <column datatype='real' name='[Amount]' role='measure' type='quantitative'/>
</datasource>
"""


def _ir(tmp_path: Path, name: str, document: str) -> dict:
    path = tmp_path / f"{name}.tds"
    path.write_text(document, encoding="utf-8")
    return parse_tableau_datasource(
        tds_path=path, source_path=f"/Volumes/main/bi/in/datasources/{name}.tdsx", document_path=path.name,
        workflow_run_id="run", package_hash=sha256_file(path), datasource_id=f"ds-{name}",
        created_at="2026-11-26T00:00:00Z", inventory_hash="0" * 64,
    )


def test_origin_tells_tableau_extracts_from_extracts_built_elsewhere_and_live_sources(tmp_path):
    tableau = extract_origin(_ir(tmp_path, "finance", TABLEAU_EXTRACT), ["Data/Finance data.hyper"])
    alteryx = extract_origin(_ir(tmp_path, "sales", _extract_is_source("Sales", "sales_output.hyper")), [])
    superstore = parse_tableau_datasource(
        tds_path=SAMPLES / "Superstore.tds", source_path="/Volumes/main/bi/in/datasources/Superstore.tds",
        document_path="Superstore.tds", workflow_run_id="run", package_hash="0" * 64, datasource_id="ds-s",
        created_at="2026-11-26T00:00:00Z", inventory_hash="0" * 64,
    )
    live = extract_origin(superstore, [])

    assert tableau["kind"] == "TABLEAU_EXTRACT"
    assert tableau["label"] == "Tableau extract of text file Finance Data.csv; extract included"
    assert alteryx["kind"] == "EXTRACT_IS_SOURCE"
    assert alteryx["label"] == "Extract is the source (built outside Tableau); extract not in this upload, numbers can't be compared"
    assert live["kind"] == "LIVE"
    assert live["label"].startswith("Live connection to Excel file Sample - Superstore.xls")


def _request(tmp_path: Path, irs: list[dict], mapping: dict) -> dict:
    datasource_entries, metric_entries = [], []
    for ir in irs:
        ir_path = tmp_path / f"{ir['datasource_id']}.json"
        metric_path = tmp_path / f"{ir['datasource_id']}-metric.json"
        ir_path.write_text(json.dumps(ir), encoding="utf-8")
        metric_path.write_text(json.dumps(compile_metric_ir(ir)), encoding="utf-8")
        datasource_entries.append({"datasource_id": ir["datasource_id"], "output_path": ir_path.as_posix()})
        metric_entries.append({"datasource_id": ir["datasource_id"], "output_path": metric_path.as_posix()})
    mapping_path = tmp_path / "table-mapping.yaml"
    mapping_path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    return build_grouping_request(
        inventory={"workflow_run_id": "run", "assets": []},
        datasource_ir_index={"datasources": datasource_entries},
        metric_ir_index={"datasources": metric_entries},
        mapping_path=mapping_path,
        grouping_result_path=tmp_path / "proposal.json",
    )


def test_one_extract_row_for_different_extracts_stops_with_a_clear_message(tmp_path):
    irs = [
        _ir(tmp_path, "sales", _extract_is_source("Sales", "sales_output.hyper")),
        _ir(tmp_path, "returns", _extract_is_source("Returns", "returns_output.hyper")),
    ]
    mapping = {"table_mappings": [{"source": {"table": "Extract"}, "target": {"table": "main.sales.sales_output"}}]}

    with pytest.raises(TableMappingError, match="Ambiguous table mapping: source table 'Extract'.*Returns, Sales"):
        _request(tmp_path, irs, mapping)


def test_rows_qualified_by_datasource_map_each_extract_to_its_own_table(tmp_path):
    irs = [
        _ir(tmp_path, "sales", _extract_is_source("Sales", "sales_output.hyper")),
        _ir(tmp_path, "returns", _extract_is_source("Returns", "returns_output.hyper")),
    ]
    mapping = {
        "table_mappings": [
            {"source": {"table": "Extract", "datasource": "Sales"}, "target": {"table": "main.sales.sales_output"}},
            {"source": {"table": "Extract", "datasource": "Returns"}, "target": {"table": "main.sales.returns_output"}},
        ]
    }

    request = _request(tmp_path, irs, mapping)

    targets = {item["datasource_name"]: item["target_tables"] for item in request["datasources"]}
    assert targets == {"Sales": ["main.sales.sales_output"], "Returns": ["main.sales.returns_output"]}
    assert {item["extract_origin"]["kind"] for item in request["datasources"]} == {"EXTRACT_IS_SOURCE"}


def test_datasources_reading_the_same_file_may_share_a_row(tmp_path):
    # The same Excel file opened by two authors: different local paths, same file and table.
    document = (SAMPLES / "Superstore.tds").read_text(encoding="utf-8")
    first = _ir(tmp_path, "first", document)
    original_file = next(item["attributes"]["filename"] for item in first["connections"] if item["attributes"].get("filename"))
    other_directory = "C:/Users/someone/Documents/" + original_file.replace("\\", "/").rsplit("/", 1)[-1]
    second = _ir(tmp_path, "second", document.replace(original_file, other_directory))
    assert second["connections"][0]["attributes"]["filename"] != original_file
    mapping = {"table_mappings": [{"source": {"table": "Orders"}, "target": {"table": "main.superstore.orders"}}]}

    request = _request(tmp_path, [first, second], mapping)

    assert all(item["target_tables"] == ["main.superstore.orders"] for item in request["datasources"])


def test_different_copies_of_a_regular_table_may_share_a_row(tmp_path):
    # An Excel and a CSV copy of Orders mapped to one table is a deliberate choice, not an ambiguity.
    excel = _ir(tmp_path, "excel", TABLEAU_EXTRACT.replace("Finance Data.csv", "Orders.xls").replace("Finance Data#csv", "Orders"))
    csv = _ir(tmp_path, "csv", TABLEAU_EXTRACT.replace("Finance Data.csv", "Orders.csv").replace("Finance Data#csv", "Orders"))
    mapping = {"table_mappings": [{"source": {"table": "Orders"}, "target": {"table": "main.sales.orders"}}]}

    request = _request(tmp_path, [excel, csv], mapping)

    assert all(item["target_tables"] == ["main.sales.orders"] for item in request["datasources"])
