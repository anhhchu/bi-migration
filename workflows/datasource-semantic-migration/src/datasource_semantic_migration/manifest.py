from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from . import __version__
from .config import WorkflowConfig
from .input_contract import InputContract


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_utc_timestamp(value: str) -> datetime:
    """Parse an ISO timestamp; values without a timezone are UTC, as Databricks job dynamic values are."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_run_folder_name(workflow_run_id: str, started_at: str) -> str:
    run_id = workflow_run_id.strip()
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("workflow_run_id must be path-safe")
    # Minute precision keeps folder names short; the run ID keeps them unique.
    return f"{run_id}--{parse_utc_timestamp(started_at).strftime('%Y-%m-%dT%H-%MZ')}"


def resolve_run_root(output_volume_path: str | Path, run_reference: str) -> Path:
    reference = run_reference.strip()
    if not RUN_ID_PATTERN.fullmatch(reference):
        raise ValueError("proposal_run_id must be a run ID or run folder name")
    runs_root = Path(output_volume_path) / "runs"
    exact_path = runs_root / reference
    if exact_path.is_dir():
        return exact_path
    matches = sorted(path for path in runs_root.glob(f"{reference}--*") if path.is_dir())
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"Proposal run not found: {reference}")
    raise ValueError(f"Proposal run ID is ambiguous: {reference}")


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
    timestamp = format_utc_timestamp(parse_utc_timestamp(created_at) if created_at else datetime.now(timezone.utc))
    run_folder_name = build_run_folder_name(workflow_run_id, timestamp)
    run_root = f"{config.output_volume_path}/runs/{run_folder_name}"
    return {
        "schema_version": "1.0",
        "workflow_run_id": workflow_run_id,
        "job_run_id": job_run_id,
        "created_at": timestamp,
        "generator": {"name": "datasource-semantic-migration", "version": __version__},
        "status": "SCAFFOLDED",
        "input": input_contract.as_dict(),
        "runtime": {
            "run_folder_name": run_folder_name,
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
