from datasource_semantic_migration.config import WorkflowConfig
from datasource_semantic_migration.manifest import build_workflow_manifest


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
    assert first["runtime"]["run_root"].endswith("/runs/123")
    assert first["input"]["datasources_path"].endswith("/datasources")
    assert first["deployment"]["candidate_schema"] == "bi_migration"
    assert first["deployment"]["analysis_batch_size"] == 25
    assert first["deployment"]["analysis_batch_workers"] == 8
