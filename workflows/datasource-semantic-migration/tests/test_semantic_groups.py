from __future__ import annotations

import json
from pathlib import Path

import yaml
import pytest

from datasource_semantic_migration.artifacts import sha256_file
from datasource_semantic_migration.sources.tableau.metric_compiler import compile_metric_ir
from datasource_semantic_migration.semantic_groups import (
    _mapping_targets,
    _relation_name,
    _validate_grouping_proposal,
    build_grouping_request,
    build_semantic_groups,
    semantic_features,
    semantic_similarity,
)
from datasource_semantic_migration.sources.tableau.parser import parse_tableau_datasource


def tableau_artifacts(tmp_path: Path):
    sample_root = Path(__file__).resolve().parents[1] / "datasource-samples"
    source = sample_root / "Superstore.tds"
    datasource_ir = parse_tableau_datasource(
        tds_path=source,
        source_path="/Volumes/main/bi_migration/tableau_datasources/datasources/Superstore.tds",
        document_path="Superstore.tds",
        workflow_run_id="run-123",
        package_hash=sha256_file(source),
        datasource_id="datasource-123",
        created_at="2026-11-22T00:00:00Z",
        inventory_hash="0" * 64,
    )
    metric_ir = compile_metric_ir(datasource_ir)
    datasource_path = tmp_path / "datasource-ir.json"
    metric_path = tmp_path / "metric-ir.json"
    datasource_path.write_text(json.dumps(datasource_ir), encoding="utf-8")
    metric_path.write_text(json.dumps(metric_ir), encoding="utf-8")
    return sample_root, datasource_ir, metric_ir, datasource_path, metric_path


def test_identical_datasources_have_full_semantic_similarity(tmp_path):
    _, datasource_ir, metric_ir, _, _ = tableau_artifacts(tmp_path)
    features = semantic_features(datasource_ir, metric_ir)

    score, components = semantic_similarity(features, features)

    assert score == pytest.approx(1.0)
    assert set(components.values()) == {1.0}


def test_relation_names_preserve_file_names_and_normalize_tableau_extract_syntax():
    assert _relation_name("Finance Data.csv") == "finance data.csv"
    assert _relation_name("[Finance Data#csv]") == "finance data.csv"
    assert _relation_name("[catalog].[schema].[Orders$]") == "orders"


def test_mapping_targets_honor_optional_datasource_hint():
    mapping = {
        "table_mappings": [
            {
                "source": {"table": "Sheet1", "datasource": "Hospital ER"},
                "target": {"table": "main.hospital.point_scaffold"},
            }
        ]
    }
    hospital_targets = _mapping_targets(
        mapping,
        {"datasource_name": "Hospital ER", "relations": [{"name": "Sheet1", "table": "[Sheet1$]"}]},
    )[1]
    annotations_targets = _mapping_targets(
        mapping,
        {"datasource_name": "TOC & Annotations", "relations": [{"name": "Sheet1", "table": "[Sheet1$]"}]},
    )[1]

    assert hospital_targets == ["main.hospital.point_scaffold"]
    assert annotations_targets == []


def test_build_semantic_groups_writes_readable_group_contract(tmp_path):
    sample_root, datasource_ir, _, datasource_path, metric_path = tableau_artifacts(tmp_path)
    inventory = {
        "workflow_run_id": "run-123",
        "created_at": "2026-11-22T00:00:00Z",
    }
    datasource_index = {
        "datasources": [
            {
                "datasource_id": datasource_ir["datasource_id"],
                "output_path": datasource_path.as_posix(),
            }
        ]
    }
    metric_index = {
        "datasources": [
            {
                "datasource_id": datasource_ir["datasource_id"],
                "output_path": metric_path.as_posix(),
            }
        ]
    }
    proposal_path = tmp_path / "semantic-grouping-proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "COMPLETE",
                "groups": [
                    {
                        "display_name": "Superstore",
                        "domain": "Retail sales",
                        "member_datasource_ids": [datasource_ir["datasource_id"]],
                        "helper_datasource_ids": [],
                        "rationale": "Shared Superstore sales model",
                        "confidence": 0.99,
                    }
                ],
                "ungrouped_datasources": [],
            }
        ),
        encoding="utf-8",
    )

    request = build_grouping_request(
        inventory=inventory,
        datasource_ir_index=datasource_index,
        metric_ir_index=metric_index,
        mapping_path=sample_root / "table-mapping.yaml",
        grouping_result_path=proposal_path,
    )

    assert request["status"] == "READY_FOR_GENIE"
    assert request["datasources"][0]["target_tables"]

    result = build_semantic_groups(
        inventory=inventory,
        datasource_ir_index=datasource_index,
        metric_ir_index=metric_index,
        mapping_path=sample_root / "table-mapping.yaml",
        grouping_proposal_path=proposal_path,
        run_root=tmp_path / "run",
        candidate_catalog="main",
        candidate_schema="bi_migration",
    )

    assert result["summary"] == {
        "datasource_count": 1,
        "semantic_group_count": 1,
        "ready_group_count": 1,
        "blocked_group_count": 0,
        "excluded_helper_count": 0,
    }
    group = result["groups"][0]
    assert group["group_id"] == "superstore"
    assert group["display_name"] == "Superstore"
    assert Path(group["internal_path"]).name == "_internal"
    assert group["report_path"].endswith("/reports/groups/superstore")
    assert Path(group["source_summary_path"]).is_file()
    manifest = json.loads(Path(group["group_manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["display_name"] == "Superstore"
    assert manifest["source_system"] == group["source_system"] == "tableau"
    assert manifest["candidate_metric_view_fqn"].startswith("main.bi_migration.bim_superstore_")
    immutable_mapping = yaml.safe_load(Path(manifest["mapping_path"]).read_text(encoding="utf-8"))
    assert immutable_mapping["table_mappings"]
    assert all(
        relationship["left"]["table"] in manifest["target_tables"]
        and relationship["right"]["table"] in manifest["target_tables"]
        for relationship in immutable_mapping["relationships"]
    )


def test_grouping_request_preserves_approved_business_context(tmp_path):
    sample_root, datasource_ir, _, datasource_path, metric_path = tableau_artifacts(tmp_path)
    mapping_path = tmp_path / "mapping.yaml"
    mapping = yaml.safe_load((sample_root / "table-mapping.yaml").read_text(encoding="utf-8"))
    mapping["table_mappings"][0]["source"].update(
        {"datasource": datasource_ir["datasource_name"], "business_domain": "Retail", "display_name": "Orders"}
    )
    mapping["table_mappings"][0]["source"]["table"] = "Orders"
    mapping_path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    request = build_grouping_request(
        inventory={"workflow_run_id": "run-123"},
        datasource_ir_index={
            "datasources": [{"datasource_id": datasource_ir["datasource_id"], "output_path": datasource_path.as_posix()}]
        },
        metric_ir_index={
            "datasources": [{"datasource_id": datasource_ir["datasource_id"], "output_path": metric_path.as_posix()}]
        },
        mapping_path=mapping_path,
        grouping_result_path=tmp_path / "proposal.json",
    )

    assert request["datasources"][0]["business_domains"] == ["Retail"]
    assert request["datasources"][0]["mapping_display_names"] == ["Orders"]


def test_grouping_proposal_rejects_group_that_mixes_bi_tools():
    assets = [
        {"datasource_id": "sales-tableau", "source_system": "tableau", "target_tables": ["main.sales.orders"], "target_schemas": ["sales"]},
        {"datasource_id": "sales-powerbi", "source_system": "powerbi", "target_tables": ["main.sales.orders"], "target_schemas": ["sales"]},
    ]
    proposal = {
        "groups": [
            {
                "display_name": "Sales",
                "member_datasource_ids": ["sales-tableau", "sales-powerbi"],
                "helper_datasource_ids": [],
                "confidence": 0.9,
            }
        ],
        "ungrouped_datasources": [],
    }
    with pytest.raises(ValueError, match="mixes BI tools"):
        _validate_grouping_proposal(proposal, assets)
