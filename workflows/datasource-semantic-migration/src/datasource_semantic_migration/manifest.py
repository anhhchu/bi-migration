from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import __version__
from .config import WorkflowConfig
from .input_contract import InputContract


def build_workflow_manifest(
    *,
    workflow_run_id: str,
    job_run_id: str,
    input_volume_path: str,
    config: WorkflowConfig,
    created_at: str | None = None,
) -> dict[str, Any]:
    if not workflow_run_id.strip():
        raise ValueError("workflow_run_id is required")
    if not job_run_id.strip():
        raise ValueError("job_run_id is required")
    input_contract = InputContract.create(input_volume_path)
    timestamp = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_root = f"{config.output_volume_path}/runs/{workflow_run_id}"
    return {
        "schema_version": "1.0",
        "workflow_run_id": workflow_run_id,
        "job_run_id": job_run_id,
        "created_at": timestamp,
        "generator": {"name": "datasource-semantic-migration", "version": __version__},
        "status": "SCAFFOLDED",
        "input": input_contract.as_dict(),
        "runtime": {
            "run_root": run_root,
            "groups_path": f"{run_root}/groups",
            "reports_path": f"{run_root}/reports",
            "internal_path": f"{run_root}/_internal",
        },
        "deployment": {
            "candidate_catalog": config.candidate_catalog,
            "candidate_schema": config.candidate_schema,
            "staging_schema": config.staging_schema,
            "warehouse_id": config.warehouse_id,
            "max_concurrency": config.max_concurrency,
            "analysis_batch_size": config.analysis_batch_size,
            "analysis_batch_workers": config.analysis_batch_workers,
            "max_repair_attempts": config.max_repair_attempts,
            "retention_days": config.retention_days,
            "policy_path": config.policy_path,
        },
    }
