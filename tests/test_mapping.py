import json

from bi_migration.mapping import draft_mapping
from bi_migration.tableau import parse_tableau


def test_draft_mapping_proposes_matches_and_preserves_unresolved():
    assets = [parse_tableau("tests/fixtures/tableau/sales_a.twb")]
    target = json.loads(open("examples/target_metadata.json", encoding="utf-8").read())
    mapping, unresolved, kpis = draft_mapping(assets, target, "sales")
    proposals = {item["legacy"]: item for item in mapping["fields"]}
    assert proposals["Order ID"]["status"] == "proposed"
    assert proposals["Sales"]["target_expression"] == "sales_amount"
    assert proposals["Margin %"]["status"] == "unresolved"
    assert unresolved[0]["legacy"] == "Margin %"
    assert kpis[0]["legacy_name"] == "Margin %"
    assert set(mapping) == {"mapping_version", "domain", "status", "sources", "fields", "kpis"}
    assert all(0 <= item["confidence"] <= 1 for item in mapping["fields"])


def test_draft_mapping_rejects_weak_name_similarity():
    assets = [
        {
            "asset_id": "sample",
            "datasources": [
                {
                    "id": "orders",
                    "fields": [{"name": "Order Date", "caption": "Order Date", "datatype": "date"}],
                }
            ],
        }
    ]
    target = {"tables": [{"name": "main.gold.orders", "columns": [{"name": "order_id", "type": "string"}]}]}
    mapping, unresolved, _ = draft_mapping(assets, target, "sales")
    assert mapping["fields"][0]["status"] == "unresolved"
    assert unresolved[0]["legacy"] == "Order Date"
