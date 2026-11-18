from bi_migration.ingest import build_artifact_manifest, build_run_manifest


def test_manifest_is_stable_and_filters_unsupported_files(tmp_path):
    (tmp_path / "sample.twb").write_text("<workbook />", encoding="utf-8")
    (tmp_path / "mapping.csv").write_text("Source Field,Target Field\nSales,sales_amount\n", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("ignored", encoding="utf-8")

    first = build_artifact_manifest(tmp_path)
    second = build_artifact_manifest(tmp_path)

    assert [item["artifact_id"] for item in first] == [item["artifact_id"] for item in second]
    assert {item["artifact_type"] for item in first} == {"tableau_workbook", "mapping_document"}
    assert len(first) == 2


def test_manifest_uses_governed_source_uris_and_builds_run_contract(tmp_path):
    (tmp_path / "sales.twbx").write_bytes(b"package")
    (tmp_path / "mapping.yaml").write_text("version: 1", encoding="utf-8")
    source = "/Volumes/catalog/schema/landing/runs/run-123/input"

    artifacts = build_artifact_manifest(tmp_path, source_base_uri=source)
    run_manifest = build_run_manifest(artifacts, run_id="run-123", source_base_uri=source)

    assert {item["source_uri"] for item in artifacts} == {
        f"{source}/workbooks/sales.twbx",
        f"{source}/mappings/mapping.yaml",
    }
    assert run_manifest["run_id"] == "run-123"
    assert run_manifest["artifact_count"] == 2
    assert run_manifest["workbook_count"] == 1
    assert run_manifest["mapping_document_count"] == 1
