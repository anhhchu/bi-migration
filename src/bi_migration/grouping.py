from __future__ import annotations


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


def _dependencies(asset: dict) -> set[str]:
    dependencies = set()
    for datasource in asset.get("datasources", []):
        dependencies.add(f"datasource:{datasource['fingerprint']}")
        dependencies.update(f"table:{table.lower()}" for table in datasource.get("tables", []))
    return dependencies


def group_assets(assets: list[dict]) -> list[dict]:
    asset_ids = [asset["asset_id"] for asset in assets]
    union_find = _UnionFind(asset_ids)
    dependencies = {asset["asset_id"]: _dependencies(asset) for asset in assets}
    for index, left in enumerate(asset_ids):
        for right in asset_ids[index + 1 :]:
            if dependencies[left] & dependencies[right]:
                union_find.union(left, right)

    grouped: dict[str, list[str]] = {}
    for asset_id in asset_ids:
        grouped.setdefault(union_find.find(asset_id), []).append(asset_id)

    results = []
    for number, members in enumerate(sorted(grouped.values(), key=lambda item: item[0]), start=1):
        shared = set.intersection(*(dependencies[member] for member in members)) if len(members) > 1 else set()
        results.append(
            {
                "group_id": f"group-{number:03d}",
                "assets": sorted(members),
                "shared_dependencies": sorted(shared),
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
