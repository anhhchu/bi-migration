from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import yaml


FIELD_ALIASES = {
    "datasource": {"datasource", "source datasource", "source_datasource"},
    "legacy": {"legacy", "source field", "source_field", "legacy field", "legacy_field"},
    "source_table": {"source table", "source_table", "legacy table", "legacy_table"},
    "source_grain": {"source grain", "source_grain", "legacy grain", "legacy_grain"},
    "target_table": {"target table", "target_table"},
    "target_expression": {"target expression", "target_expression", "target field", "target_field"},
    "target_grain": {"target grain", "target_grain"},
    "conversion": {"conversion", "transformation", "rule"},
    "status": {"status", "approval status", "approval_status"},
    "notes": {"notes", "description", "comments"},
}


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower().replace("-", " "))


def _canonical_key(value: str) -> str | None:
    normalized = _normalize_header(value)
    return next((key for key, aliases in FIELD_ALIASES.items() if normalized in aliases), None)


def _normalize_row(row: dict, source: Path, locator: str) -> dict | None:
    if row.get("evidence_type") == "relationship":
        normalized = {
            key: value
            for key, value in row.items()
            if key in {
                "evidence_type", "source_table", "source_key", "as_of",
                "target_left_table", "target_right_table", "target_key",
                "join_type", "cardinality", "temporal_mode",
            } and value not in (None, "")
        }
        normalized["provenance"] = {"file": str(source), "locator": locator}
        return normalized
    normalized = {}
    for key, value in row.items():
        canonical = _canonical_key(str(key))
        if canonical and value is not None and str(value).strip():
            normalized[canonical] = str(value).strip()
    if not normalized.get("legacy"):
        return None
    normalized["provenance"] = {"file": str(source), "locator": locator}
    return normalized


def _tabular_rows(path: Path) -> list[tuple[str, dict]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [(f"row:{number}", row) for number, row in enumerate(csv.DictReader(handle), start=2)]
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return []
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows = []
    for number, line in enumerate(lines[2:], start=3):
        values = [cell.strip() for cell in line.strip("|").split("|")]
        if len(values) == len(headers):
            rows.append((f"line:{number}", dict(zip(headers, values))))
    return rows


def _structured_rows(path: Path) -> list[tuple[str, dict]]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if isinstance(value, dict) and isinstance(value.get("dataset_mappings"), list):
        rows = []
        anchor_targets = {}
        for dataset in value["dataset_mappings"]:
            if not isinstance(dataset, dict) or dataset.get("relationship"):
                continue
            source = dataset.get("source", {}) if isinstance(dataset.get("source"), dict) else {}
            target = dataset.get("target", {}) if isinstance(dataset.get("target"), dict) else {}
            if source.get("table") and target.get("table"):
                anchor_targets.setdefault(source["table"], target["table"])
        for dataset_number, dataset in enumerate(value["dataset_mappings"], start=1):
            if not isinstance(dataset, dict):
                continue
            source = dataset.get("source", {}) if isinstance(dataset.get("source"), dict) else {}
            target = dataset.get("target", {}) if isinstance(dataset.get("target"), dict) else {}
            relationship = dataset.get("relationship", {}) if isinstance(dataset.get("relationship"), dict) else {}
            if relationship and source.get("table") and target.get("table"):
                rows.append(
                    (
                        f"dataset:{dataset_number}:relationship",
                        {
                            "evidence_type": "relationship",
                            "source_table": source.get("table"),
                            "source_key": relationship.get("source_key"),
                            "as_of": relationship.get("as_of"),
                            "target_left_table": relationship.get("target_left_table") or anchor_targets.get(source.get("table")),
                            "target_right_table": target.get("table"),
                            "target_key": relationship.get("target_key"),
                            "join_type": relationship.get("join_type", "left"),
                            "cardinality": relationship.get("cardinality", "many_to_one"),
                            "temporal_mode": target.get("temporal_mode"),
                        },
                    )
                )
            columns = dataset.get("columns", []) if isinstance(dataset.get("columns"), list) else []
            for column_number, column in enumerate(columns, start=1):
                if not isinstance(column, dict):
                    continue
                rows.append(
                    (
                        f"dataset:{dataset_number}:column:{column_number}",
                        {
                            "source_table": source.get("table"),
                            "source_grain": source.get("grain"),
                            "legacy": column.get("source_column"),
                            "target_table": target.get("table"),
                            "target_grain": target.get("grain"),
                            "target_expression": column.get("target_expression") or column.get("target_column"),
                            "conversion": column.get("conversion"),
                            "notes": column.get("notes"),
                        },
                    )
                )
        return rows
    if isinstance(value, dict):
        value = value.get("mappings", value.get("fields", [value]))
    if not isinstance(value, list):
        raise ValueError("Mapping document must contain a list or a mappings/fields list")
    return [(f"item:{number}", row) for number, row in enumerate(value, start=1) if isinstance(row, dict)]


def load_mapping_documents(input_path: str | Path | None) -> tuple[list[dict], list[dict]]:
    if not input_path:
        return [], []
    root = Path(input_path)
    paths = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
    evidence = []
    errors = []
    for path in paths:
        if path.suffix.lower() not in {".csv", ".json", ".yaml", ".yml", ".md"}:
            continue
        try:
            rows = _tabular_rows(path) if path.suffix.lower() in {".csv", ".md"} else _structured_rows(path)
            evidence.extend(
                item
                for locator, row in rows
                if (item := _normalize_row(row, path, locator)) is not None
            )
        except (OSError, ValueError, TypeError, yaml.YAMLError, json.JSONDecodeError) as error:
            errors.append({"file": str(path), "error": str(error), "status": "quarantined"})
    return evidence, errors
