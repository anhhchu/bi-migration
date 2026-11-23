from pathlib import Path

from datasource_semantic_migration.schema_registry import SchemaRegistry


def test_all_workflow_schemas_are_registered_and_loadable():
    root = Path(__file__).resolve().parents[1]
    registry = SchemaRegistry(root / "schemas")

    assert registry.names() == (
        "datasource_ir",
        "datasource_ir_index",
        "deterministic_patch",
        "evaluation_summary",
        "genie_patch",
        "importbi_result",
        "input_inventory",
        "mapping_revision",
        "metric_ir",
        "metric_ir_index",
        "metric_scorecard",
        "semantic_grouping_proposal",
        "structured_finding",
        "table_mapping_input",
        "workflow_manifest",
    )
    for name in registry.names():
        definition = registry.get(name)
        assert definition.version == "1.0"
        assert definition.document["$schema"].endswith("2020-12/schema")
