from bi_migration.ingest import build_run_manifest
from bi_migration.inventory import build_inventory_preflight


def test_inventory_preflight_summarizes_parser_output():
    artifacts = [{"artifact_type": "tableau_workbook"}]
    manifest = build_run_manifest(artifacts, run_id="run-1")
    assets = [
        {
            "asset_id": "sales",
            "source_file": "sales.twb",
            "dashboards": [{"name": "Sales"}],
            "worksheets": [{"name": "Overview"}],
            "datasources": [
                {
                    "tables": ["fact_sales"],
                    "fields": [
                        {"type": "physical", "calculation": None},
                        {"type": "quantitative", "calculation": "SUM([Sales])"},
                    ],
                }
            ],
        }
    ]

    preflight = build_inventory_preflight(assets, [], manifest)

    assert preflight["status"] == "PASS"
    assert preflight["authority"] == "deterministic_tableau_parser"
    assert preflight["physical_field_count"] == 1
    assert preflight["calculated_field_count"] == 1
    assert preflight["source_tables"] == ["fact_sales"]


def test_inventory_preflight_is_partial_when_one_workbook_is_quarantined():
    manifest = build_run_manifest(
        [{"artifact_type": "tableau_workbook"}, {"artifact_type": "tableau_workbook"}],
        run_id="run-2",
    )
    preflight = build_inventory_preflight(
        [{"asset_id": "valid", "datasources": [], "dashboards": [], "worksheets": []}],
        [{"file": "broken.twbx", "error": "invalid zip", "status": "quarantined"}],
        manifest,
    )

    assert preflight["status"] == "PARTIAL"
    assert preflight["registered_workbooks"] == 2
    assert preflight["inventoried_workbooks"] == 1
    assert preflight["quarantined_workbooks"] == 1
