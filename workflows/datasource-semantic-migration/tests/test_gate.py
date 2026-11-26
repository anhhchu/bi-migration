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


def test_unmet_repair_gates_keep_the_gate_from_reporting_ready():
    result = gate(
        scorecard_evaluation={
            "scorecards": [{"status": "PASS_SEMANTIC_ONLY"}],
            "blocking_findings": [],
            "relationship_blockers": [],
            "gates": {"overall_metric_translation_coverage": False, "measure_queryability": True},
        }
    )

    design = next(stage for stage in result["stages"] if stage["key"] == "design")
    assert result["status"] == "NEEDS_REVIEW"
    assert design["status"] == "WARN"
    assert "overall metric translation coverage" in design["summary"]


def _parity(statuses, reason=None):
    from datasource_semantic_migration.parity import parity_summary

    outcomes = [
        {"measure": f"M{index}", "status": status, "reason": reason, "checks": [{"status": "MISMATCH", "grouped_by": None, "differences": [{"group": "total", "candidate": 1, "reference": 2}], "difference_count": 1}] if status == "FAILED_VALUE" else []}
        for index, status in enumerate(statuses)
    ]
    return {"summary": parity_summary(outcomes, available=bool(outcomes), reason=reason), "outcomes": outcomes}


def test_parity_stage_reports_the_number_check():
    def parity_stage(parity):
        return next(stage for stage in gate(parity=parity)["stages"] if stage["key"] == "parity")

    assert parity_stage(None)["status"] == "NOT_RUN"
    assert parity_stage(_parity(["PASS_EXACT", "PASS_WITH_TOLERANCE"]))["status"] == "PASS"
    assert gate(parity=_parity(["PASS_EXACT"]))["status"] == "READY_FOR_SIGN_OFF"
    assert parity_stage(_parity(["PASS_EXACT", "NOT_COMPARABLE"]))["status"] == "WARN"
    failed = gate(parity=_parity(["PASS_EXACT", "FAILED_VALUE"]))
    assert failed["status"] == "BLOCKED" and "differ from the Tableau extract" in failed["headline"] + str(failed["stages"])
    assert parity_stage(_parity([], reason="no extract"))["status"] == "NOT_RUN"
