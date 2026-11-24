import pytest

from datasource_semantic_migration.gate import build_gate, infer_additivity


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("SUM(trxn_amount_major) FILTER (WHERE `Current Period T/F`)", "additive"),
        ("COUNT(1)", "additive"),
        ("(MEASURE(`Current Value`) - MEASURE(`Prior Value`)) / MEASURE(`Prior Value`)", "non_additive"),
        ("SUM(profit) / SUM(sales)", "non_additive"),
        ("COUNT(DISTINCT customer_id)", "non_additive"),
        ("AVG(days_to_ship)", "non_additive"),
        ("MAX(order_date)", "semi_additive"),
        ("CASE WHEN MEASURE(`% MOM Value`) > 0 THEN 'Increase' ELSE 'Decline' END", "label"),
        ("MEASURE(`Current Value`) + MEASURE(`Current Volume`)", "derived"),
        ("days_to_ship", "unknown"),
    ],
)
def test_additivity_is_inferred_from_the_expression(expression, expected):
    assert infer_additivity(expression)["additivity"] == expected


def gate(**overrides):
    arguments = {
        "has_candidate": True,
        "repair": {"status": "READY", "coverage_after": {"translated_metric_count": 2, "source_business_metric_count": 2}},
        "scorecard_evaluation": {
            "scorecards": [{"status": "PASS_SEMANTIC_ONLY"}, {"status": "PASS_SEMANTIC_ONLY"}],
            "blocking_findings": [],
            "relationship_blockers": [],
        },
        "metric_view": {"measures": [{"name": "Sales", "expr": "SUM(sales)"}]},
        "group_mapping": {"table_mappings": [{"target": {"table": "main.gold.orders", "grain": "one row per order line"}}]},
        "untranslated": [],
        "review_actions": [],
    }
    return build_gate(**{**arguments, **overrides})


def statuses(result):
    return {stage["key"]: stage["status"] for stage in result["stages"]}


def test_clean_candidate_is_ready_for_parity_and_never_claims_parity():
    result = gate()

    assert result["status"] == "READY_FOR_PARITY"
    assert statuses(result) == {
        "translation": "PASS",
        "contract": "PASS",
        "design": "PASS",
        "parity": "NOT_RUN",
        "performance": "NOT_RUN",
        "certify": "NOT_RUN",
    }


def test_blocking_measure_blocks_at_design_with_a_next_step():
    result = gate(
        repair={"status": "NO_PROGRESS", "coverage_after": {}},
        scorecard_evaluation={
            "scorecards": [{"status": "FAILED_SEMANTICS"}],
            "blocking_findings": [{"source_name": "Profit Ratio"}],
            "relationship_blockers": [],
        },
    )

    assert result["status"] == "BLOCKED"
    assert result["headline"] == "Blocked at Design."
    assert "Profit Ratio" in result["next_step"]


def test_missing_grain_and_review_actions_need_review():
    result = gate(
        group_mapping={"table_mappings": [{"target": {"table": "main.gold.orders"}}]},
        review_actions=[{"priority": "REVIEW", "title": "Check how these measures are totalled"}],
    )

    assert result["status"] == "NEEDS_REVIEW"
    assert statuses(result)["contract"] == "WARN"
    assert statuses(result)["design"] == "WARN"
    assert "main.gold.orders" in result["next_step"]


def test_pending_checks_are_not_reported_as_ready():
    assert gate(scorecard_evaluation=None)["status"] == "CHECKS_PENDING"


def test_missing_candidate_blocks_at_translation():
    result = gate(has_candidate=False)

    assert result["status"] == "BLOCKED"
    assert statuses(result)["translation"] == "FAIL"
