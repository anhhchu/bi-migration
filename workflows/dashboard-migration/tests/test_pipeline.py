import json

from bi_migration.corpus import generate_corpus
from bi_migration.pipeline import run_backend_pipeline


def test_backend_pipeline_runs_generated_corpus_and_quarantines_invalid_package(tmp_path):
    corpus = tmp_path / "corpus"
    output = tmp_path / "run"
    generate_corpus(corpus)

    result = run_backend_pipeline(
        input_path=corpus / "tableau",
        mapping_documents_path=corpus / "mappings",
        target_metadata_path=corpus / "target_metadata.json",
        domain="sales",
        output_path=output,
        run_id="pipeline-test",
        source_base_uri="/Volumes/catalog/schema/landing/runs/pipeline-test/input",
    )

    assert result["assets"] == 23
    assert result["quarantined"] == 1
    assert result["groups"] == 4
    assert not result["ready"]
    errors = json.loads((output / "inventory_errors.json").read_text(encoding="utf-8"))
    assert errors[0]["file"].endswith("corrupt.twbx")
    groups = json.loads((output / "groups.json").read_text(encoding="utf-8"))
    sales_group = next(group for group in groups if "sales_overview" in group["assets"])
    assert {"sales_overview", "sales_packaged", "sales_region"}.issubset(sales_group["assets"])
    assert len(sales_group["assets"]) == 11
    assert len(sales_group["coverage_signature"]) == 16
    manifest = json.loads((output / "artifact_manifest.json").read_text(encoding="utf-8"))
    corrupt = next(item for item in manifest if item["relative_path"] == "corrupt.twbx")
    assert corrupt["status"] == "quarantined"
    readiness = json.loads((output / "readiness_report.json").read_text(encoding="utf-8"))
    assert {issue["code"] for issue in readiness["issues"]} >= {
        "inventory_errors",
        "unresolved_fields",
        "contract_not_approved",
    }
    inventory_issue = next(issue for issue in readiness["issues"] if issue["code"] == "inventory_errors")
    assert inventory_issue["severity"] == "warning"
    group_readiness = json.loads((output / "group_readiness.json").read_text(encoding="utf-8"))
    assert len(group_readiness) == 4
    assert all((output / "groups" / item["group_id"] / "mapping_template.csv").exists() for item in group_readiness)
    assert all((output / "groups" / item["group_id"] / "readiness_report.json").exists() for item in group_readiness)
    run_manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["run_id"] == "pipeline-test"
    assert all(item["source_uri"].startswith("/Volumes/") for item in run_manifest["artifacts"])
    inventory_preflight = json.loads((output / "inventory_preflight.json").read_text(encoding="utf-8"))
    assert inventory_preflight["status"] == "PARTIAL"
    assert inventory_preflight["inventoried_workbooks"] == 23
