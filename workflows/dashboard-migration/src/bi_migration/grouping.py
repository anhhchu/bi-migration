from __future__ import annotations

import hashlib
import re


class _UnionFind:
    def __init__(self, values: list[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _normalized_table(table: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", table.lower()).strip(".")


def _is_generic_extract_table(table: str) -> bool:
    return _normalized_table(table) in {"extract.extract", "data.engine.extract"}


def _has_connection_identity(datasource: dict) -> bool:
    return any(
        connection.get(key)
        for connection in datasource.get("connections", [])
        for key in ("server", "dbname", "schema")
    )


def _is_local_datasource(datasource: dict) -> bool:
    local_classes = {"excel-direct", "textscan", "hyper"}
    return any(connection.get("class") in local_classes for connection in datasource.get("connections", []))


def _dependencies(asset: dict) -> set[str]:
    dependencies = set()
    for datasource in asset.get("datasources", []):
        meaningful_tables = [
            table for table in datasource.get("tables", []) if not _is_generic_extract_table(table)
        ]
        if meaningful_tables or _has_connection_identity(datasource):
            dependencies.add(f"datasource:{datasource['fingerprint']}")
        if not _is_local_datasource(datasource):
            dependencies.update(f"table:{table.lower()}" for table in meaningful_tables)
    return dependencies


def _physical_fields(asset: dict) -> set[str]:
    return {
        re.sub(r"[^a-z0-9]+", " ", str(field.get("caption") or field.get("name")).lower()).strip()
        for datasource in asset.get("datasources", [])
        if _is_local_datasource(datasource)
        for field in datasource.get("fields", [])
        if (field.get("caption") or field.get("name")) and not field.get("calculation")
    }


def _schema_similarity(left: dict, right: dict) -> dict | None:
    left_fields = _physical_fields(left)
    right_fields = _physical_fields(right)
    if not left_fields or not right_fields:
        return None
    shared = left_fields & right_fields
    jaccard = len(shared) / len(left_fields | right_fields)
    containment = len(shared) / min(len(left_fields), len(right_fields))
    if len(shared) < 12 or jaccard < 0.45 or containment < 0.65:
        return None
    return {
        "left": left["asset_id"],
        "right": right["asset_id"],
        "shared_field_count": len(shared),
        "jaccard": round(jaccard, 3),
        "containment": round(containment, 3),
        "shared_fields": sorted(shared),
    }


def group_assets(assets: list[dict]) -> list[dict]:
    asset_ids = [asset["asset_id"] for asset in assets]
    union_find = _UnionFind(asset_ids)
    assets_by_id = {asset["asset_id"]: asset for asset in assets}
    dependencies = {asset["asset_id"]: _dependencies(asset) for asset in assets}
    similarity_edges = []
    for index, left in enumerate(asset_ids):
        for right in asset_ids[index + 1 :]:
            if dependencies[left] & dependencies[right]:
                union_find.union(left, right)
                continue
            similarity = _schema_similarity(assets_by_id[left], assets_by_id[right])
            if similarity:
                similarity_edges.append(similarity)
                union_find.union(left, right)

    grouped: dict[str, list[str]] = {}
    for asset_id in asset_ids:
        grouped.setdefault(union_find.find(asset_id), []).append(asset_id)

    results = []
    for number, members in enumerate(sorted(grouped.values(), key=lambda item: item[0]), start=1):
        shared = set.intersection(*(dependencies[member] for member in members)) if len(members) > 1 else set()
        all_dependencies = sorted(set.union(*(dependencies[member] for member in members)))
        signature_source = "|".join([*sorted(members), *all_dependencies])
        results.append(
            {
                "group_id": f"group-{number:03d}",
                "assets": sorted(members),
                "shared_dependencies": sorted(shared),
                "dependencies": all_dependencies,
                "similarity_edges": [
                    edge
                    for edge in similarity_edges
                    if edge["left"] in members and edge["right"] in members
                ],
                "coverage_signature": hashlib.sha256(signature_source.encode()).hexdigest()[:16],
            }
        )
    return results


def dependency_graph(assets: list[dict]) -> dict:
    nodes: set[tuple[str, str]] = set()
    edges: set[tuple[str, str, str]] = set()
    for asset in assets:
        asset_node = f"asset:{asset['asset_id']}"
        nodes.add((asset_node, "asset"))
        for dashboard in asset.get("dashboards", []):
            dashboard_node = f"dashboard:{asset['asset_id']}:{dashboard['name']}"
            nodes.add((dashboard_node, "dashboard"))
            edges.add((asset_node, dashboard_node, "contains"))
            for worksheet_name in dashboard.get("worksheets", []):
                worksheet_node = f"worksheet:{asset['asset_id']}:{worksheet_name}"
                nodes.add((worksheet_node, "worksheet"))
                edges.add((dashboard_node, worksheet_node, "uses"))
        for worksheet in asset.get("worksheets", []):
            worksheet_node = f"worksheet:{asset['asset_id']}:{worksheet['name']}"
            nodes.add((worksheet_node, "worksheet"))
            for datasource_id in worksheet.get("datasources", []):
                datasource_node = f"datasource:{asset['asset_id']}:{datasource_id}"
                nodes.add((datasource_node, "datasource"))
                edges.add((worksheet_node, datasource_node, "uses"))
        for datasource in asset.get("datasources", []):
            datasource_node = f"datasource:{asset['asset_id']}:{datasource['id']}"
            nodes.add((datasource_node, "datasource"))
            for table in datasource.get("tables", []):
                table_node = f"table:{table}"
                nodes.add((table_node, "table"))
                edges.add((datasource_node, table_node, "reads"))
    return {
        "nodes": [{"id": node_id, "type": node_type} for node_id, node_type in sorted(nodes)],
        "edges": [
            {"source": source, "target": target, "relationship": relationship}
            for source, target, relationship in sorted(edges)
        ],
    }