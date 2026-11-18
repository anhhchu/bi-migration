from __future__ import annotations

import hashlib
import re
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


def _relation_name(relation: ElementTree.Element) -> str:
    return relation.attrib.get("table") or relation.attrib.get("name") or ""


def _expression_text(node: ElementTree.Element) -> str:
    value = (
        node.attrib.get("value")
        or node.attrib.get("name")
        or (node.attrib.get("op") if not list(node) else "")
        or (node.text or "").strip()
    )
    children = [_expression_text(child) for child in node if _local_name(child.tag) == "expression"]
    children = [child for child in children if child]
    operator = node.attrib.get("op", "")
    if children and operator:
        return f"({f' {operator} '.join(children)})"
    if children:
        return " ".join(children)
    return value


def _relationships(datasource: ElementTree.Element) -> list[dict]:
    relationships = []
    for relation in (node for node in datasource.iter() if _local_name(node.tag) == "relation"):
        if relation.attrib.get("type") != "join":
            continue
        sides = [child for child in relation if _local_name(child.tag) == "relation"]
        if len(sides) < 2:
            continue
        clause = next((child for child in relation if _local_name(child.tag) == "clause"), None)
        expression = next(
            (child for child in clause.iter() if _local_name(child.tag) == "expression"),
            None,
        ) if clause is not None else None
        condition = _expression_text(expression) if expression is not None else ""
        referenced_tables = []
        for table in re.findall(r"\[([^\]]+)\]\.\[[^\]]+\]", condition):
            if table not in referenced_tables:
                referenced_tables.append(table)
        left_table = _relation_name(sides[0]).strip("[]")
        right_table = _relation_name(sides[1]).strip("[]")
        if len(referenced_tables) >= 2:
            left_table, right_table = referenced_tables[:2]
        relationships.append(
            {
                "left_table": left_table,
                "right_table": right_table,
                "join_type": relation.attrib.get("join", "inner").lower(),
                "condition": condition,
                "source_kind": "physical_join",
            }
        )

    for relationship in (node for node in datasource.iter() if _local_name(node.tag) == "relationship"):
        tables = [
            value.strip("[]")
            for node in relationship.iter()
            if _local_name(node.tag) in {"relation", "table"}
            and (value := _relation_name(node))
        ]
        if len(tables) < 2:
            continue
        expression = next(
            (node for node in relationship.iter() if _local_name(node.tag) == "expression"),
            None,
        )
        candidate = {
            "left_table": tables[0],
            "right_table": tables[1],
            "join_type": relationship.attrib.get("join", "relationship").lower(),
            "condition": _expression_text(expression) if expression is not None else "",
            "source_kind": "logical_relationship",
        }
        if candidate not in relationships:
            relationships.append(candidate)
    return relationships


def _datasource(datasource: ElementTree.Element) -> dict:
    datasource_id = datasource.attrib.get("name") or datasource.attrib.get("caption") or "unknown"
    physical_fields = []
    seen_physical = set()
    for record in (
        node
        for node in datasource.iter()
        if _local_name(node.tag) == "metadata-record" and node.attrib.get("class") == "column"
    ):
        metadata = {_local_name(node.tag): (node.text or "").strip() for node in record}
        local_name = metadata.get("local-name", "")
        remote_name = metadata.get("remote-name", "")
        source_table = metadata.get("parent-name", "").strip("[]")
        key = (local_name or remote_name, source_table)
        if not (local_name or remote_name) or key in seen_physical:
            continue
        seen_physical.add(key)
        physical_fields.append(
            {
                "name": local_name or f"[{remote_name}]",
                "caption": remote_name or local_name.strip("[]"),
                "datatype": metadata.get("local-type", metadata.get("remote-type", "")),
                "role": "",
                "type": "physical",
                "calculation": None,
                "source_table": source_table,
            }
        )

    column_fields = []
    for column in (node for node in datasource.iter() if _local_name(node.tag) == "column"):
        calculation = next(
            (node for node in column if _local_name(node.tag) == "calculation"),
            None,
        )
        if physical_fields and calculation is None:
            continue
        column_fields.append(
            {
                "name": column.attrib.get("name", ""),
                "caption": column.attrib.get("caption", ""),
                "datatype": column.attrib.get("datatype", ""),
                "role": column.attrib.get("role", ""),
                "type": column.attrib.get("type", ""),
                "calculation": calculation.attrib.get("formula") if calculation is not None else None,
                "source_table": "",
                "workbook_object": calculation is not None and not calculation.attrib.get("formula"),
                "source_kind": "calculation",
            }
        )
    fields_by_table: dict[str, list[dict]] = {}
    for field in physical_fields:
        fields_by_table.setdefault(field["source_table"], []).append(field)
    for source_table, table_fields in fields_by_table.items():
        normalized_table = source_table.lower()
        names = {field["caption"].lower() for field in table_fields}
        if normalized_table == "extract":
            source_kind = "extract_replica"
        elif normalized_table == "menu":
            source_kind = "dashboard_object"
        elif normalized_table.startswith("clipboard_"):
            source_kind = "workbook_helper"
        elif normalized_table == "sheet1" and "dashboard" in names and any(
            name.endswith(" value") for name in names
        ):
            source_kind = "dashboard_object"
        else:
            source_kind = "business_source"
        for field in table_fields:
            field["source_kind"] = source_kind
    fields = [*physical_fields, *column_fields]
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
        "relationships": _relationships(datasource),
        "fields": fields,
        "fingerprint": hashlib.sha256(fingerprint_source.encode()).hexdigest()[:16],
    }


def parse_tableau(path: str | Path) -> dict:
    source_path = Path(path)
    xml_bytes, packaged_workbook = _read_workbook(source_path)
    root = ElementTree.fromstring(xml_bytes)
    datasource_container = next(
        (node for node in root if _local_name(node.tag) == "datasources"),
        None,
    )
    datasource_nodes = (
        [node for node in datasource_container if _local_name(node.tag) == "datasource"]
        if datasource_container is not None
        else list(_nodes(root, "datasource"))
    )
    datasources = [_datasource(node) for node in datasource_nodes]

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
