from datasource_semantic_migration.metric_repair import (
    apply_metric_patch,
    build_deterministic_patch,
    create_metric_view_sql,
    evaluate_candidate,
    evaluate_progress,
    import_exclusions,
    next_attempt_decision,
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


def test_measures_composed_from_other_measures_count_as_aggregated():
    # Regression: Card Payment Transactions run flagged these correct translations as AGGREGATION_MISMATCH.
    names = ["% MOM Value Color", "Select Current Measure", "Approved Count"]
    target = {
        "measures": [
            {"name": "% MOM Value", "expr": "SUM(value)"},
            {
                "name": "% MOM Value Color",
                "expr": "CASE WHEN MEASURE(`% MOM Value`) > 0 THEN 'Increase' ELSE 'Decline' END",
            },
            {
                "name": "Select Current Measure",
                "expr": "CASE WHEN select_measure = 'Value' THEN MEASURE(`Current Value`) ELSE MEASURE(`Current Volume`) END",
            },
            {"name": "Approved Count", "expr": "COUNT_IF(status = 'APPROVED')"},
        ]
    }
    evaluation = evaluate_candidate(
        source_metric_irs=[
            {"measures": [measure(name, status="NEEDS_AGGREGATION_COMPILATION") for name in names]}
        ],
        metric_view=target,
        target_profile={"relationships": []},
    )

    statuses = {item["source_name"]: item["status"] for item in evaluation["scorecards"]}
    assert all(statuses[name] == "PASS_SEMANTIC_ONLY" for name in names), statuses


PROFILE = {"relationships": []}
ORDERS = "SELECT * FROM main.gold.orders"


def test_measure_left_out_by_import_waits_for_a_person_and_skips_genie():
    evaluation = evaluate_candidate(
        source_metric_irs=[{"measures": [measure("Sales"), measure("Rank")]}],
        metric_view={"source": ORDERS, "measures": [{"name": "Sales", "expr": "SUM(sales)"}]},
        target_profile=PROFILE,
        query_results={"sales": {"status": "PASS"}},
        excluded_measures=["rank"],
    )

    rank = next(item for item in evaluation["scorecards"] if item["source_name"] == "Rank")
    assert rank["status"] == "EXCLUDED_BY_IMPORT"
    assert rank["repair_route"] == "HUMAN_DECISION"
    assert evaluation["needs_genie"] is False
    assert evaluation["blocking_findings"] == []
    # The exclusion no longer counts against evidence; only translation coverage shows it.
    assert evaluation["coverage"]["evidence_coverage"] == 1.0
    assert evaluation["coverage"]["governed_disposition_coverage"] == 1.0
    assert evaluation["coverage"]["translation_coverage"] == 0.5
    assert evaluation["excluded_measures"] == ["rank"]


def test_genie_is_not_requested_when_a_mapping_blocker_stops_the_attempt():
    evaluation = evaluate_candidate(
        source_metric_irs=[
            {"measures": [measure("Gross Margin"), measure("Target", dependencies=[{"kind": "external_field"}])]}
        ],
        metric_view={"source": ORDERS, "measures": []},
        target_profile=PROFILE,
    )

    assert evaluation["readiness"] == "BLOCKED_EVIDENCE"
    assert evaluation["needs_genie"] is False


def test_missing_aggregate_on_a_non_column_expression_goes_to_genie():
    evaluation = evaluate_candidate(
        source_metric_irs=[{"measures": [measure("Late Orders", status="NEEDS_AGGREGATION_COMPILATION")]}],
        metric_view={"source": ORDERS, "measures": [{"name": "Late Orders", "expr": "CASE WHEN late THEN 1 END"}]},
        target_profile=PROFILE,
        query_results={"late orders": {"status": "PASS"}},
    )

    assert evaluation["scorecards"][0]["repair_route"] == "GENIE_PATCH"
    assert evaluation["needs_genie"] is True
    assert build_deterministic_patch(evaluation, {"measures": []})["operations"] == []


def test_deterministic_patch_never_wraps_unquoted_names_with_spaces():
    evaluation = {
        "scorecards": [
            {"failure_codes": ["AGGREGATION_MISMATCH"], "target": {"name": "Margin", "expr": "profit margin"}},
            {"failure_codes": ["AGGREGATION_MISMATCH"], "target": {"name": "Cost", "expr": "`unit cost`"}},
        ]
    }

    operations = build_deterministic_patch(evaluation, {"measures": []})["operations"]

    assert [item["after"] for item in operations] == ["SUM(`unit cost`)"]


def _finding(metric_id, route):
    return {"metric_id": metric_id, "repair_route": route}


def test_retry_stops_when_genie_already_saw_every_remaining_failure():
    before = {
        "failure_signature": "a",
        "blocking_findings": [_finding("A", "DETERMINISTIC_METRIC_PATCH"), _finding("B", "GENIE_PATCH")],
    }
    after = {"failure_signature": "b", "blocking_findings": [_finding("B", "GENIE_PATCH")]}

    decision = next_attempt_decision(before, after, genie_ran=True)

    assert decision["retry"] is False
    assert "Genie already saw" in decision["reason"]
    assert next_attempt_decision(before, after, genie_ran=False)["retry"] is True


def test_retry_stops_when_the_same_failures_remain():
    findings = [_finding("B", "GENIE_PATCH")]
    decision = next_attempt_decision(
        {"failure_signature": "same", "blocking_findings": findings},
        {"failure_signature": "same", "blocking_findings": findings},
        genie_ran=False,
    )

    assert decision["retry"] is False


def test_import_exclusions_reads_every_field_name(tmp_path):
    path = tmp_path / "importbi-result.json"
    path.write_text(
        '{"items_not_translated": [{"name": "Rank, Index", "reason": "Table calculation"}, {"name": "Flag", "reason": "UI"}]}',
        encoding="utf-8",
    )

    assert import_exclusions(path) == ["Rank", "Index", "Flag"]
    assert import_exclusions(tmp_path / "missing.json") == []
