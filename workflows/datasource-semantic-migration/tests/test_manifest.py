from pathlib import Path

import pytest

from datasource_semantic_migration.config import WorkflowConfig
from datasource_semantic_migration.manifest import build_run_folder_name, build_workflow_manifest, resolve_run_root


def config():
    return WorkflowConfig.from_dict(
        {
            "output_volume_path": "/Volumes/main/bi_migration/semantic_workflows",
            "candidate_catalog": "main",
            "candidate_schema": "bi_migration",
            "staging_schema": "bi_migration_staging",
            "warehouse_id": "warehouse-123",
        }
    )


def test_manifest_is_deterministic_for_fixed_inputs():
    arguments = {
        "workflow_run_id": "123",
        "job_run_id": "123",
        "input_volume_path": "/Volumes/main/bi_migration/tableau_sources",
        "config": config(),
        "created_at": "2026-11-22T00:00:00Z",
    }

    first = build_workflow_manifest(**arguments)
    second = build_workflow_manifest(**arguments)

    assert first == second
    assert first["created_at"] == "2026-11-22T00:00:00Z"
    assert first["runtime"]["run_folder_name"] == "123--2026-11-22T00-00Z"
    assert first["runtime"]["run_root"].endswith("/runs/123--2026-11-22T00-00Z")
    assert first["input"]["datasources_path"].endswith("/datasources")
    assert first["deployment"]["candidate_schema"] == "bi_migration"
    assert first["deployment"]["analysis_batch_size"] == 25
    assert first["deployment"]["analysis_batch_workers"] == 8


def test_run_folder_name_normalizes_start_time_to_utc():
    assert build_run_folder_name("456", "2026-11-22T16:30:15-08:00") == "456--2026-11-23T00-30Z"


def test_job_start_time_without_timezone_is_treated_as_utc():
    # {{job.start_time.iso_datetime}} has no offset; it must not fail the inventory task.
    assert build_run_folder_name("789", "2026-11-24T01:20:15") == "789--2026-11-24T01-20Z"
    manifest = build_workflow_manifest(
        workflow_run_id="789",
        job_run_id="789",
        input_volume_path="/Volumes/main/bi_migration/tableau_sources",
        config=config(),
        created_at="2026-11-24T01:20:15.123",
    )
    assert manifest["created_at"] == "2026-11-24T01:20:15Z"


def test_resolve_run_root_supports_new_and_legacy_names(tmp_path: Path):
    runs_root = tmp_path / "runs"
    timestamped = runs_root / "123--2026-11-22T00-00-00Z"
    legacy = runs_root / "456"
    timestamped.mkdir(parents=True)
    legacy.mkdir()

    assert resolve_run_root(tmp_path, "123") == timestamped
    assert resolve_run_root(tmp_path, timestamped.name) == timestamped
    assert resolve_run_root(tmp_path, "456") == legacy


def test_resolve_run_root_rejects_ambiguous_run_ids(tmp_path: Path):
    (tmp_path / "runs" / "123--2026-11-22T00-00-00Z").mkdir(parents=True)
    (tmp_path / "runs" / "123--2026-11-23T00-00-00Z").mkdir()

    with pytest.raises(ValueError, match="ambiguous"):
        resolve_run_root(tmp_path, "123")
