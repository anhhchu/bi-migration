from datasource_semantic_migration.metric_repair import (
    apply_metric_patch,
    build_deterministic_patch,
    create_metric_view_sql,
    evaluate_candidate,
    evaluate_progress,
    target_lineage,
)


def measure(name, *, status="READY", dependencies=None):
    return {
        "measure_id": f"measure-{name}",
        "display_name": name,
        "status": status,
        "aggregation": "SOURCE_DEFAULT" if status == "NEEDS_AGGREGATION_COMPILATION" else "SUM",
        "dependencies": dependencies or [],
    }


def test_evaluation_confirms_aggregate_and_blocks_unmapped_external_metric():
    source = {
        "measures": [
            measure("Sales"),
            measure("Days to Ship", status="NEEDS_AGGREGATION_COMPILATION"),
            measure("Sales above Target?", dependencies=[{"kind": "external_field"}]),
        ]
    }
    target = {
        "source": "SELECT * FROM main.gold.orders",
        "measures": [
            {"name": "Sales", "expr": "SUM(sales)"},
            {"name": "Days to Ship", "expr": "SUM(days_to_ship)"},
        ],
    }

    evaluation = evaluate_candidate(
        source_metric_irs=[source],
        metric_view=target,
        target_profile={"relationships": []},
        query_results={"sales": {"status": "PASS"}, "days to ship": {"status": "PASS"}},
    )

    assert evaluation["readiness"] == "BLOCKED_EVIDENCE"
    assert evaluation["coverage"]["translation_coverage"] == 2 / 3
    assert evaluation["needs_genie"] is False
    assert next(item for item in evaluation["scorecards"] if item["source_name"] == "Days to Ship")[
        "status"
    ] == "PASS_SEMANTIC_ONLY"


def test_missing_supported_measure_routes_once_to_genie_patch():
    evaluation = evaluate_candidate(
        source_metric_irs=[{"measures": [measure("Gross Margin")]}],
        metric_view={"source": "SELECT * FROM main.gold.orders", "measures": []},
        target_profile={"relationships": []},
    )

    assert evaluation["readiness"] == "NEEDS_REPAIR"
    assert evaluation["needs_genie"] is True
    assert evaluation["scorecards"][0]["repair_route"] == "GENIE_PATCH"


def test_queryability_does_not_count_not_run_as_pass():
    evaluation = evaluate_candidate(
        source_metric_irs=[{"measures": [measure("Sales")]}],
        metric_view={"source": "SELECT * FROM main.gold.orders", "measures": [{"name": "Sales", "expr": "SUM(sales)"}]},
        target_profile={"relationships": []},
        query_results={},
    )

    assert evaluation["coverage"]["measure_queryability"] == 0.0
    assert evaluation["coverage"]["query_not_run_count"] == 1
    assert evaluation["gates"]["measure_queryability"] is False


def test_progress_requires_coverage_or_blocker_improvement():
    before = {
        "readiness": "NEEDS_REPAIR",
        "coverage": {
            "translated_metric_count": 6,
            "governed_metric_count": 6,
            "evidenced_metric_count": 5,
            "query_pass_count": 6,
        },
        "blocking_findings": [{"metric_id": "a"}],
        "relationship_blockers": [],
    }
    unchanged = evaluate_progress(before, before)
    improved = evaluate_progress(
        before,
        {
            **before,
            "coverage": {**before["coverage"], "evidenced_metric_count": 6},
            "blocking_findings": [],
        },
    )

    assert unchanged["measurable_improvement"] is False
    assert improved["measurable_improvement"] is True


def test_deterministic_patch_wraps_only_bare_row_expression():
    target = {"measures": [{"name": "Days to Ship", "expr": "days_to_ship"}]}
    evaluation = evaluate_candidate(
        source_metric_irs=[{"measures": [measure("Days to Ship", status="NEEDS_AGGREGATION_COMPILATION")]}],
        metric_view=target,
        target_profile={"relationships": []},
    )

    patch = build_deterministic_patch(evaluation, target)
    updated = apply_metric_patch(target, patch)

    assert patch["operations"] == [
        {
            "op": "set_measure_expression",
            "measure": "Days to Ship",
            "before": "days_to_ship",
            "after": "SUM(days_to_ship)",
            "failure_codes": ["AGGREGATION_MISMATCH"],
        }
    ]
    assert updated["measures"][0]["expr"] == "SUM(days_to_ship)"


def test_lineage_and_create_sql_are_catalog_safe():
    document = {
        "version": 1.1,
        "source": "SELECT * FROM `main`.`gold`.`orders` JOIN main.gold.customers USING (customer_id)",
        "measures": [{"name": "Sales", "expr": "SUM(sales)"}],
    }

    assert target_lineage(document) == ["main.gold.customers", "main.gold.orders"]
    sql = create_metric_view_sql("main.metrics.sales", document)
    assert sql.startswith("CREATE OR REPLACE VIEW `main`.`metrics`.`sales` WITH METRICS LANGUAGE YAML AS $$")
