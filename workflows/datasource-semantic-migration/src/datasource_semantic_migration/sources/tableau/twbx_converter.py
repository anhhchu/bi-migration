from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree

from ...artifacts import sha256_file
from .discovery import DiscoveryLimits, UnsafeArchiveError, inspect_tds, safely_extract_tdsx
from .parser import parse_tableau_datasource


PACKAGED_DATA_SUFFIXES = {
    ".csv",
    ".hyper",
    ".json",
    ".parquet",
    ".tde",
    ".txt",
    ".xls",
    ".xlsx",
}


@dataclass(frozen=True)
class ConvertedDatasource:
    workbook_path: Path
    datasource_name: str
    output_path: Path
    dependencies: tuple[str, ...]
    validation: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "workbook_path": self.workbook_path.as_posix(),
            "datasource_name": self.datasource_name,
            "output_path": self.output_path.as_posix(),
            "output_file": self.output_path.name,
            "byte_size": self.output_path.stat().st_size,
            "sha256": sha256_file(self.output_path),
            "dependencies": list(self.dependencies),
            "validation": self.validation,
        }


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _safe_member_name(name: str) -> str:
    if "\x00" in name:
        raise UnsafeArchiveError("Archive member contains a null byte")
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafeArchiveError(f"Unsafe archive member path: {name}")
    if path.parts and ":" in path.parts[0]:
        raise UnsafeArchiveError(f"Unsafe archive member path: {name}")
    return path.as_posix()


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(member.external_attr >> 16)


def _validated_members(
    archive: zipfile.ZipFile,
    *,
    limits: DiscoveryLimits,
) -> dict[str, zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > limits.maximum_archive_entries:
        raise UnsafeArchiveError(
            f"Archive contains {len(members)} entries; limit is {limits.maximum_archive_entries}"
        )
    declared_total = sum(member.file_size for member in members if not member.is_dir())
    if declared_total > limits.maximum_uncompressed_bytes:
        raise UnsafeArchiveError(
            f"Archive declares {declared_total} uncompressed bytes; "
            f"limit is {limits.maximum_uncompressed_bytes}"
        )

    validated: dict[str, zipfile.ZipInfo] = {}
    for member in members:
        normalized = _safe_member_name(member.filename)
        collision_key = normalized.casefold()
        if collision_key in validated:
            raise UnsafeArchiveError(f"Archive contains a duplicate member path: {normalized}")
        if member.flag_bits & 0x1:
            raise UnsafeArchiveError(f"Encrypted archive member is unsupported: {normalized}")
        if _is_symlink(member):
            raise UnsafeArchiveError(f"Archive symlink is unsupported: {normalized}")
        if member.file_size > limits.maximum_member_bytes:
            raise UnsafeArchiveError(
                f"Archive member {normalized} declares {member.file_size} bytes; "
                f"limit is {limits.maximum_member_bytes}"
            )
        validated[collision_key] = member
    return validated


def _load_workbook_root(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    *,
    workbook_name: str,
) -> ElementTree.Element:
    twb_members = [member for member in members.values() if member.filename.casefold().endswith(".twb")]
    if len(twb_members) != 1:
        raise ValueError(f"{workbook_name} must contain exactly one .twb file; found {len(twb_members)}")
    document = archive.read(twb_members[0])
    prefix = document[:8192].upper()
    if b"<!DOCTYPE" in prefix or b"<!ENTITY" in prefix:
        raise ValueError(f"{workbook_name} contains a prohibited XML declaration")
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise ValueError(f"Invalid Tableau workbook XML in {workbook_name}: {error}") from error
    if _local_name(root.tag) != "workbook":
        raise ValueError(f"{workbook_name} does not have a workbook root element")
    return root


def _datasources(root: ElementTree.Element) -> list[ElementTree.Element]:
    container = next((child for child in root if _local_name(child.tag) == "datasources"), None)
    if container is None:
        return []
    return [
        datasource
        for datasource in container
        if _local_name(datasource.tag) == "datasource"
        and any(_local_name(element.tag) == "connection" for element in datasource.iter())
    ]


def _display_name(datasource: ElementTree.Element, position: int) -> str:
    caption = datasource.attrib.get("caption")
    internal_name = datasource.attrib.get("name")
    if caption:
        return caption
    if internal_name and not internal_name.casefold().startswith("federated."):
        return internal_name
    return f"Datasource {position}"


def _slug(value: str, *, maximum_length: int = 120) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    normalized = normalized or "tableau-datasource"
    if len(normalized) <= maximum_length:
        return normalized
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{normalized[: maximum_length - 9].rstrip('-')}-{digest}"


def _dependency_names(
    datasource: ElementTree.Element,
    members: dict[str, zipfile.ZipInfo],
) -> tuple[str, ...]:
    candidate_members = {
        _safe_member_name(member.filename).casefold(): _safe_member_name(member.filename)
        for member in members.values()
        if not member.is_dir() and Path(member.filename).suffix.casefold() in PACKAGED_DATA_SUFFIXES
    }
    references: set[str] = set()
    for element in datasource.iter():
        for raw_value in element.attrib.values():
            value = unquote(raw_value).replace("\\", "/").removeprefix("./")
            exact = candidate_members.get(value.casefold())
            if exact:
                references.add(exact)
                continue
            for member_key, member_name in candidate_members.items():
                if member_key in value.casefold():
                    references.add(member_name)

    connection_classes = {
        element.attrib.get("class", "").casefold()
        for element in datasource.iter()
        if _local_name(element.tag) == "connection"
    }
    if "hyper" in connection_classes and not any(Path(name).suffix.casefold() == ".hyper" for name in references):
        raise ValueError(
            f"Datasource {_display_name(datasource, 1)!r} has a Hyper connection but no packaged extract reference"
        )
    if "dataengine" in connection_classes and not any(
        Path(name).suffix.casefold() in {".hyper", ".tde"} for name in references
    ):
        raise ValueError(
            f"Datasource {_display_name(datasource, 1)!r} has an extract connection but no packaged extract reference"
        )
    return tuple(sorted(references, key=str.casefold))


def _write_member(
    source: zipfile.ZipFile,
    target: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    normalized_name: str,
) -> None:
    target_info = zipfile.ZipInfo(normalized_name, date_time=member.date_time)
    target_info.compress_type = zipfile.ZIP_DEFLATED
    target_info.external_attr = 0o600 << 16
    with source.open(member) as source_stream, target.open(target_info, "w") as target_stream:
        shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)


def _validate_tdsx(package_path: Path, *, created_at: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="tdsx-validation-") as temporary_directory:
        extracted = safely_extract_tdsx(package_path, Path(temporary_directory))
        tds_members = [member for member in extracted if member["kind"] == "TDS"]
        if len(tds_members) != 1:
            raise ValueError(f"{package_path.name} must contain exactly one .tds file")
        tds_path = Path(tds_members[0]["extracted_path"])
        inspected = inspect_tds(tds_path)
        parsed = parse_tableau_datasource(
            tds_path=tds_path,
            source_path=package_path.as_posix(),
            document_path=tds_members[0]["relative_path"],
            workflow_run_id="local-twbx-conversion-validation",
            package_hash=sha256_file(package_path),
            datasource_id=hashlib.sha256(package_path.name.encode("utf-8")).hexdigest(),
            created_at=created_at,
            inventory_hash="0" * 64,
        )
        if parsed["warnings"]:
            raise ValueError(f"{package_path.name} failed semantic validation: {parsed['warnings']}")
        return {
            "status": "PASS",
            "datasource_name": parsed["datasource_name"],
            "connection_classes": inspected["connection_classes"],
            "relation_count": len(parsed["relations"]),
            "relationship_count": len(parsed["relationships"]),
            "field_count": len(parsed["fields"]),
            "calculation_count": len(parsed["calculations"]),
            "parameter_count": len(parsed["parameters"]),
            "filter_count": len(parsed["filters"]),
            "embedded_extract_count": sum(
                member["kind"] in {"HYPER", "TDE"} for member in extracted
            ),
        }


def convert_twbx(
    workbook_path: str | Path,
    output_directory: str | Path,
    *,
    limits: DiscoveryLimits | None = None,
) -> list[ConvertedDatasource]:
    source_path = Path(workbook_path)
    destination = Path(output_directory)
    limits = limits or DiscoveryLimits()
    if source_path.suffix.casefold() != ".twbx":
        raise ValueError(f"Expected a .twbx file: {source_path}")
    if not zipfile.is_zipfile(source_path):
        raise UnsafeArchiveError(f"Tableau workbook is not a valid ZIP archive: {source_path.name}")
    destination.mkdir(parents=True, exist_ok=True)
    created_at = _utc_timestamp()
    converted: list[ConvertedDatasource] = []

    with zipfile.ZipFile(source_path) as source_archive:
        members = _validated_members(source_archive, limits=limits)
        workbook_root = _load_workbook_root(source_archive, members, workbook_name=source_path.name)
        datasources = _datasources(workbook_root)
        if not datasources:
            raise ValueError(f"{source_path.name} contains no connected datasources")

        used_names: set[str] = set()
        for position, datasource in enumerate(datasources, start=1):
            datasource_name = _display_name(datasource, position)
            base_name = _slug(f"{source_path.stem}--{datasource_name}")
            if base_name in used_names:
                suffix = hashlib.sha256(
                    ElementTree.tostring(datasource, encoding="utf-8")
                ).hexdigest()[:8]
                base_name = f"{base_name}-{suffix}"
            used_names.add(base_name)
            output_path = destination / f"{base_name}.tdsx"
            tds_name = f"{base_name}.tds"
            dependencies = _dependency_names(datasource, members)
            tds_document = ElementTree.tostring(
                datasource,
                encoding="utf-8",
                xml_declaration=True,
            )

            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as target_archive:
                target_archive.writestr(tds_name, tds_document)
                for dependency in dependencies:
                    source_member = members[dependency.casefold()]
                    _write_member(source_archive, target_archive, source_member, dependency)
            with zipfile.ZipFile(output_path) as validation_archive:
                corrupt_member = validation_archive.testzip()
                if corrupt_member:
                    raise ValueError(f"{output_path.name} contains corrupt member {corrupt_member}")
            validation = _validate_tdsx(output_path, created_at=created_at)
            converted.append(
                ConvertedDatasource(
                    workbook_path=source_path,
                    datasource_name=datasource_name,
                    output_path=output_path,
                    dependencies=dependencies,
                    validation=validation,
                )
            )
    return converted


def convert_twbx_directory(
    input_directory: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    source_root = Path(input_directory).resolve()
    output_root = Path(output_directory).resolve()
    if not source_root.is_dir():
        raise NotADirectoryError(f"Input directory does not exist: {source_root}")
    if source_root == output_root or source_root in output_root.parents:
        raise ValueError("Output directory must not be inside the input directory")
    workbooks = sorted(source_root.rglob("*.twbx"), key=lambda path: path.relative_to(source_root).as_posix().casefold())
    if not workbooks:
        raise ValueError(f"No .twbx files found beneath {source_root}")

    temporary_root = output_root.with_name(f".{output_root.name}.tmp")
    shutil.rmtree(temporary_root, ignore_errors=True)
    temporary_datasources = temporary_root / "datasources"
    temporary_datasources.mkdir(parents=True)
    converted: list[ConvertedDatasource] = []
    try:
        for workbook in workbooks:
            converted.extend(convert_twbx(workbook, temporary_datasources))
        created_at = _utc_timestamp()
        datasource_records = []
        for item in converted:
            record = item.as_dict()
            record["output_path"] = (output_root / "datasources" / item.output_path.name).as_posix()
            datasource_records.append(record)
        manifest = {
            "schema_version": "1.0",
            "status": "PASS",
            "created_at": created_at,
            "input_directory": source_root.as_posix(),
            "output_directory": output_root.as_posix(),
            "summary": {
                "workbook_count": len(workbooks),
                "datasource_count": len(converted),
                "validated_count": sum(item.validation["status"] == "PASS" for item in converted),
                "embedded_extract_count": sum(
                    item.validation["embedded_extract_count"] for item in converted
                ),
            },
            "datasources": datasource_records,
        }
        (temporary_root / "conversion-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if output_root.exists():
            shutil.rmtree(output_root)
        temporary_root.replace(output_root)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise
    return manifest


def upload_tdsx_files(
    local_directory: str | Path,
    *,
    volume_root: str,
    profile: str,
) -> dict[str, Any]:
    normalized_root = volume_root.rstrip("/")
    if not normalized_root.startswith("/Volumes/"):
        raise ValueError("volume_root must be an absolute Unity Catalog Volume path")
    remote_directory = (
        normalized_root if normalized_root.endswith("/datasources") else f"{normalized_root}/datasources"
    )
    remote_uri = f"dbfs:{remote_directory}"
    source_root = Path(local_directory)
    files = sorted(source_root.glob("*.tdsx"), key=lambda path: path.name.casefold())
    if not files:
        raise ValueError(f"No validated .tdsx files found in {source_root}")

    _run_databricks_cli(["fs", "mkdir", remote_uri, "--profile", profile])
    uploaded = []
    for path in files:
        target_uri = f"{remote_uri}/{path.name}"
        _run_databricks_cli(
            [
                "fs",
                "cp",
                path.as_posix(),
                target_uri,
                "--overwrite",
                "--profile",
                profile,
            ]
        )
        uploaded.append(f"{remote_directory}/{path.name}")
    return {
        "status": "UPLOADED",
        "profile": profile,
        "destination": remote_directory,
        "uploaded_count": len(uploaded),
        "uploaded_files": uploaded,
    }


def _run_databricks_cli(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["databricks", *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise RuntimeError(f"Databricks CLI command failed: {detail}") from error
