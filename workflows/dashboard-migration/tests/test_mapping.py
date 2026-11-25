from bi_migration.mapping import draft_mapping
from bi_migration.tableau import parse_tableau


def test_draft_mapping_proposes_matches_and_preserves_unresolved():
    assets = [parse_tableau("tests/fixtures/tableau/sales_a.twb")]
    target = {"tables": [{
        "name": "main.gold.sales",
        "grain": "order line",
        "columns": [
            {"name": "order_id", "type": "string", "synonyms": ["Order ID"]},
            {"name": "sales_amount", "type": "real", "synonyms": ["Sales"]},
        ],
    }]}
    mapping, unresolved, kpis = draft_mapping(assets, target, "sales")
    proposals = {item["legacy"]: item for item in mapping["fields"]}
    assert proposals["Order ID"]["status"] == "proposed"
    assert proposals["Sales"]["target_expression"] == "sales_amount"
    assert "Margin %" not in proposals
    assert not unresolved
    assert kpis[0]["legacy_name"] == "Margin %"
    assert set(mapping) == {
        "mapping_version", "domain", "status", "sources", "fields", "relationships", "kpis", "workbook_helpers"
    }
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


def test_draft_mapping_deduplicates_physical_fields_and_copy_calculations():
    assets = [
        {
            "asset_id": "one",
            "datasources": [
                {
                    "id": "extract-one",
                    "fields": [
                        {"name": "Sales", "datatype": "real"},
                        {"name": "Min", "datatype": "real", "calculation": "MIN([Sales])"},
                    ],
                }
            ],
        },
        {
            "asset_id": "two",
            "datasources": [
                {
                    "id": "extract-two",
                    "fields": [
                        {"name": "[Sales]", "caption": "Sales", "datatype": "real"},
                        {"name": "Min (copy)", "datatype": "real", "calculation": "MIN([Sales])"},
                    ],
                }
            ],
        },
    ]
    target = {"tables": [{"name": "main.gold.sales", "columns": [{"name": "sales", "type": "real"}]}]}

    mapping, _, kpis = draft_mapping(assets, target, "sales")

    assert len(mapping["fields"]) == 1
    assert mapping["fields"][0]["assets"] == ["one", "two"]
    assert mapping["fields"][0]["datasources"] == ["extract-one", "extract-two"]
    assert len(kpis) == 1
    assert kpis[0]["aliases"] == ["Min", "Min (copy)"]


def test_draft_mapping_excludes_clipboard_helpers_from_field_review():
    assets = [
        {
            "asset_id": "finance",
            "datasources": [
                {
                    "id": "Clipboard_20250312T134147",
                    "fields": [
                        {"name": "Chart Type", "datatype": "string"},
                        {"name": "Clipboard_20250312T134147", "datatype": "table"},
                    ],
                }
            ],
        }
    ]

    mapping, unresolved, _ = draft_mapping(assets, {"tables": []}, "sales")

    assert not mapping["fields"]
    assert not unresolved
    assert {item["name"] for item in mapping["workbook_helpers"]} == {
        "Chart Type", "Clipboard_20250312T134147"
    }


def test_draft_mapping_excludes_dashboard_objects_and_extract_replicas():
    assets = [
        {
            "asset_id": "interactive",
            "datasources": [
                {
                    "id": "superstore",
                    "fields": [
                        {"name": "Order ID", "datatype": "string", "source_table": "Orders", "source_kind": "business_source"},
                        {"name": "Order ID1", "datatype": "string", "source_table": "Extract", "source_kind": "extract_replica"},
                        {"name": "Menu Name", "datatype": "string", "source_table": "Menu", "source_kind": "dashboard_object"},
                    ],
                }
            ],
        }
    ]

    mapping, _, _ = draft_mapping(assets, {"tables": []}, "sales")

    assert [field["legacy"] for field in mapping["fields"]] == ["Order ID"]
    assert {item["name"] for item in mapping["workbook_helpers"]} == {"Menu Name", "Order ID1"}


def test_draft_mapping_proposes_target_relationship_from_field_lineage():
    assets = [{
        "asset_id": "orders",
        "datasources": [{
            "id": "sales",
            "relationships": [{
                "left_table": "Orders",
                "right_table": "Customers",
                "join_type": "left",
                "condition": "([Customer ID] = [Customer ID])",
                "source_kind": "physical_join",
            }],
            "fields": [
                {"name": "Order ID", "caption": "Order ID", "source_table": "Orders"},
                {"name": "Customer ID", "caption": "Customer ID", "source_table": "Customers"},
            ],
        }],
    }]
    target = {"tables": [
        {"name": "main.gold.orders", "columns": [{"name": "order_id", "synonyms": ["Order ID"]}]},
        {"name": "main.gold.customers", "columns": [{"name": "customer_id", "synonyms": ["Customer ID"]}]},
    ]}

    mapping, _, _ = draft_mapping(assets, target, "sales")

    relationship = mapping["relationships"][0]
    assert relationship["status"] == "proposed"
    assert relationship["target"]["left_table_candidates"] == ["main.gold.orders"]
    assert relationship["target"]["right_table_candidates"] == ["main.gold.customers"]
    assert relationship["target"]["temporal_predicates"] == []
