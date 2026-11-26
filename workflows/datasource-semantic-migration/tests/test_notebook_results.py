import json

from datasource_semantic_migration.notebook_results import (
    format_notebook_result,
    render_volume_links_html,
    summarize_semantic_groups,
    volume_catalog_url,
)


def test_format_notebook_result_is_readable_and_stable():
    result = format_notebook_result({"summary": {"unique_count": 1}, "inventory_path": "/Volumes/example"})

    assert result.startswith("{\n")
    assert '\n  "inventory_path": "/Volumes/example",' in result
    assert '\n  "summary": {' in result
    assert '\n    "unique_count": 1' in result


def test_volume_catalog_url_links_to_catalog_explorer_volume():
    assert volume_catalog_url("/Volumes/main/bi migration/run artifacts/reports/index.html") == (
        "/explore/data/volumes/main/bi%20migration/run%20artifacts"
    )
    assert volume_catalog_url("/tmp/report.json") is None


def test_render_volume_links_html_finds_nested_paths_and_escapes_labels():
    rendered = render_volume_links_html(
        {
            "summary_path": "/Volumes/main/bi_migration/artifacts/reports/index.html",
            "nested": ["not-a-volume", "/Volumes/main/bi_migration/artifacts/groups/a&b.json"],
        }
    )

    assert rendered.count("Open Volume") == 2
    assert "/explore/data/volumes/main/bi_migration/artifacts" in rendered
    assert "a&amp;b.json" in rendered


def test_semantic_group_summary_exposes_index_sources_targets_and_migration_status(tmp_path):
    source_summary_path = tmp_path / "source-summary.json"
    source_summary_path.write_text(
        json.dumps(
            {
                "datasources": [
                    {
                        "datasource_name": "Orders",
                        "source_path": "/Volumes/main/input/superstore-orders.tdsx",
                    }
                ],
                "target_tables": ["main.superstore.orders"],
            }
        ),
        encoding="utf-8",
    )
    groups_index = {
        "groups": [
            {
                "group_id": "orders-superstore",
                "status": "READY_FOR_PREFLIGHT",
                "source_summary_path": source_summary_path.as_posix(),
                "candidate_metric_view_fqn": "main.metrics.orders_candidate",
            }
        ]
    }

    summaries = summarize_semantic_groups(groups_index)

    assert summaries == [
        {
            "group_index": 0,
            "group_name": "orders-superstore",
            "status": "READY_FOR_PREFLIGHT",
            "will_migrate": True,
            "datasources": [{"name": "Orders", "file": "superstore-orders.tdsx", "role": "PRIMARY", "data": "—"}],
            "target_tables": ["main.superstore.orders"],
            "candidate_metric_view": "main.metrics.orders_candidate",
        }
    ]
