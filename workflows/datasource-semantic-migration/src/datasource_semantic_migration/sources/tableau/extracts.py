"""Load Tableau .hyper extracts as Parquet, for number checks.

The extract is copied out of its package to the task's temporary disk (Hyper needs an ordinary local
file), and Hyper's own COPY writes each table to Parquet, so no rows pass through Python. Proven on
serverless compute by scripts/hyper_serverless_check.py.
"""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path
from typing import Any


def extract_key(package_sha256: str, member_path: str | None) -> str:
    """Stable cache key for one extract: the same file in the same package is loaded once."""
    return hashlib.sha256(f"{package_sha256}\0{member_path or ''}".encode("utf-8")).hexdigest()[:16]


def datasource_extracts(inventory: dict[str, Any], datasource_ir: dict[str, Any]) -> list[dict[str, Any]]:
    """The extracts a datasource uses, located in the uploaded packages."""
    found = []
    for asset in inventory.get("assets", []):
        if asset.get("source_path") != datasource_ir.get("source_path"):
            continue
        document = next(
            (
                item
                for item in asset.get("tds_documents", [])
                if item.get("document_path", asset.get("relative_path")) == datasource_ir.get("document_path")
            ),
            None,
        )
        members = {item["relative_path"]: item for item in asset.get("embedded_extracts", [])}
        names = (document or {}).get("extracts") or list(members)
        for name in names:
            if name in members and name.casefold().endswith(".hyper"):
                found.append(
                    {
                        "package_path": asset["source_path"],
                        "package_sha256": asset["sha256"],
                        "member_path": name,
                        "byte_size": members[name].get("byte_size"),
                        "key": extract_key(asset["sha256"], name),
                    }
                )
    return found


def copy_extract(package_path: str, member_path: str, destination: Path) -> int:
    """Copy one extract out of a .tdsx/.twbx in chunks, without unzipping anything else."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path) as archive, archive.open(member_path) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target, length=8 * 1024 * 1024)
    return destination.stat().st_size


def export_parquet(hyper_file: Path, output_directory: Path, work_directory: Path) -> list[dict[str, Any]]:
    """Each table of a local .hyper file written to Parquet in output_directory, with its columns and rows."""
    from tableauhyperapi import Connection, CreateMode, HyperProcess, Telemetry

    output_directory.mkdir(parents=True, exist_ok=True)
    tables = []
    parameters = {"log_dir": str(work_directory)}
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters=parameters) as hyper:
        with Connection(hyper.endpoint, str(hyper_file), CreateMode.NONE) as connection:
            names = [
                table
                for schema in connection.catalog.get_schema_names()
                for table in connection.catalog.get_table_names(schema)
            ]
            for position, table in enumerate(names):
                definition = connection.catalog.get_table_definition(table)
                local_parquet = work_directory / f"table_{position}.parquet"
                # TableName renders as a quoted, qualified SQL name.
                connection.execute_command(f"COPY {table} TO '{local_parquet}' WITH (FORMAT PARQUET)")
                target = output_directory / local_parquet.name
                shutil.copyfile(local_parquet, target)
                tables.append(
                    {
                        "table": f"{table.schema_name.name.unescaped}.{table.name.unescaped}",
                        "columns": [str(column.name.unescaped) for column in definition.columns],
                        "rows": connection.execute_scalar_query(f"SELECT COUNT(*) FROM {table}"),
                        "parquet_path": target.as_posix(),
                    }
                )
    return tables


def main_table(tables: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The table Tableau queries: the single table, else the one named Extract, else the largest."""
    if not tables:
        return None
    if len(tables) == 1:
        return tables[0]
    named = [item for item in tables if item["table"].split(".")[-1].casefold() == "extract"]
    return named[0] if named else max(tables, key=lambda item: item["rows"])
