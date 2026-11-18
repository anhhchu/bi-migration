from bi_migration.mapping import apply_mapping_evidence
from bi_migration.mapping import draft_mapping
from bi_migration.mapping_documents import load_mapping_documents


def _mapping():
    return {
        "status": "proposed",
        "fields": [
            {
                "datasource": "sales",
                "legacy": "Sales",
                "target_table": "wrong.table",
                "target_expression": "wrong_column",
                "confidence": 0.5,
                "status": "unresolved",
                "evidence": ["name_similarity"],
            }
        ],
    }


def test_csv_mapping_evidence_overrides_name_proposal(tmp_path):
    document = tmp_path / "mapping.csv"
    document.write_text(
        "Source Field,Target Table,Target Field,Source Grain,Target Grain\n"
        "Sales,main.gold.orders,sales_amount,order line,order line\n",
        encoding="utf-8",
    )
    evidence, errors = load_mapping_documents(document)
    compiled, conflicts = apply_mapping_evidence(_mapping(), evidence)

    assert not errors
    assert not conflicts
    assert compiled["fields"][0]["target_table"] == "main.gold.orders"
    assert compiled["fields"][0]["target_expression"] == "sales_amount"
    assert compiled["fields"][0]["evidence"][0].startswith("mapping_document:")


def test_conflicting_mapping_documents_remain_unresolved(tmp_path):
    document = tmp_path / "mapping.csv"
    document.write_text(
        "Source Field,Target Table,Target Field\n"
        "Sales,main.gold.orders,sales_amount\n"
        "Sales,main.gold.orders,gross_amount\n",
        encoding="utf-8",
    )
    evidence, _ = load_mapping_documents(document)
    compiled, conflicts = apply_mapping_evidence(_mapping(), evidence)

    assert conflicts
    assert compiled["fields"][0]["status"] == "unresolved"
    assert compiled["fields"][0]["evidence"] == ["conflicting_mapping_documents"]


def test_target_grain_is_preserved_in_generated_suggestion():
    assets = [{"asset_id": "sales", "datasources": [{"id": "sales", "fields": [{"name": "Sales", "datatype": "real"}]}]}]
    metadata = {"tables": [{"name": "main.gold.orders", "grain": "order line", "columns": [{"name": "sales", "type": "real"}]}]}

    mapping, _, _ = draft_mapping(assets, metadata, "sales")

    assert mapping["fields"][0]["target_grain"] == "order line"


def test_document_interpretation_without_target_stays_unresolved(tmp_path):
    document = tmp_path / "mapping.csv"
    document.write_text(
        "Source Field,Source Grain,Notes\n"
        "Sales,order line,Business concept is documented but target is unknown\n",
        encoding="utf-8",
    )

    evidence, errors = load_mapping_documents(document)
    compiled, conflicts = apply_mapping_evidence(_mapping(), evidence)
    field = compiled["fields"][0]

    assert not errors
    assert not conflicts
    assert field["status"] == "unresolved"
    assert field["confidence"] == 0.0
    assert field["mapping_document"]["source_grain"] == "order line"
    assert "target is unknown" in field["mapping_document"]["notes"]
    assert field["evidence"][0].startswith("mapping_document:")


def test_dataset_mapping_yaml_flattens_source_lineage(tmp_path):
    document = tmp_path / "mapping.yaml"
    document.write_text(
        """
mapping_version: 1.0.0
dataset_mappings:
  - source:
      platform: fabric
      table: Orders
      grain: order line
    target:
      table: main.sales.sales_order_line_bitemporal
      grain: bitemporal order line
    columns:
      - source_column: Order ID
        target_column: sales_order_id
        conversion: renamed
""",
        encoding="utf-8",
    )

    evidence, errors = load_mapping_documents(document)

    assert not errors
    assert evidence == [
        {
            "source_table": "Orders",
            "source_grain": "order line",
            "legacy": "Order ID",
            "target_table": "main.sales.sales_order_line_bitemporal",
            "target_expression": "sales_order_id",
            "target_grain": "bitemporal order line",
            "conversion": "renamed",
            "provenance": {"file": str(document), "locator": "dataset:1:column:1"},
        }
    ]


def test_dataset_mapping_yaml_preserves_relationship_and_temporal_evidence(tmp_path):
    document = tmp_path / "mapping.yaml"
    document.write_text(
        """
dataset_mappings:
  - source: {table: Orders, grain: order line}
    target: {table: main.sales.order_lines, grain: order line}
    columns:
      - {source_column: Order ID, target_column: order_id}
  - source: {table: Orders, grain: order line}
    target: {table: main.sales.customers, grain: customer version, temporal_mode: bitemporal}
    relationship: {source_key: Customer ID, target_key: customer_id, as_of: Order Date}
    columns:
      - {source_column: Customer Name, target_column: customer_name}
""",
        encoding="utf-8",
    )

    evidence, errors = load_mapping_documents(document)
    relationship = next(item for item in evidence if item.get("evidence_type") == "relationship")

    assert not errors
    assert relationship["target_left_table"] == "main.sales.order_lines"
    assert relationship["target_right_table"] == "main.sales.customers"
    assert relationship["as_of"] == "Order Date"


def test_mapping_relationship_resolves_matching_tableau_relationship(tmp_path):
    document = tmp_path / "mapping.yaml"
    document.write_text(
        """
dataset_mappings:
  - source: {table: Orders}
    target: {table: main.sales.order_lines}
    columns:
      - {source_column: Order ID, target_column: order_id}
  - source: {table: Returns}
    target: {table: main.sales.returns}
    relationship: {target_left_table: main.sales.order_lines, source_key: Order ID, target_key: order_id}
    columns:
      - {source_column: Returned, target_column: returned}
""",
        encoding="utf-8",
    )
    mapping = {
        "sources": ["workbook"],
        "fields": [{
            "datasource": "sales", "legacy": "Order ID", "source_table": "Orders$",
            "target_table": "main.sales.order_lines", "target_expression": "order_id",
            "status": "proposed", "confidence": 1, "evidence": [],
        }],
        "relationships": [{
            "datasource": "sales",
            "source": {"left_table": "Orders$", "right_table": "Returns$", "join_type": "left", "condition": ""},
            "target": {"left_table_candidates": ["main.sales.order_lines"], "right_table_candidates": ["main.sales.returns"]},
            "assets": ["workbook"], "status": "unresolved", "confidence": 0, "evidence": [],
        }],
    }
    evidence, _ = load_mapping_documents(document)

    compiled, conflicts = apply_mapping_evidence(mapping, evidence)

    assert not conflicts
    assert len(compiled["relationships"]) == 1
    assert compiled["relationships"][0]["status"] == "proposed"
    assert compiled["relationships"][0]["target"]["cardinality"] == "many_to_one"
