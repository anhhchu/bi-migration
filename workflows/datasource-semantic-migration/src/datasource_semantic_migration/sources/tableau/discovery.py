from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from xml.etree import ElementTree

from ... import __version__
from ...artifacts import sha256_file


SUPPORTED_DATASOURCE_SUFFIXES = {".tds", ".tdsx"}
# Any YAML, JSON, or CSV file in mappings/ is read as table mapping; several files are merged.
SUPPORTED_MAPPING_SUFFIXES = {".yaml", ".yml", ".json", ".csv"}
EMBEDDED_EXTRACT_SUFFIXES = {".hyper", ".tde"}


class UnsafeArchiveError(ValueError):
    """Raised when a packaged datasource violates extraction safety limits."""


@dataclass(frozen=True)
class DiscoveryLimits:
    maximum_archive_entries: int = 10_000
    maximum_member_bytes: int = 512 * 1024 * 1024
    maximum_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    maximum_tds_bytes: int = 128 * 1024 * 1024


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalized_member_path(name: str) -> PurePosixPath:
    if "\x00" in name:
        raise UnsafeArchiveError("Archive member contains a null byte")
    normalized_name = name.replace("\\", "/")
    member_path = PurePosixPath(normalized_name)
    if member_path.is_absolute() or any(part in {"", ".", ".."} for part in member_path.parts):
        raise UnsafeArchiveError(f"Unsafe archive member path: {name}")
    if member_path.parts and ":" in member_path.parts[0]:
        raise UnsafeArchiveError(f"Unsafe archive member path: {name}")
    return member_path


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    unix_mode = member.external_attr >> 16
    return stat.S_ISLNK(unix_mode)


def _copy_bounded(source: BinaryIO, destination: BinaryIO, limit: int) -> int:
    written = 0
    while chunk := source.read(min(1024 * 1024, limit - written + 1)):
        written += len(chunk)
        if written > limit:
            raise UnsafeArchiveError(f"Archive member exceeds {limit} bytes")
        destination.write(chunk)
    return written


def safely_extract_tdsx(
    archive_path: Path,
    destination: Path,
    *,
    limits: DiscoveryLimits | None = None,
) -> list[dict[str, Any]]:
    limits = limits or DiscoveryLimits()
    if not zipfile.is_zipfile(archive_path):
        raise UnsafeArchiveError(f"Packaged datasource is not a valid ZIP archive: {archive_path.name}")

    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    actual_total = 0

    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > limits.maximum_archive_entries:
            raise UnsafeArchiveError(
                f"Archive contains {len(members)} entries; limit is {limits.maximum_archive_entries}"
            )
        declared_total = sum(member.file_size for member in members if not member.is_dir())
        if declared_total > limits.maximum_uncompressed_bytes:
            raise UnsafeArchiveError(
                f"Archive declares {declared_total} uncompressed bytes; limit is {limits.maximum_uncompressed_bytes}"
            )

        for member in members:
            member_path = _normalized_member_path(member.filename)
            normalized = member_path.as_posix()
            collision_key = normalized.casefold()
            if collision_key in seen_paths:
                raise UnsafeArchiveError(f"Archive contains a duplicate member path: {normalized}")
            seen_paths.add(collision_key)
            if member.flag_bits & 0x1:
                raise UnsafeArchiveError(f"Encrypted archive member is unsupported: {normalized}")
            if _is_symlink(member):
                raise UnsafeArchiveError(f"Archive symlink is unsupported: {normalized}")
            if member.is_dir():
                (destination / Path(*member_path.parts)).mkdir(parents=True, exist_ok=True)
                continue
            if member.file_size > limits.maximum_member_bytes:
                raise UnsafeArchiveError(
                    f"Archive member {normalized} declares {member.file_size} bytes; "
                    f"limit is {limits.maximum_member_bytes}"
                )

            output_path = destination / Path(*member_path.parts)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with archive.open(member) as source, output_path.open("wb") as target:
                    written = _copy_bounded(source, target, limits.maximum_member_bytes)
            except Exception:
                output_path.unlink(missing_ok=True)
                raise
            actual_total += written
            if actual_total > limits.maximum_uncompressed_bytes:
                output_path.unlink(missing_ok=True)
                raise UnsafeArchiveError(
                    f"Archive exceeds {limits.maximum_uncompressed_bytes} extracted bytes"
                )
            extracted.append(
                {
                    "relative_path": normalized,
                    "extracted_path": output_path.as_posix(),
                    "byte_size": written,
                    "sha256": sha256_file(output_path),
                    "kind": _member_kind(output_path.suffix),
                }
            )
    return sorted(extracted, key=lambda item: item["relative_path"].casefold())


def _member_kind(suffix: str) -> str:
    normalized = suffix.casefold()
    if normalized == ".tds":
        return "TDS"
    if normalized == ".hyper":
        return "HYPER"
    if normalized == ".tde":
        return "TDE"
    if normalized in {".csv", ".json", ".parquet", ".xls", ".xlsx"}:
        return "DATA_FILE"
    return "SUPPORT_FILE"


def inspect_tds(path: Path, *, limits: DiscoveryLimits | None = None) -> dict[str, Any]:
    limits = limits or DiscoveryLimits()
    byte_size = path.stat().st_size
    if byte_size > limits.maximum_tds_bytes:
        raise ValueError(f"TDS file {path.name} exceeds {limits.maximum_tds_bytes} bytes")
    with path.open("rb") as handle:
        prefix = handle.read(8192).upper()
    if b"<!DOCTYPE" in prefix or b"<!ENTITY" in prefix:
        raise ValueError(f"TDS file {path.name} contains a prohibited XML declaration")
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as error:
        raise ValueError(f"Invalid TDS XML in {path.name}: {error}") from error
    if root.tag.rsplit("}", 1)[-1] != "datasource":
        raise ValueError(f"TDS file {path.name} does not have a datasource root element")

    connection_classes = sorted(
        {
            element.attrib["class"]
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "connection" and element.attrib.get("class")
        }
    )
    relation_count = sum(1 for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "relation")
    calculation_count = sum(1 for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "calculation")
    display_name = root.attrib.get("caption") or root.attrib.get("name") or root.attrib.get("formatted-name")
    return {
        "path": path.as_posix(),
        "byte_size": byte_size,
        "sha256": sha256_file(path),
        "datasource_name": display_name,
        "source_system": "tableau",
        "source_version": root.attrib.get("version"),
        "connection_classes": connection_classes,
        "relation_count": relation_count,
        "calculation_count": calculation_count,
    }


def _discover_files(root: Path, suffixes: set[str]) -> list[Path]:
    if not root.exists():
        raise FileNotFoundError(f"Required input directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {root}")
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in suffixes and not path.is_symlink()
    ]
    return sorted(files, key=lambda path: path.relative_to(root).as_posix().casefold())


def _mapping_inventory(mappings_path: Path) -> list[dict[str, Any]]:
    if not mappings_path.exists():
        return []
    if not mappings_path.is_dir():
        raise NotADirectoryError(f"Mappings path is not a directory: {mappings_path}")
    mappings = []
    for path in sorted(mappings_path.iterdir(), key=lambda item: item.name.casefold()):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.name.startswith(".")
            or path.suffix.casefold() not in SUPPORTED_MAPPING_SUFFIXES
        ):
            continue
        mappings.append(
            {
                "path": path.as_posix(),
                "format": path.suffix.casefold().lstrip("."),
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return mappings


def discover_inputs(
    *,
    datasources_path: str | Path,
    mappings_path: str | Path,
    extraction_root: str | Path,
    workflow_run_id: str,
    created_at: str | None = None,
    limits: DiscoveryLimits | None = None,
) -> dict[str, Any]:
    if not workflow_run_id.strip():
        raise ValueError("workflow_run_id is required")
    limits = limits or DiscoveryLimits()
    datasource_root = Path(datasources_path)
    output_root = Path(extraction_root)
    input_files = _discover_files(datasource_root, SUPPORTED_DATASOURCE_SUFFIXES)
    if not input_files:
        raise ValueError(f"No .tds or .tdsx files found beneath {datasource_root}")

    assets: list[dict[str, Any]] = []
    canonical_hashes: dict[str, str] = {}
    embedded_extract_count = 0
    for input_path in input_files:
        relative_path = input_path.relative_to(datasource_root).as_posix()
        content_hash = sha256_file(input_path)
        duplicate_of = canonical_hashes.get(content_hash)
        if duplicate_of is None:
            canonical_hashes[content_hash] = relative_path
        asset = {
            "asset_id": content_hash,
            "relative_path": relative_path,
            "source_path": input_path.as_posix(),
            "kind": input_path.suffix.casefold().lstrip(".").upper(),
            "byte_size": input_path.stat().st_size,
            "sha256": content_hash,
            "duplicate_of": duplicate_of,
            "tds_documents": [],
            "archive_members": [],
            "embedded_extracts": [],
        }
        if duplicate_of is None and input_path.suffix.casefold() == ".tds":
            asset["tds_documents"] = [inspect_tds(input_path, limits=limits)]
        elif duplicate_of is None:
            extraction_path = output_root / content_hash
            members = safely_extract_tdsx(input_path, extraction_path, limits=limits)
            tds_members = [member for member in members if member["kind"] == "TDS"]
            if not tds_members:
                raise ValueError(f"Packaged datasource {relative_path} contains no .tds definition")
            asset["archive_members"] = members
            asset["tds_documents"] = [
                inspect_tds(Path(member["extracted_path"]), limits=limits) for member in tds_members
            ]
            asset["embedded_extracts"] = [
                member for member in members if member["kind"] in {"HYPER", "TDE"}
            ]
            embedded_extract_count += len(asset["embedded_extracts"])
        assets.append(asset)

    inventory_basis = [
        {"relative_path": asset["relative_path"], "sha256": asset["sha256"]} for asset in assets
    ]
    inventory_hash = hashlib.sha256(
        json.dumps(inventory_basis, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    mappings = _mapping_inventory(Path(mappings_path))
    return {
        "schema_version": "1.0",
        "workflow_run_id": workflow_run_id,
        "created_at": created_at or _utc_timestamp(),
        "generator": {"name": "datasource-semantic-migration", "version": __version__},
        "status": "COMPLETE",
        "inventory_hash": inventory_hash,
        "datasources_path": datasource_root.as_posix(),
        "mappings_path": Path(mappings_path).as_posix(),
        "extraction_root": output_root.as_posix(),
        "summary": {
            "discovered_count": len(assets),
            "unique_count": len(canonical_hashes),
            "duplicate_count": len(assets) - len(canonical_hashes),
            "tds_count": sum(asset["kind"] == "TDS" for asset in assets),
            "tdsx_count": sum(asset["kind"] == "TDSX" for asset in assets),
            "embedded_extract_count": embedded_extract_count,
            "mapping_file_count": len(mappings),
        },
        "assets": assets,
        "mapping_files": mappings,
    }


def write_inventory(inventory: dict[str, Any], destination: str | Path) -> Path:
    output_path = Path(destination)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temporary_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary_path.replace(output_path)
    return output_path
