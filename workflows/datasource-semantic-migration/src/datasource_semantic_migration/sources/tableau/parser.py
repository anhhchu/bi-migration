from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ... import __version__
from ...artifacts import sha256_file, write_json_artifact
from .discovery import DiscoveryLimits


SENSITIVE_ATTRIBUTE_PARTS = ("password", "secret", "token", "credential")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _is_relation(element: ElementTree.Element) -> bool:
    name = _local_name(element.tag)
    return name == "relation" or name.endswith("...relation")


def _children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in element if _local_name(child.tag) == name]


def _first_descendant(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((child for child in element.iter() if _local_name(child.tag) == name), None)


def _clean_tableau_name(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) >= 2 and value.startswith("[") and value.endswith("]"):
        return value[1:-1]
    return value


def _safe_attributes(attributes: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in sorted(attributes.items())
        if not any(part in key.casefold() for part in SENSITIVE_ATTRIBUTE_PARTS) and value != ""
    }


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.casefold()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _expression(element: ElementTree.Element | None) -> dict[str, Any] | None:
    if element is None:
        return None
    result: dict[str, Any] = {"operator": element.attrib.get("op")}
    attributes = {key: value for key, value in _safe_attributes(element.attrib).items() if key != "op"}
    if attributes:
        result["attributes"] = attributes
    text = (element.text or "").strip()
    if text:
        result["value"] = text
    children = [_expression(child) for child in element if _local_name(child.tag) == "expression"]
    if children:
        result["children"] = children
    return result


def _relation_columns(element: ElementTree.Element) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    for container in _children(element, "columns"):
        for column in _children(container, "column"):
            columns.append(
                {
                    "name": column.attrib.get("name"),
                    "datatype": column.attrib.get("datatype"),
                    "ordinal": _parse_int(column.attrib.get("ordinal")),
                    "attributes": {
                        key: value
                        for key, value in _safe_attributes(column.attrib).items()
                        if key not in {"name", "datatype", "ordinal"}
                    },
                }
            )
    return columns


def _parse_relation_tree(
    element: ElementTree.Element,
    *,
    root_id: str,
    parent_relation_id: str | None,
    relations: list[dict[str, Any]],
) -> str:
    relation_id = root_id if parent_relation_id is None else f"{root_id}:{len(relations) + 1}"
    relation_type = element.attrib.get("type", "unknown")
    direct_relation_children = [child for child in element if _is_relation(child)]
    clause_expressions = []
    for clause in _children(element, "clause"):
        expression = _first_descendant(clause, "expression")
        clause_expressions.append(
            {
                "type": clause.attrib.get("type"),
                "expression": _expression(expression),
            }
        )
    relation = {
        "relation_id": relation_id,
        "parent_relation_id": parent_relation_id,
        "relation_type": relation_type,
        "name": element.attrib.get("name"),
        "table": element.attrib.get("table"),
        "connection": element.attrib.get("connection"),
        "join_type": element.attrib.get("join"),
        "attributes": {
            key: value
            for key, value in _safe_attributes(element.attrib).items()
            if key not in {"type", "name", "table", "connection", "join"}
        },
        "columns": _relation_columns(element),
        "clauses": clause_expressions,
        "children": [],
    }
    relation_text = (element.text or "").strip()
    if relation_text:
        relation["custom_sql"] = relation_text
    relations.append(relation)
    for child in direct_relation_children:
        child_id = _parse_relation_tree(
            child,
            root_id=root_id,
            parent_relation_id=relation_id,
            relations=relations,
        )
        relation["children"].append(child_id)
    return relation_id


def _parse_connections(root: ElementTree.Element) -> list[dict[str, Any]]:
    connections: list[dict[str, Any]] = []
    named_elements: set[int] = set()
    for named_connection in (element for element in root.iter() if _local_name(element.tag) == "named-connection"):
        connection = next((child for child in named_connection if _local_name(child.tag) == "connection"), None)
        if connection is None:
            continue
        named_elements.add(id(connection))
        connections.append(
            {
                "connection_id": named_connection.attrib.get("name") or f"connection-{len(connections) + 1}",
                "name": named_connection.attrib.get("name"),
                "caption": named_connection.attrib.get("caption"),
                "class": connection.attrib.get("class"),
                "attributes": {
                    key: value
                    for key, value in _safe_attributes(connection.attrib).items()
                    if key != "class"
                },
            }
        )
    for connection in (element for element in root.iter() if _local_name(element.tag) == "connection"):
        if id(connection) in named_elements:
            continue
        connections.append(
            {
                "connection_id": f"connection-{len(connections) + 1}",
                "name": None,
                "caption": None,
                "class": connection.attrib.get("class"),
                "attributes": {
                    key: value
                    for key, value in _safe_attributes(connection.attrib).items()
                    if key != "class"
                },
            }
        )
    return connections


def _object_graph(root: ElementTree.Element) -> ElementTree.Element | None:
    return next(
        (
            element
            for element in root.iter()
            if _local_name(element.tag) == "object-graph" or _local_name(element.tag).endswith("...object-graph")
        ),
        None,
    )


def _parse_relations(root: ElementTree.Element) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    relations: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    graph = _object_graph(root)
    object_ids: set[str] = set()
    if graph is not None:
        objects_container = next((child for child in graph if _local_name(child.tag) == "objects"), None)
        if objects_container is not None:
            for object_element in _children(objects_container, "object"):
                object_id = object_element.attrib.get("id") or f"object-{len(object_ids) + 1}"
                object_ids.add(object_id)
                relation_element = _first_descendant(object_element, "relation")
                if relation_element is None:
                    continue
                start = len(relations)
                _parse_relation_tree(
                    relation_element,
                    root_id=object_id,
                    parent_relation_id=None,
                    relations=relations,
                )
                relations[start]["object_id"] = object_id
                relations[start]["object_caption"] = object_element.attrib.get("caption")

        relationships_container = next((child for child in graph if _local_name(child.tag) == "relationships"), None)
        if relationships_container is not None:
            for position, relationship in enumerate(_children(relationships_container, "relationship"), start=1):
                first_endpoint = _first_descendant(relationship, "first-end-point")
                second_endpoint = _first_descendant(relationship, "second-end-point")
                expression = next(
                    (child for child in relationship if _local_name(child.tag) == "expression"),
                    None,
                )
                relationships.append(
                    {
                        "relationship_id": f"relationship-{position:03d}",
                        "left_relation_id": first_endpoint.attrib.get("object-id") if first_endpoint is not None else None,
                        "right_relation_id": second_endpoint.attrib.get("object-id") if second_endpoint is not None else None,
                        "expression": _expression(expression),
                        "attributes": _safe_attributes(relationship.attrib),
                    }
                )

    if not relations:
        parent_map = {child: parent for parent in root.iter() for child in parent}
        candidates = []
        for element in root.iter():
            if not _is_relation(element):
                continue
            parent = parent_map.get(element)
            if parent is not None and _is_relation(parent):
                continue
            candidates.append(element)
        for position, relation_element in enumerate(candidates, start=1):
            _parse_relation_tree(
                relation_element,
                root_id=f"relation-{position:03d}",
                parent_relation_id=None,
                relations=relations,
            )
    return relations, relationships


def _element_values(element: ElementTree.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in element:
        text = (child.text or "").strip()
        if text:
            values[_local_name(child.tag)] = text
    return values


def _aliases(column: ElementTree.Element) -> list[dict[str, str]]:
    aliases = []
    for element in column.iter():
        if _local_name(element.tag) != "alias":
            continue
        alias = _safe_attributes(element.attrib)
        text = (element.text or "").strip()
        if text:
            alias["value"] = text
        if alias:
            aliases.append(alias)
    return aliases


def _parse_fields_and_calculations(
    root: ElementTree.Element,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    root_columns = [child for child in root if _local_name(child.tag) == "column"]
    column_definitions = {column.attrib.get("name"): column for column in root_columns if column.attrib.get("name")}
    fields: list[dict[str, Any]] = []
    calculations: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []

    for parameter in (
        element
        for element in root.iter()
        if _local_name(element.tag) == "column" and element.attrib.get("param-domain-type")
    ):
        range_element = next((child for child in parameter if _local_name(child.tag) == "range"), None)
        parameters.append(
            {
                "parameter_id": parameter.attrib.get("name"),
                "name": parameter.attrib.get("caption") or _clean_tableau_name(parameter.attrib.get("name")),
                "datatype": parameter.attrib.get("datatype"),
                "domain_type": parameter.attrib.get("param-domain-type"),
                "default_value": parameter.attrib.get("value"),
                "format": parameter.attrib.get("default-format"),
                "range": _safe_attributes(range_element.attrib) if range_element is not None else None,
                "aliases": _aliases(parameter),
            }
        )

    for column in root_columns:
        calculation = next((child for child in column if _local_name(child.tag) == "calculation"), None)
        if calculation is None:
            continue
        calculations.append(
            {
                "calculation_id": column.attrib.get("name"),
                "name": column.attrib.get("caption") or _clean_tableau_name(column.attrib.get("name")),
                "formula": calculation.attrib.get("formula"),
                "class": calculation.attrib.get("class"),
                "datatype": column.attrib.get("datatype"),
                "role": column.attrib.get("role"),
                "type": column.attrib.get("type"),
                "format": column.attrib.get("default-format"),
                "hidden": _parse_bool(column.attrib.get("hidden")),
                "semantic_role": column.attrib.get("semantic-role"),
                "attributes": {
                    key: value
                    for key, value in _safe_attributes(calculation.attrib).items()
                    if key not in {"formula", "class"}
                },
                "aliases": _aliases(column),
            }
        )

    physical_field_ids: set[str] = set()
    for record in (
        element
        for element in root.iter()
        if _local_name(element.tag) == "metadata-record" and element.attrib.get("class") == "column"
    ):
        values = _element_values(record)
        field_id = values.get("local-name") or values.get("remote-name")
        if not field_id:
            continue
        physical_field_ids.add(field_id)
        definition = column_definitions.get(field_id)
        object_id = next((value for key, value in values.items() if key.endswith("...object-id")), None)
        fields.append(
            {
                "field_id": field_id,
                "name": _clean_tableau_name(field_id),
                "remote_name": values.get("remote-name"),
                "relation_name": _clean_tableau_name(values.get("parent-name")),
                "object_id": _clean_tableau_name(object_id),
                "datatype": values.get("local-type") or (definition.attrib.get("datatype") if definition is not None else None),
                "remote_type": values.get("remote-type"),
                "ordinal": _parse_int(values.get("ordinal")),
                "default_aggregation": values.get("aggregation"),
                "nullable": _parse_bool(values.get("contains-null")),
                "role": definition.attrib.get("role") if definition is not None else None,
                "type": definition.attrib.get("type") if definition is not None else None,
                "semantic_role": definition.attrib.get("semantic-role") if definition is not None else None,
                "format": definition.attrib.get("default-format") if definition is not None else None,
                "hidden": _parse_bool(definition.attrib.get("hidden")) if definition is not None else None,
                "kind": "physical",
                "aliases": _aliases(definition) if definition is not None else [],
            }
        )

    calculation_ids = {item["calculation_id"] for item in calculations}
    parameter_ids = {item["parameter_id"] for item in parameters}
    for column in root_columns:
        field_id = column.attrib.get("name")
        if not field_id or field_id in physical_field_ids or field_id in calculation_ids or field_id in parameter_ids:
            continue
        fields.append(
            {
                "field_id": field_id,
                "name": column.attrib.get("caption") or _clean_tableau_name(field_id),
                "remote_name": None,
                "relation_name": None,
                "object_id": None,
                "datatype": column.attrib.get("datatype"),
                "remote_type": None,
                "ordinal": None,
                "default_aggregation": None,
                "nullable": None,
                "role": column.attrib.get("role"),
                "type": column.attrib.get("type"),
                "semantic_role": column.attrib.get("semantic-role"),
                "format": column.attrib.get("default-format"),
                "hidden": _parse_bool(column.attrib.get("hidden")),
                "kind": "generated",
                "aliases": _aliases(column),
            }
        )
    fields.sort(key=lambda field: ((field["relation_name"] or "").casefold(), (field["name"] or "").casefold()))
    calculations.sort(key=lambda item: (item["name"] or "").casefold())
    parameters.sort(key=lambda item: (item["name"] or "").casefold())
    return fields, calculations, parameters


def _parse_filters(root: ElementTree.Element) -> list[dict[str, Any]]:
    filters = []
    for position, element in enumerate(
        (item for item in root.iter() if _local_name(item.tag) in {"filter", "datasource-filter"}),
        start=1,
    ):
        expression = _first_descendant(element, "expression")
        filters.append(
            {
                "filter_id": f"filter-{position:03d}",
                "kind": _local_name(element.tag),
                "attributes": _safe_attributes(element.attrib),
                "expression": _expression(expression),
            }
        )
    return filters


def _parse_semantic_metadata(root: ElementTree.Element) -> dict[str, Any]:
    groups = []
    for group in (child for child in root if _local_name(child.tag) == "group"):
        groups.append(
            {
                "name": group.attrib.get("caption") or _clean_tableau_name(group.attrib.get("name")),
                "field_id": group.attrib.get("name"),
                "datatype": group.attrib.get("datatype"),
                "role": group.attrib.get("role"),
                "member_count": sum(1 for item in group.iter() if _local_name(item.tag) == "groupfilter"),
            }
        )
    drill_paths = []
    for drill_path in (element for element in root.iter() if _local_name(element.tag) == "drill-path"):
        drill_paths.append(
            {
                "name": drill_path.attrib.get("name"),
                "fields": [
                    (field.text or "").strip()
                    for field in drill_path
                    if _local_name(field.tag) == "field" and (field.text or "").strip()
                ],
            }
        )
    return {
        "tableau_internal_name": root.attrib.get("name") or root.attrib.get("formatted-name"),
        "groups": groups,
        "drill_paths": drill_paths,
    }


def _datasource_display_name(root: ElementTree.Element, path: Path) -> str:
    for attribute in ("caption", "name"):
        value = root.attrib.get(attribute)
        if value and not value.casefold().startswith("federated."):
            return value
    named_connection = next(
        (
            element
            for element in root.iter()
            if _local_name(element.tag) == "named-connection" and element.attrib.get("caption")
        ),
        None,
    )
    if named_connection is not None:
        return named_connection.attrib["caption"]
    return path.stem


def _load_root(path: Path, limits: DiscoveryLimits) -> ElementTree.Element:
    if path.stat().st_size > limits.maximum_tds_bytes:
        raise ValueError(f"TDS file {path.name} exceeds {limits.maximum_tds_bytes} bytes")
    with path.open("rb") as handle:
        prefix = handle.read(8192).upper()
    if b"<!DOCTYPE" in prefix or b"<!ENTITY" in prefix:
        raise ValueError(f"TDS file {path.name} contains a prohibited XML declaration")
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as error:
        raise ValueError(f"Invalid TDS XML in {path.name}: {error}") from error
    if _local_name(root.tag) != "datasource":
        raise ValueError(f"TDS file {path.name} does not have a datasource root element")
    return root


def parse_tableau_datasource(
    *,
    tds_path: str | Path,
    source_path: str,
    document_path: str,
    workflow_run_id: str,
    package_hash: str,
    datasource_id: str,
    created_at: str,
    inventory_hash: str,
    limits: DiscoveryLimits | None = None,
) -> dict[str, Any]:
    path = Path(tds_path)
    limits = limits or DiscoveryLimits()
    root = _load_root(path, limits)
    connections = _parse_connections(root)
    relations, relationships = _parse_relations(root)
    fields, calculations, parameters = _parse_fields_and_calculations(root)
    filters = _parse_filters(root)
    metadata = _parse_semantic_metadata(root)
    warnings = []
    if not connections:
        warnings.append({"code": "NO_CONNECTION", "message": "Datasource contains no connection metadata"})
    if not relations:
        warnings.append({"code": "NO_RELATION", "message": "Datasource contains no relation metadata"})
    for relationship in relationships:
        if not relationship["left_relation_id"] or not relationship["right_relation_id"]:
            warnings.append(
                {
                    "code": "INCOMPLETE_RELATIONSHIP",
                    "message": f"{relationship['relationship_id']} has a missing endpoint",
                }
            )
    return {
        "schema_version": "1.0",
        "workflow_run_id": workflow_run_id,
        "datasource_id": datasource_id,
        "datasource_name": _datasource_display_name(root, path),
        "source_system": "tableau",
        "source_version": root.attrib.get("version"),
        "source_path": source_path,
        "document_path": document_path,
        "package_hash": package_hash,
        "connections": connections,
        "relations": relations,
        "relationships": relationships,
        "fields": fields,
        "calculations": calculations,
        "parameters": parameters,
        "filters": filters,
        "metadata": metadata,
        "warnings": warnings,
        "provenance": {
            "created_at": created_at,
            "generator": {"name": "datasource-semantic-migration", "version": __version__},
            "inventory_hash": inventory_hash,
            "tds_sha256": sha256_file(path),
        },
    }


def _document_relative_path(asset: dict[str, Any], document: dict[str, Any]) -> str:
    if document.get("document_path"):
        return document["document_path"]
    # Inventories written before discovery recorded document_path.
    if asset["kind"] == "TDS":
        return asset["relative_path"]
    member = next(
        (
            item
            for item in asset["archive_members"]
            if item.get("extracted_path") == document["path"] and item.get("kind") == "TDS"
        ),
        None,
    )
    if member is None:
        raise ValueError(f"TDSX inventory cannot resolve packaged document: {document['path']}")
    return member["relative_path"]


def parse_inventory_asset(inventory: dict[str, Any], asset_index: int) -> list[dict[str, Any]]:
    try:
        asset = inventory["assets"][asset_index]
    except (IndexError, TypeError) as error:
        raise ValueError(f"Asset index is outside the inventory: {asset_index}") from error
    if asset["duplicate_of"] is not None:
        raise ValueError(f"Asset index {asset_index} is an exact duplicate and must not be parsed")
    parsed = []
    for document in asset["tds_documents"]:
        document_path = _document_relative_path(asset, document)
        datasource_id = hashlib.sha256(
            f"{asset['sha256']}\0{document_path}\0{document['sha256']}".encode("utf-8")
        ).hexdigest()
        parsed.append(
            parse_tableau_datasource(
                tds_path=document["path"],
                source_path=asset["source_path"],
                document_path=document_path,
                workflow_run_id=inventory["workflow_run_id"],
                package_hash=asset["sha256"],
                datasource_id=datasource_id,
                created_at=inventory["created_at"],
                inventory_hash=inventory["inventory_hash"],
            )
        )
    if not parsed and not asset.get("published_datasources"):
        raise ValueError(f"Asset index {asset_index} contains no TDS documents")
    # A workbook that only references published datasources has nothing to parse; discovery lists them.
    return parsed


def write_asset_ir_result(
    *,
    inventory: dict[str, Any],
    asset_index: int,
    ir_root: str | Path,
) -> dict[str, Any]:
    asset = inventory["assets"][asset_index]
    asset_root = Path(ir_root) / "assets" / asset["asset_id"]
    datasource_entries = []
    for document in parse_inventory_asset(inventory, asset_index):
        output_path = write_json_artifact(document, asset_root / f"{document['datasource_id']}.json")
        datasource_entries.append(
            {
                "datasource_id": document["datasource_id"],
                "datasource_name": document["datasource_name"],
                "source_path": document["source_path"],
                "document_path": document["document_path"],
                "output_path": output_path.as_posix(),
                "ir_sha256": sha256_file(output_path),
                "connection_count": len(document["connections"]),
                "relation_count": len(document["relations"]),
                "relationship_count": len(document["relationships"]),
                "field_count": len(document["fields"]),
                "calculation_count": len(document["calculations"]),
                "parameter_count": len(document["parameters"]),
                "warning_count": len(document["warnings"]),
            }
        )
    result = {
        "schema_version": "1.0",
        "workflow_run_id": inventory["workflow_run_id"],
        "asset_index": asset_index,
        "asset_id": asset["asset_id"],
        "source_path": asset["source_path"],
        "status": "COMPLETE",
        "datasources": datasource_entries,
    }
    write_json_artifact(result, asset_root / "parse-result.json")
    return result


