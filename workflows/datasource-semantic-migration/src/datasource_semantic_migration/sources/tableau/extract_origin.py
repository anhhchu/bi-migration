"""Where a Tableau datasource's data comes from, decided from its definition's connections."""

from __future__ import annotations

import re
from typing import Any

EXTRACT_CLASSES = {"hyper", "dataengine"}
# Connection types that are containers, not data sources.
WRAPPER_CLASSES = {"federated", ""}
CONNECTION_LABELS = {
    "textscan": "text file",
    "excel-direct": "Excel file",
    "sqlserver": "SQL Server",
    "postgres": "PostgreSQL",
    "snowflake": "Snowflake",
    "databricks": "Databricks",
    "bigquery": "BigQuery",
    "redshift": "Redshift",
    "oracle": "Oracle",
    "mysql": "MySQL",
    "teradata": "Teradata",
}


def _file_name(value: str | None) -> str:
    return re.split(r"[\\/]", value or "")[-1]


def connection_source(connection: dict[str, Any]) -> str:
    """Short readable description of a connection, for example "text file Finance Data.csv"."""
    attributes = connection.get("attributes") or {}
    kind = str(connection.get("class") or "")
    label = CONNECTION_LABELS.get(kind, kind or "connection")
    detail = (
        _file_name(attributes.get("filename"))
        or "/".join(part for part in (attributes.get("server"), attributes.get("dbname")) if part)
        or connection.get("caption")
        or ""
    )
    if kind in EXTRACT_CLASSES:
        detail = _file_name(attributes.get("dbname")) or detail
    return f"{label} {detail}".strip()


def source_identity(connection: dict[str, Any] | None, relation_table: str | None) -> str:
    """What physical data a relation reads. Paths are reduced to file names because they are the
    author's local paths, which differ between authors for the same file."""
    connection = connection or {}
    attributes = connection.get("attributes") or {}
    dbname = attributes.get("dbname") or ""
    if "/" in dbname or "\\" in dbname or dbname.casefold().endswith((".hyper", ".tde")):
        dbname = _file_name(dbname)
    parts = (
        connection.get("class") or "",
        attributes.get("server") or "",
        dbname,
        attributes.get("schema") or "",
        _file_name(attributes.get("filename")),
        relation_table or "",
    )
    return "|".join(part.casefold() for part in parts)


def relation_connections(datasource_ir: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Each relation with the connection it reads from."""
    by_name = {item.get("name"): item for item in datasource_ir.get("connections", []) if item.get("name")}
    return [(relation, by_name.get(relation.get("connection"))) for relation in datasource_ir.get("relations", [])]


def extract_origin(datasource_ir: dict[str, Any], extract_files: list[str]) -> dict[str, Any]:
    """How the datasource's data was produced, and whether the upload includes its extract.

    TABLEAU_EXTRACT: an extract next to the original connection the tables read (made by Tableau).
    EXTRACT_IS_SOURCE: the tables read the extract itself (built outside Tableau, for example by Alteryx).
    LIVE: no extract; numbers cannot be compared with Tableau.
    """
    connections = datasource_ir.get("connections", [])
    has_extract = any(str(item.get("class") or "").casefold() in EXTRACT_CLASSES for item in connections)
    read_connections = [connection for _, connection in relation_connections(datasource_ir) if connection]
    originals = [
        item for item in read_connections if str(item.get("class") or "").casefold() not in EXTRACT_CLASSES | WRAPPER_CLASSES
    ]
    sources = sorted({connection_source(item) for item in originals})
    in_upload = bool(extract_files)
    if not has_extract:
        kind = "LIVE"
        label = f"Live connection to {', '.join(sources) or 'its source'}; no extract, numbers can't be compared"
    elif originals:
        kind = "TABLEAU_EXTRACT"
        label = f"Tableau extract of {', '.join(sources)}"
    else:
        kind = "EXTRACT_IS_SOURCE"
        label = "Extract is the source (built outside Tableau)"
    if has_extract:
        label += "; extract included" if in_upload else "; extract not in this upload, numbers can't be compared"
    return {"kind": kind, "label": label, "original_sources": sources, "extract_in_upload": in_upload}
