from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from datasource_semantic_migration.sources.tableau.discovery import UnsafeArchiveError
from datasource_semantic_migration.sources.tableau.twbx_converter import (
    convert_twbx,
    convert_twbx_directory,
    upload_tdsx_files,
)


WORKBOOK = """<?xml version='1.0' encoding='utf-8'?>
<workbook version="18.1">
  <datasources>
    <datasource hasconnection="false" name="Parameters">
      <column caption="Year" datatype="integer" name="[Parameter 1]" param-domain-type="any" value="2026"/>
    </datasource>
    <datasource caption="Orders Data" name="federated.test" version="18.1">
      <connection class="federated">
        <named-connections>
          <named-connection caption="Orders" name="hyper.test">
            <connection class="hyper" dbname="Data/Extracts/orders.hyper" schema="Extract"/>
          </named-connection>
        </named-connections>
        <relation connection="hyper.test" name="Extract" table="[Extract].[Extract]" type="table"/>
        <metadata-records>
          <metadata-record class="column">
            <remote-name>Order ID</remote-name>
            <remote-type>129</remote-type>
            <local-name>[Order ID]</local-name>
            <local-type>string</local-type>
            <ordinal>0</ordinal>
          </metadata-record>
        </metadata-records>
      </connection>
    </datasource>
  </datasources>
</workbook>
"""


def _write_twbx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Orders.twb", WORKBOOK)
        archive.writestr("Data/Extracts/orders.hyper", b"synthetic-hyper")


def test_converter_creates_one_valid_package_per_connected_datasource(tmp_path):
    source = tmp_path / "Finance #1.twbx"
    _write_twbx(source)

    converted = convert_twbx(source, tmp_path / "output")

    assert len(converted) == 1
    result = converted[0]
    assert result.output_path.name == "finance-1-orders-data.tdsx"
    assert result.dependencies == ("Data/Extracts/orders.hyper",)
    assert result.validation["status"] == "PASS"
    assert result.validation["field_count"] == 1
    with zipfile.ZipFile(result.output_path) as package:
        assert sorted(package.namelist()) == [
            "Data/Extracts/orders.hyper",
            "finance-1-orders-data.tds",
        ]


def test_directory_conversion_replaces_stale_outputs_and_writes_manifest(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _write_twbx(inputs / "Orders.twbx")
    output = tmp_path / "output"
    (output / "datasources").mkdir(parents=True)
    (output / "datasources" / "stale.tdsx").write_bytes(b"stale")

    manifest = convert_twbx_directory(inputs, output)

    assert manifest["status"] == "PASS"
    assert manifest["summary"] == {
        "workbook_count": 1,
        "datasource_count": 1,
        "validated_count": 1,
        "embedded_extract_count": 1,
    }
    assert not (output / "datasources" / "stale.tdsx").exists()
    assert (output / "conversion-manifest.json").exists()


def test_converter_rejects_unsafe_workbook_archive(tmp_path):
    source = tmp_path / "unsafe.twbx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Workbook.twb", WORKBOOK)
        archive.writestr("../orders.hyper", b"unsafe")

    with pytest.raises(UnsafeArchiveError, match="Unsafe archive member path"):
        convert_twbx(source, tmp_path / "output")


def test_upload_uses_workflow_datasources_directory(tmp_path, monkeypatch):
    (tmp_path / "one.tdsx").write_bytes(b"one")
    (tmp_path / "two.tdsx").write_bytes(b"two")
    commands = []

    def record_command(arguments):
        commands.append(arguments)

    monkeypatch.setattr(
        "datasource_semantic_migration.sources.tableau.twbx_converter._run_databricks_cli",
        record_command,
    )

    result = upload_tdsx_files(
        tmp_path,
        volume_root="/Volumes/main/bi_migration/tableau_datasources",
        profile="DEFAULT",
    )

    assert result["uploaded_count"] == 2
    assert result["destination"] == "/Volumes/main/bi_migration/tableau_datasources/datasources"
    assert commands[0] == [
        "fs",
        "mkdir",
        "dbfs:/Volumes/main/bi_migration/tableau_datasources/datasources",
        "--profile",
        "DEFAULT",
    ]
    assert commands[1][-3:] == ["--overwrite", "--profile", "DEFAULT"]
