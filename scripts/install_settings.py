"""Per-workspace installation settings, shared by install.py and the deploy scripts.

Catalog, schema, Volumes, and warehouse differ per workspace, so they are not in
databricks.yml. install.py saves them per CLI profile (one profile per workspace) in
.databricks/bi-migration/<profile>.json, which is gitignored. Every deploy reads them
back and also writes them to each bundle's variable-overrides.json so plain
`databricks bundle` commands use the same values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "workflows" / "datasource-semantic-migration"
SETTINGS_DIR = ROOT / ".databricks" / "bi-migration"


def settings_path(profile: str) -> Path:
    return SETTINGS_DIR / f"{profile}.json"


def load_settings(profile: str) -> dict[str, Any] | None:
    path = settings_path(profile)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def require_settings(profile: str) -> dict[str, Any]:
    settings = load_settings(profile)
    if not settings:
        raise SystemExit(
            f"No installation settings for profile '{profile}'. Run: "
            f"python3 scripts/install.py --profile {profile} --catalog <catalog>"
        )
    return settings


def save_settings(profile: str, settings: dict[str, Any]) -> Path:
    path = settings_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def volume_path(full_name: str) -> str:
    return "/Volumes/" + full_name.replace(".", "/")


def workflow_variables(settings: dict[str, Any]) -> dict[str, str]:
    return {
        "output_volume_path": volume_path(settings["output_volume"]),
        "candidate_catalog": settings["catalog"],
        "candidate_schema": settings["schema"],
        "staging_schema": settings["staging_schema"],
        "warehouse_id": settings["warehouse_id"],
    }


def app_variables(settings: dict[str, Any]) -> dict[str, str]:
    return {
        "volume_full_name": settings["upload_volume"],
        "datasource_semantic_volume_full_name": settings["output_volume"],
    }


def write_overrides(bundle_dir: Path, target: str, variables: dict[str, str]) -> None:
    """Merge values into the bundle's variable-overrides.json for this target."""
    path = bundle_dir / ".databricks" / "bundle" / target / "variable-overrides.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    path.write_text(json.dumps({**current, **variables}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def apply_settings(settings: dict[str, Any], target: str) -> None:
    """Point both bundles at this workspace's catalog, schemas, Volumes, and warehouse."""
    write_overrides(WORKFLOW_DIR, target, workflow_variables(settings))
    write_overrides(ROOT, target, app_variables(settings))
