"""Read a Tableau → Databricks table mapping written in any reasonable shape.

The workflow only needs, for each Tableau table, the Databricks table that replaces it.
Users can write that as YAML, JSON, or CSV, with flexible key or column names, in one or
several files. Everything is normalized to one internal document:

    {"version": "1.0", "table_mappings": [{"source": {...}, "target": {...}}], "relationships": [...]}

Accepted shapes include:

* the full format: ``table_mappings: [{source: {table: ...}, target: {table: ...}}]``
* a list of flat rows: ``[{source_table: Orders, target_table: main.sales.orders}]``
* a simple map: ``{Orders: main.sales.orders}``
* a CSV with columns such as ``source_table,target_table`` (header names are flexible)
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import yaml

MAPPING_SUFFIXES = {".yaml", ".yml", ".json", ".csv"}

# Accepted names for each field in flat rows and CSV headers (compared after normalizing).
SOURCE_TABLE_KEYS = ("source_table", "tableau_table", "source", "from", "from_table", "tableau", "table")
TARGET_TABLE_KEYS = ("target_table", "databricks_table", "target", "to", "to_table", "databricks", "uc_table")
SOURCE_FIELD_KEYS = {
    "datasource": ("datasource", "source_datasource", "tableau_datasource", "data_source"),
    "grain": ("source_grain",),
    "business_domain": ("business_domain", "domain"),
    "display_name": ("display_name",),
}
TARGET_FIELD_KEYS = {
    "grain": ("target_grain", "grain"),
    "business_keys": ("business_keys", "keys", "target_keys", "primary_keys"),
    "event_date": ("event_date", "date_column"),
    "temporal_model": ("temporal_model",),
}
SUPPORTED_VERSIONS = {"1", "1.0"}


class TableMappingError(ValueError):
    """The mapping could not be read; the message says what to fix."""


def _key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().casefold()).strip("_")


def _first(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _keys_list(value: Any) -> list[str] | None:
    if value in (None, ""):
        return None
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in re.split(r"[;|,]", str(value)) if item.strip()]


def _table_name(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("table") or value.get("name")
    text = str(value).strip() if value not in (None, "") else ""
    return text or None


def _entry_from_row(row: dict[str, Any], where: str) -> dict[str, Any]:
    """One mapping entry from either the full shape or a flat row."""
    if isinstance(row.get("source"), dict) or isinstance(row.get("target"), dict):
        source = dict(row.get("source") or {}) if isinstance(row.get("source"), dict) else {"table": row.get("source")}
        target = dict(row.get("target") or {}) if isinstance(row.get("target"), dict) else {"table": row.get("target")}
        entry = {key: value for key, value in row.items() if key not in {"source", "target"}}
    else:
        flat = {_key(name): value for name, value in row.items()}
        source = {"table": _first(flat, SOURCE_TABLE_KEYS)}
        target = {"table": _first(flat, TARGET_TABLE_KEYS)}
        for field, names in SOURCE_FIELD_KEYS.items():
            if (value := _first(flat, names)) is not None:
                source[field] = str(value).strip()
        for field, names in TARGET_FIELD_KEYS.items():
            if (value := _first(flat, names)) is not None:
                target[field] = _keys_list(value) if field == "business_keys" else str(value).strip()
        entry = {}
    source["table"] = _table_name(source.get("table"))
    target["table"] = _table_name(target.get("table"))
    if not source["table"] or not target["table"]:
        missing = "Tableau (source) table" if not source["table"] else "Databricks (target) table"
        raise TableMappingError(f"{where}: missing the {missing}. Each row needs both a source and a target table.")
    if target["table"].count(".") != 2:
        raise TableMappingError(
            f"{where}: target '{target['table']}' must be a full Databricks name, catalog.schema.table."
        )
    entry.update({"source": source, "target": target})
    return entry


def _rows_from_document(document: Any, label: str) -> tuple[list[tuple[dict[str, Any], str]], list[Any]]:
    """Mapping rows (with a location label) and any relationships from a parsed YAML/JSON document."""
    relationships: list[Any] = []
    if isinstance(document, dict):
        version = document.get("version")
        if version is not None and str(version).strip() not in SUPPORTED_VERSIONS:
            raise TableMappingError(f"{label}: unsupported mapping version '{version}'; this workflow reads version 1.")
        relationships = list(document.get("relationships") or [])
        rows = next(
            (document[key] for key in ("table_mappings", "mappings", "tables") if isinstance(document.get(key), list)),
            None,
        )
        if rows is None:
            simple = {
                key: value
                for key, value in document.items()
                if key not in {"version", "relationships"} and isinstance(value, (str, dict))
            }
            return [({"source": {"table": key}, "target": value if isinstance(value, dict) else {"table": value}},
                     f"{label}, '{key}'") for key, value in simple.items()], relationships
    elif isinstance(document, list):
        rows = document
    else:
        raise TableMappingError(f"{label}: no mappings found.")
    return [(row, f"{label}, entry {index}") for index, row in enumerate(rows, start=1) if isinstance(row, dict)], relationships


def read_mapping_text(text: str, *, suffix: str, label: str) -> dict[str, Any]:
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
        rows = [({name: value for name, value in row.items() if name}, f"{label}, row {index}")
                for index, row in enumerate(reader, start=2)
                if any((value or "").strip() for value in row.values())]
        relationships: list[Any] = []
    else:
        try:
            document = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
        except (json.JSONDecodeError, yaml.YAMLError) as error:
            raise TableMappingError(f"{label}: not valid {suffix.lstrip('.').upper()} ({error}).") from error
        rows, relationships = _rows_from_document(document or {}, label)
    entries = [_entry_from_row(row, where) for row, where in rows]
    return {"version": "1.0", "table_mappings": entries, "relationships": relationships}


def load_table_mapping(paths: str | Path | list[str | Path]) -> dict[str, Any]:
    """Load and merge one or more mapping files into the internal mapping document."""
    path_list = [Path(path) for path in (paths if isinstance(paths, list) else [paths])]
    merged: dict[str, Any] = {"version": "1.0", "table_mappings": [], "relationships": []}
    for path in path_list:
        if not path.is_file():
            raise FileNotFoundError(f"Table mapping does not exist: {path}")
        suffix = path.suffix.casefold()
        if suffix not in MAPPING_SUFFIXES:
            raise TableMappingError(f"{path.name}: use a .yaml, .yml, .json, or .csv file.")
        document = read_mapping_text(path.read_text(encoding="utf-8"), suffix=suffix, label=path.name)
        merged["table_mappings"].extend(document["table_mappings"])
        merged["relationships"].extend(document["relationships"])
    if not merged["table_mappings"]:
        raise TableMappingError(
            "No table mappings found. Each entry needs a Tableau source table and a Databricks target table, e.g. "
            "'source_table,target_table' in CSV or 'Orders: main.sales.orders' in YAML."
        )
    return merged
