from pathlib import Path

import pytest

from datasource_semantic_migration.config import WorkflowConfig, load_workflow_config


def test_load_workflow_config():
    root = Path(__file__).resolve().parents[1]
    config = load_workflow_config(root / "config" / "workflow.example.yaml")

    assert config.output_volume_path == "/Volumes/main/bi_migration/semantic_workflows"
    assert config.max_concurrency == 10
    assert config.analysis_batch_size == 25
    assert config.analysis_batch_workers == 8
    assert config.max_repair_attempts == 3


def test_config_rejects_local_output_path():
    with pytest.raises(ValueError, match="Unity Catalog Volume"):
        WorkflowConfig.from_dict(
            {
                "output_volume_path": "/tmp/output",
                "candidate_catalog": "main",
                "candidate_schema": "candidates",
                "staging_schema": "staging",
                "warehouse_id": "warehouse",
            }
        )
