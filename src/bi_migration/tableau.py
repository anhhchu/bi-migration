from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _nodes(root: ElementTree.Element, name: str):
    return (node for node in root.iter() if _local_name(node.tag) == name)


def _read_workbook(path: Path) -> tuple[bytes, str]:
    if path.suffix.lower() == ".twb":
        return path.read_bytes(), path.name
    if path.suffix.lower() != ".twbx":
        raise ValueError(f"Unsupported Tableau file: {path}")
    with zipfile.ZipFile(path) as package:
        workbook_names = sorted(name for name in package.namelist() if name.lower().endswith(".twb"))
        if not workbook_names:
            raise ValueError(f"No .twb workbook found in {path}")
        workbook_name = workbook_names[0]
        return package.read(workbook_name), workbook_name


def _connection(connection: ElementTree.Element) -> dict:
    keys = ("class", "server", "dbname", "schema", "port", "authentication")
    return {key: connection.attrib[key] for key in keys if connection.attrib.get(key)}


def _datasource(datasource: ElementTree.Element) -> dict:
    datasource_id = datasource.attrib.get("name") or datasource.attrib.get("caption") or "unknown"
    fields = []
    for column in (node for node in datasource.iter() if _local_name(node.tag) == "column"):
        calculation = next(
            (node for node in column if _local_name(node.tag) == "calculation"),
            None,
        )
        fields.append(
            {
                "name": column.attrib.get("name", ""),
                "caption": column.attrib.get("caption", ""),
                "datatype": column.attrib.get("datatype", ""),
                "role": column.attrib.get("role", ""),
                "type": column.attrib.get("type", ""),
                "calculation": calculation.attrib.get("formula") if calculation is not None else None,
            }
        )
    connections = [_connection(node) for node in datasource.iter() if _local_name(node.tag) == "connection"]
    tables = sorted(
        {
            node.attrib.get("table") or node.attrib.get("name")
            for node in datasource.iter()
            if _local_name(node.tag) == "relation" and (node.attrib.get("table") or node.attrib.get("name"))
        }
    )
    fingerprint_source = "|".join(
        [datasource_id, *tables, *(str(sorted(item.items())) for item in connections)]
    )
    return {
        "id": datasource_id,
        "caption": datasource.attrib.get("caption", datasource_id),
        "connections": connections,
        "tables": tables,
        "fields": fields,
        "fingerprint": hashlib.sha256(fingerprint_source.encode()).hexdigest()[:16],
    }


def parse_tableau(path: str | Path) -> dict:
    source_path = Path(path)
    xml_bytes, packaged_workbook = _read_workbook(source_path)
    root = ElementTree.fromstring(xml_bytes)
    datasources = [_datasource(node) for node in _nodes(root, "datasource")]

    worksheets = []
    for worksheet in _nodes(root, "worksheet"):
        datasource_ids = sorted(
            {
                node.attrib["datasource"]
                for node in worksheet.iter()
                if _local_name(node.tag) == "datasource-dependencies" and node.attrib.get("datasource")
            }
        )
        worksheets.append({"name": worksheet.attrib.get("name", "unknown"), "datasources": datasource_ids})

    worksheet_names = {item["name"] for item in worksheets}
    dashboards = []
    for dashboard in _nodes(root, "dashboard"):
        referenced = sorted(
            {
                value
                for node in dashboard.iter()
                for key, value in node.attrib.items()
                if key in {"name", "worksheet"} and value in worksheet_names
            }
        )
        dashboards.append({"name": dashboard.attrib.get("name", "unknown"), "worksheets": referenced})

    return {
        "asset_id": source_path.stem,
        "platform": "tableau",
        "source_file": str(source_path),
        "packaged_workbook": packaged_workbook,
        "dashboards": dashboards,
        "worksheets": worksheets,
        "datasources": datasources,
    }


def find_tableau_files(input_path: str | Path) -> list[Path]:
    path = Path(input_path)
    if path.is_file():
        return [path]
    return sorted(item for item in path.rglob("*") if item.suffix.lower() in {".twb", ".twbx"})
