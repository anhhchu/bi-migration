from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from datasource_semantic_migration.sources.tableau.discovery import DiscoveryLimits, UnsafeArchiveError, discover_inputs
from datasource_semantic_migration.sources.tableau.parser import parse_inventory_asset


def _sample_tds() -> Path:
    return Path(__file__).resolve().parents[1] / "datasource-samples" / "Superstore.tds"


def test_discovery_inventories_tds_tdsx_extract_and_duplicate(tmp_path):
    datasources = tmp_path / "datasources"
    mappings = tmp_path / "mappings"
    datasources.mkdir()
    mappings.mkdir()
    source_tds = _sample_tds()
    shutil.copy2(source_tds, datasources / "Superstore.tds")
    shutil.copy2(source_tds, datasources / "Superstore duplicate.tds")
    (mappings / "table-mapping.yaml").write_text("version: '1.0'\ntable_mappings: []\n", encoding="utf-8")

    with zipfile.ZipFile(datasources / "Packaged.tdsx", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source_tds, "Data/Superstore.tds")
        archive.writestr("Data/Extracts/Superstore.hyper", b"synthetic-hyper-fixture")

    inventory = discover_inputs(
        datasources_path=datasources,
        mappings_path=mappings,
        extraction_root=tmp_path / "extracted",
        workflow_run_id="run-123",
        created_at="2026-11-22T00:00:00Z",
    )

    assert inventory["summary"] == {
        "discovered_count": 3,
        "unique_count": 2,
        "duplicate_count": 1,
        "tds_count": 2,
        "tdsx_count": 1,
        "twb_count": 0,
        "twbx_count": 0,
        "datasource_document_count": 2,
        "embedded_extract_count": 1,
        "published_datasource_count": 0,
        "mapping_file_count": 1,
    }
    packaged = next(asset for asset in inventory["assets"] if asset["kind"] == "TDSX")
    assert packaged["tds_documents"][0]["connection_classes"] == ["excel-direct", "federated"]
    assert packaged["embedded_extracts"][0]["relative_path"] == "Data/Extracts/Superstore.hyper"
    duplicate = next(asset for asset in inventory["assets"] if asset["duplicate_of"] is not None)
    assert duplicate["tds_documents"] == []


def test_discovery_is_deterministic_for_fixed_inputs(tmp_path):
    datasources = tmp_path / "datasources"
    datasources.mkdir()
    shutil.copy2(_sample_tds(), datasources / "Superstore.tds")
    arguments = {
        "datasources_path": datasources,
        "mappings_path": tmp_path / "missing-mappings",
        "extraction_root": tmp_path / "extracted",
        "workflow_run_id": "run-123",
        "created_at": "2026-11-22T00:00:00Z",
    }

    assert discover_inputs(**arguments) == discover_inputs(**arguments)


def test_tdsx_rejects_parent_path_traversal(tmp_path):
    datasources = tmp_path / "datasources"
    datasources.mkdir()
    with zipfile.ZipFile(datasources / "Unsafe.tdsx", "w") as archive:
        archive.writestr("../outside.tds", _sample_tds().read_bytes())

    with pytest.raises(UnsafeArchiveError, match="Unsafe archive member path"):
        discover_inputs(
            datasources_path=datasources,
            mappings_path=tmp_path / "mappings",
            extraction_root=tmp_path / "extracted",
            workflow_run_id="run-123",
        )


def test_discovery_requires_at_least_one_datasource(tmp_path):
    datasources = tmp_path / "datasources"
    datasources.mkdir()

    with pytest.raises(ValueError, match="No .tds, .tdsx, .twb, or .twbx"):
        discover_inputs(
            datasources_path=datasources,
            mappings_path=tmp_path / "mappings",
            extraction_root=tmp_path / "extracted",
            workflow_run_id="run-123",
        )


WORKBOOK = """<?xml version='1.0' encoding='utf-8'?>
<workbook version="18.1">
  <datasources>
    <datasource hasconnection="false" name="Parameters">
      <column caption="Year" datatype="integer" name="[Parameter 1]" param-domain-type="any" value="2026"/>
    </datasource>
    <datasource caption="Orders Data" name="federated.orders" version="18.1">
      <connection class="federated">
        <named-connections>
          <named-connection caption="Orders" name="hyper.orders">
            <connection class="hyper" dbname="Data/Extracts/orders.hyper" schema="Extract"/>
          </named-connection>
        </named-connections>
        <relation connection="hyper.orders" name="Extract" table="[Extract].[Extract]" type="table"/>
      </connection>
      <column datatype="real" name="[Amount]" role="measure" type="quantitative"/>
    </datasource>
    <datasource caption="Targets" name="federated.targets" version="18.1">
      <connection class="federated">
        <named-connections>
          <named-connection caption="targets" name="textscan.targets">
            <connection class="textscan" directory="Data" filename="targets.csv"/>
          </named-connection>
        </named-connections>
        <relation connection="textscan.targets" name="targets.csv" table="[targets#csv]" type="table"/>
      </connection>
    </datasource>
    <datasource caption="Sales (published)" name="sqlproxy.sales" version="18.1">
      <connection class="sqlproxy" dbname="Sales" server="tableau.example"/>
    </datasource>
  </datasources>
</workbook>
"""


def _discover(tmp_path, datasources, **extra):
    return discover_inputs(
        datasources_path=datasources,
        mappings_path=tmp_path / "mappings",
        extraction_root=tmp_path / "extracted",
        workflow_run_id="run-123",
        created_at="2026-11-25T00:00:00Z",
        **extra,
    )


def test_twbx_yields_each_embedded_datasource_and_lists_published_references(tmp_path):
    datasources = tmp_path / "datasources"
    datasources.mkdir()
    with zipfile.ZipFile(datasources / "Sales Workbook.twbx", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Sales Workbook.twb", WORKBOOK)
        archive.writestr("Data/Extracts/orders.hyper", b"synthetic-hyper" * 100)
        archive.writestr("Data/targets.csv", b"region,target\n")

    inventory = _discover(tmp_path, datasources)

    asset = inventory["assets"][0]
    assert asset["kind"] == "TWBX"
    documents = {item["workbook_datasource"]: item for item in asset["tds_documents"]}
    assert sorted(documents) == ["Orders Data", "Targets"]
    assert documents["Orders Data"]["document_path"] == "Sales Workbook.twb#Orders Data"
    assert documents["Orders Data"]["extracts"] == ["Data/Extracts/orders.hyper"]
    assert documents["Targets"]["extracts"] == ["Data/targets.csv"]
    assert asset["published_datasources"] == ["Sales (published)"]
    assert inventory["summary"]["datasource_document_count"] == 2
    assert inventory["summary"]["published_datasource_count"] == 1
    # The extract is listed, never copied.
    extract = asset["embedded_extracts"][0]
    assert extract["extracted_path"] is None and extract["byte_size"] == 1500
    assert not list((tmp_path / "extracted").rglob("*.hyper"))

    parsed = parse_inventory_asset(inventory, 0)
    assert sorted(item["datasource_name"] for item in parsed) == ["Orders Data", "Targets"]
    assert len({item["datasource_id"] for item in parsed}) == 2


def test_plain_twb_is_split_without_extracts(tmp_path):
    datasources = tmp_path / "datasources"
    datasources.mkdir()
    (datasources / "Sales.twb").write_text(WORKBOOK, encoding="utf-8")

    asset = _discover(tmp_path, datasources)["assets"][0]

    assert asset["kind"] == "TWB"
    assert [item["extracts"] for item in asset["tds_documents"]] == [[], []]


def test_workbook_with_only_published_datasources_parses_to_nothing(tmp_path):
    datasources = tmp_path / "datasources"
    datasources.mkdir()
    published_only = WORKBOOK.split('<datasource caption="Orders Data"')[0] + WORKBOOK[WORKBOOK.index('<datasource caption="Sales (published)"'):]
    (datasources / "Published.twb").write_text(published_only, encoding="utf-8")

    inventory = _discover(tmp_path, datasources)

    assert inventory["assets"][0]["published_datasources"] == ["Sales (published)"]
    assert parse_inventory_asset(inventory, 0) == []


def test_large_extract_no_longer_blocks_discovery(tmp_path):
    datasources = tmp_path / "datasources"
    datasources.mkdir()
    with zipfile.ZipFile(datasources / "Big.tdsx", "w") as archive:
        archive.write(_sample_tds(), "Superstore.tds")
        archive.writestr("Data/Extracts/big.hyper", b"x" * 4096)

    # Member and total limits smaller than the extract: they apply only to the test converter now.
    limits = DiscoveryLimits(maximum_member_bytes=1024, maximum_uncompressed_bytes=1024)
    asset = _discover(tmp_path, datasources, limits=limits)["assets"][0]

    assert asset["embedded_extracts"][0]["byte_size"] == 4096
    assert len(asset["tds_documents"]) == 1


def test_oversized_definition_is_still_rejected(tmp_path):
    datasources = tmp_path / "datasources"
    datasources.mkdir()
    with zipfile.ZipFile(datasources / "Huge.tdsx", "w") as archive:
        archive.write(_sample_tds(), "Superstore.tds")

    with pytest.raises(UnsafeArchiveError, match="definition limit"):
        _discover(tmp_path, datasources, limits=DiscoveryLimits(maximum_tds_bytes=1024))


def test_workbook_with_a_dtd_is_rejected(tmp_path):
    datasources = tmp_path / "datasources"
    datasources.mkdir()
    (datasources / "Evil.twb").write_text(
        "<?xml version='1.0'?><!DOCTYPE workbook [<!ENTITY x 'y'>]><workbook/>", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="prohibited XML declaration"):
        _discover(tmp_path, datasources)
