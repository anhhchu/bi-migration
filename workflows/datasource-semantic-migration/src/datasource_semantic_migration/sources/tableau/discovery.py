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
from .workbooks import (
    datasource_document,
    document_slug,
    extract_references,
    parse_workbook_xml,
    workbook_datasources,
)


SUPPORTED_DATASOURCE_SUFFIXES = {".tds", ".tdsx", ".twb", ".twbx"}
# The definition each package kind holds; it is the only member discovery unzips.
PACKAGE_DEFINITION_SUFFIXES = {".tdsx": ".tds", ".twbx": ".twb"}
# Any YAML, JSON, or CSV file in mappings/ is read as table mapping; several files are merged.
SUPPORTED_MAPPING_SUFFIXES = {".yaml", ".yml", ".json", ".csv"}
EMBEDDED_EXTRACT_SUFFIXES = {".hyper", ".tde"}


class UnsafeArchiveError(ValueError):
    """Raised when a packaged datasource violates extraction safety limits."""


@dataclass(frozen=True)
class DiscoveryLimits:
    """Safety limits for untrusted uploads.

    Discovery unzips only definitions (.tds, .twb), so extracts of any size pass: they are listed,
    not copied. The definition limits bound memory, because XML is parsed whole. The member and
    uncompressed limits apply only to the TWBX-to-TDSX test converter, which copies extracts.
    """

    maximum_archive_entries: int = 10_000
    maximum_member_bytes: int = 512 * 1024 * 1024
    maximum_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    maximum_tds_bytes: int = 128 * 1024 * 1024
    maximum_workbook_bytes: int = 256 * 1024 * 1024


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


def open_package(
    archive_path: Path,
    destination: Path,
    *,
    definition_suffix: str,
    limits: DiscoveryLimits | None = None,
) -> list[dict[str, Any]]:
    """Check a .tdsx or .twbx and unzip only its definitions; list every other member.

    Security checks cover every member. Extracts and other data files are listed with their declared
    size and are not copied (extracted_path is None).
    """
    limits = limits or DiscoveryLimits()
    if not zipfile.is_zipfile(archive_path):
        raise UnsafeArchiveError(f"Package is not a valid ZIP archive: {archive_path.name}")
    definition_limit = limits.maximum_workbook_bytes if definition_suffix == ".twb" else limits.maximum_tds_bytes

    destination.mkdir(parents=True, exist_ok=True)
    listed: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > limits.maximum_archive_entries:
            raise UnsafeArchiveError(
                f"Archive contains {len(members)} entries; limit is {limits.maximum_archive_entries}"
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
                continue
            entry = {
                "relative_path": normalized,
                "extracted_path": None,
                "byte_size": member.file_size,
                "sha256": None,
                "kind": _member_kind(member_path.suffix),
            }
            if member_path.suffix.casefold() == definition_suffix:
                if member.file_size > definition_limit:
                    raise UnsafeArchiveError(
                        f"{normalized} declares {member.file_size} bytes; definition limit is {definition_limit}"
                    )
                output_path = destination / Path(*member_path.parts)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with archive.open(member) as source, output_path.open("wb") as target:
                        written = _copy_bounded(source, target, definition_limit)
                except Exception:
                    output_path.unlink(missing_ok=True)
                    raise
                entry.update({"extracted_path": output_path.as_posix(), "byte_size": written, "sha256": sha256_file(output_path)})
            listed.append(entry)
    return sorted(listed, key=lambda item: item["relative_path"].casefold())


def safely_extract_tdsx(
    archive_path: Path,
    destination: Path,
    *,
    limits: DiscoveryLimits | None = None,
) -> list[dict[str, Any]]:
    """The .tds definitions of a .tdsx unzipped; other members listed."""
    return open_package(archive_path, destination, definition_suffix=".tds", limits=limits)


def _member_kind(suffix: str) -> str:
    normalized = suffix.casefold()
    if normalized == ".tds":
        return "TDS"
    if normalized == ".twb":
        return "TWB"
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


def _datasource_entry(
    path: Path,
    *,
    document_path: str,
    extracts: list[str],
    limits: DiscoveryLimits,
    workbook_datasource: str | None = None,
) -> dict[str, Any]:
    entry = inspect_tds(path, limits=limits)
    entry.update({"document_path": document_path, "extracts": extracts})
    if workbook_datasource is not None:
        entry["workbook_datasource"] = workbook_datasource
    return entry


def _split_workbook(
    asset: dict[str, Any],
    document: bytes,
    *,
    workbook_path: str,
    destination: Path,
    member_names: list[str],
    limits: DiscoveryLimits,
) -> None:
    """Write each datasource defined in the workbook as its own .tds document."""
    root = parse_workbook_xml(document, name=workbook_path)
    embedded, published = workbook_datasources(root)
    if not embedded and not published:
        raise ValueError(f"{asset['relative_path']} contains no connected datasources")
    asset["published_datasources"] = published
    used: set[str] = set()
    for name, datasource in embedded:
        tds_document = datasource_document(datasource)
        slug = document_slug(Path(workbook_path).stem, name, tds_document, used)
        output_path = destination / "datasources" / f"{slug}.tds"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(tds_document)
        asset["tds_documents"].append(
            _datasource_entry(
                output_path,
                document_path=f"{workbook_path}#{name}",
                extracts=extract_references(datasource, member_names),
                limits=limits,
                workbook_datasource=name,
            )
        )


def _inventory_asset(asset: dict[str, Any], input_path: Path, destination: Path, limits: DiscoveryLimits) -> None:
    """Fill the asset's datasource documents; packages are unzipped for their definitions only."""
    suffix = input_path.suffix.casefold()
    if suffix == ".tds":
        asset["tds_documents"] = [
            _datasource_entry(input_path, document_path=asset["relative_path"], extracts=[], limits=limits)
        ]
        return
    if suffix == ".twb":
        if asset["byte_size"] > limits.maximum_workbook_bytes:
            raise ValueError(f"Workbook {input_path.name} exceeds {limits.maximum_workbook_bytes} bytes")
        _split_workbook(
            asset,
            input_path.read_bytes(),
            workbook_path=asset["relative_path"],
            destination=destination,
            member_names=[],
            limits=limits,
        )
        return
    definition_suffix = PACKAGE_DEFINITION_SUFFIXES[suffix]
    members = open_package(input_path, destination, definition_suffix=definition_suffix, limits=limits)
    asset["archive_members"] = members
    asset["embedded_extracts"] = [member for member in members if member["kind"] in {"HYPER", "TDE"}]
    member_names = [member["relative_path"] for member in members]
    definitions = [member for member in members if member["extracted_path"]]
    if suffix == ".tdsx":
        if not definitions:
            raise ValueError(f"Packaged datasource {asset['relative_path']} contains no .tds definition")
        for member in definitions:
            definition_path = Path(member["extracted_path"])
            # inspect_tds checks size and refuses DTDs before the definition is parsed for its extracts.
            entry = _datasource_entry(definition_path, document_path=member["relative_path"], extracts=[], limits=limits)
            entry["extracts"] = extract_references(ElementTree.parse(definition_path).getroot(), member_names)
            asset["tds_documents"].append(entry)
        return
    if len(definitions) != 1:
        raise ValueError(
            f"Packaged workbook {asset['relative_path']} must contain exactly one .twb; found {len(definitions)}"
        )
    _split_workbook(
        asset,
        Path(definitions[0]["extracted_path"]).read_bytes(),
        workbook_path=definitions[0]["relative_path"],
        destination=destination,
        member_names=member_names,
        limits=limits,
    )


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
        raise ValueError(f"No .tds, .tdsx, .twb, or .twbx files found beneath {datasource_root}")

    assets: list[dict[str, Any]] = []
    canonical_hashes: dict[str, str] = {}
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
            "published_datasources": [],
        }
        if duplicate_of is None:
            _inventory_asset(asset, input_path, output_root / content_hash, limits)
        assets.append(asset)
    embedded_extract_count = sum(len(asset["embedded_extracts"]) for asset in assets)

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
            "twb_count": sum(asset["kind"] == "TWB" for asset in assets),
            "twbx_count": sum(asset["kind"] == "TWBX" for asset in assets),
            "datasource_document_count": sum(len(asset["tds_documents"]) for asset in assets),
            "embedded_extract_count": embedded_extract_count,
            "published_datasource_count": sum(len(asset["published_datasources"]) for asset in assets),
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
