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


def test_importbi_result_prompts_name_every_schema_field():
    root = Path(__file__).resolve().parents[1]
    schema = SchemaRegistry(root / "schemas").get("importbi_result").document
    prompts = {
        "template": (root / "prompts" / "tableau" / "import_metric_view.md").read_text(encoding="utf-8"),
        "job": (root / "notebooks" / "prepare_candidate_context.py").read_text(encoding="utf-8"),
    }
    # validation is reporting-only metadata; the agent is not asked to write it.
    fields = set(schema["properties"]) - {"validation"}
    assert set(schema["required"]) <= fields
    for name, text in prompts.items():
        missing = sorted(field for field in fields if field not in text)
        assert not missing, f"{name} prompt does not mention {missing}"
