from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path


TABLEAU_EXTENSIONS = {".twb", ".twbx"}
MAPPING_EXTENSIONS = {".csv", ".json", ".yaml", ".yml", ".md"}


def _artifact_type(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in TABLEAU_EXTENSIONS:
        return "tableau_workbook"
    if suffix in MAPPING_EXTENSIONS:
        return "mapping_document"
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_artifact_manifest(*roots: str | Path, source_base_uri: str | None = None) -> list[dict]:
    artifacts = []
    for root_value in roots:
        root = Path(root_value)
        candidates = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
        for path in candidates:
            artifact_type = _artifact_type(path)
            if not artifact_type:
                continue
            checksum = _sha256(path)
            stat = path.stat()
            relative_path = path.name if root.is_file() else str(path.relative_to(root))
            artifacts.append(
                {
                    "artifact_id": checksum[:16],
                    "artifact_type": artifact_type,
                    "path": str(path),
                    "relative_path": relative_path,
                    "extension": path.suffix.lower(),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "sha256": checksum,
                    "status": "registered",
                    "source_uri": _source_uri(source_base_uri, artifact_type, relative_path, path),
                }
            )
    return sorted(artifacts, key=lambda item: (item["artifact_type"], item["relative_path"]))


def _source_uri(
    source_base_uri: str | None,
    artifact_type: str,
    relative_path: str,
    local_path: Path,
) -> str:
    if not source_base_uri:
        return local_path.resolve().as_uri()
    category = "workbooks" if artifact_type == "tableau_workbook" else "mappings"
    return "/".join(
        [source_base_uri.rstrip("/"), category, relative_path.replace("\\", "/").lstrip("/")]
    )


def build_run_manifest(
    artifacts: Iterable[dict],
    run_id: str,
    source_base_uri: str | None = None,
) -> dict:
    artifact_list = list(artifacts)
    return {
        "manifest_version": "1.0",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_base_uri": source_base_uri,
        "artifact_count": len(artifact_list),
        "workbook_count": sum(item["artifact_type"] == "tableau_workbook" for item in artifact_list),
        "mapping_document_count": sum(item["artifact_type"] == "mapping_document" for item in artifact_list),
        "artifacts": artifact_list,
    }
