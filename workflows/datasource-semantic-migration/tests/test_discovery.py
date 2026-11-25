from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from datasource_semantic_migration.sources.tableau.discovery import UnsafeArchiveError, discover_inputs


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
        "embedded_extract_count": 1,
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

    with pytest.raises(ValueError, match="No .tds or .tdsx"):
        discover_inputs(
            datasources_path=datasources,
            mappings_path=tmp_path / "mappings",
            extraction_root=tmp_path / "extracted",
            workflow_run_id="run-123",
        )
