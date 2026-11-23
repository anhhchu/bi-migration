from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def validate_volume_path(value: str, field_name: str) -> str:
    normalized = value.rstrip("/")
    parts = normalized.split("/")
    if len(parts) < 5 or parts[0] != "" or parts[1] != "Volumes" or not all(parts[2:5]):
        raise ValueError(f"{field_name} must be a Unity Catalog Volume path beginning with /Volumes/<catalog>/<schema>/<volume>")
    return normalized


def validate_identifier(value: str, field_name: str) -> str:
    if not value or not value.replace("_", "").isalnum() or value[0].isdigit():
        raise ValueError(f"{field_name} must be a non-empty SQL identifier")
    return value


@dataclass(frozen=True)
class WorkflowConfig:
    output_volume_path: str
    candidate_catalog: str
    candidate_schema: str
    staging_schema: str
    warehouse_id: str
    max_concurrency: int = 10
    analysis_batch_size: int = 25
    analysis_batch_workers: int = 8
    max_repair_attempts: int = 3
    retention_days: int = 7
    policy_path: str = "config/default-policy.yaml"

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "WorkflowConfig":
        config = cls(
            output_volume_path=validate_volume_path(str(document.get("output_volume_path", "")), "output_volume_path"),
            candidate_catalog=validate_identifier(str(document.get("candidate_catalog", "")), "candidate_catalog"),
            candidate_schema=validate_identifier(str(document.get("candidate_schema", "")), "candidate_schema"),
            staging_schema=validate_identifier(str(document.get("staging_schema", "")), "staging_schema"),
            warehouse_id=str(document.get("warehouse_id", "")).strip(),
            max_concurrency=int(document.get("max_concurrency", 10)),
            analysis_batch_size=int(document.get("analysis_batch_size", 25)),
            analysis_batch_workers=int(document.get("analysis_batch_workers", 8)),
            max_repair_attempts=int(document.get("max_repair_attempts", 3)),
            retention_days=int(document.get("retention_days", 7)),
            policy_path=str(document.get("policy_path", "config/default-policy.yaml")),
        )
        if not config.warehouse_id:
            raise ValueError("warehouse_id is required")
        if not 1 <= config.max_concurrency <= 100:
            raise ValueError("max_concurrency must be between 1 and 100")
        if not 1 <= config.analysis_batch_size <= 500:
            raise ValueError("analysis_batch_size must be between 1 and 500")
        if not 1 <= config.analysis_batch_workers <= 32:
            raise ValueError("analysis_batch_workers must be between 1 and 32")
        if not 1 <= config.max_repair_attempts <= 10:
            raise ValueError("max_repair_attempts must be between 1 and 10")
        if config.retention_days < 1:
            raise ValueError("retention_days must be positive")
        return config


def load_workflow_config(path: str | Path) -> WorkflowConfig:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise ValueError("Workflow configuration must be a YAML object")
    return WorkflowConfig.from_dict(document)
