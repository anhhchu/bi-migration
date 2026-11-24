from datasource_semantic_migration.action_items import build_action_groups


def actions(**overrides):
    arguments = {
        "scorecard_evaluation": {"scorecards": [], "blocking_findings": [], "relationship_blockers": []},
        "evaluation_findings": [],
        "business_untranslated": [],
        "approximations": [],
        "aggregation_items": [],
        "group_mapping": {"table_mappings": [{"target": {"table": "main.gold.orders", "grain": "one row per order"}}]},
        "repair": {"status": "READY"},
        "has_candidate": True,
    }
    return build_action_groups(**{**arguments, **overrides})


def by_category(result):
    return {group["category"]: [item["title"] for item in group["items"]] for group in result["groups"]}


def failed_query(name, error):
    return {"source_name": name, "failure_codes": ["MEASURE_QUERY_FAILED"], "query": {"status": "FAIL", "error": error}}


def test_card_payment_items_are_handled_automatically_not_sent_for_review():
    result = actions(
        business_untranslated=[
            {"kind": "calculation", "name": "No.", "reason": "INDEX() table calculation depends on worksheet partitioning"},
            {"kind": "group", "name": "Action groups (Action (Card Brand))", "reason": "Dashboard action sets have no semantic-layer equivalent"},
        ],
        aggregation_items=[{"name": "Current Value", "expression": "SUM(trxn_amount_major) FILTER (WHERE `Current Period T/F`)"}],
    )

    automatic_names = {name for item in result["automatic"] for name in item["names"]}
    assert automatic_names == {"No.", "Action groups (Action (Card Brand))", "Current Value"}
    assert set(by_category(result)) == {"number_checks", "sign_off"}
    assert result["blocking_count"] == 0


def test_query_errors_are_routed_by_cause():
    result = actions(
        scorecard_evaluation={
            "blocking_findings": [
                failed_query("Sales", "PERMISSION_DENIED: User does not have SELECT on table main.gold.orders"),
                failed_query("Profit", "[UNRESOLVED_COLUMN] A column `profit_amt` cannot be resolved"),
                failed_query("Margin", "[DIVIDE_BY_ZERO] Division by zero"),
            ],
            "relationship_blockers": [],
        }
    )

    categories = by_category(result)
    assert categories["access_platform"] == ["Sales"]
    assert categories["data_mapping"] == ["Profit"]
    assert categories["calculation"] == ["Margin"]
    assert result["blocking_count"] == 3


def test_every_category_explains_who_acts_and_why_a_person_is_needed():
    result = actions(
        business_untranslated=[{"kind": "filter", "name": "Region filter", "reason": "No member selection"}],
        group_mapping={"table_mappings": [{"target": {"table": "main.gold.orders"}}]},
    )

    for group in result["groups"]:
        assert group["owner"] and group["why_human"], group
    assert by_category(result)["business_definition"] == ["Region filter"]
    assert by_category(result)["data_mapping"] == ["Grain for main.gold.orders"]


def test_non_sum_aggregation_needs_a_business_decision():
    result = actions(aggregation_items=[{"name": "Days to Ship", "expression": "AVG(days_to_ship)"}])

    assert by_category(result)["business_definition"] == ["Days to Ship"]


def test_internal_terms_are_replaced_in_user_text():
    from datasource_semantic_migration.action_items import plain_language

    assert plain_language("Datasource IR has no member selection") == "the parsed Tableau datasource has no member selection"


def test_nested_aggregates_and_labels_do_not_need_review():
    result = actions(
        aggregation_items=[
            {"name": "Profit Color", "expression": "try_divide(SUM(profit), SUM(sales))"},
            {"name": "Sales arrow", "expression": "CASE WHEN SUM(sales) > 0 THEN '▲' ELSE '▼' END"},
            {"name": "Number of Records", "expression": "COUNT(*)"},
            {"name": "Left out by import", "expression": ""},
        ]
    )

    assert set(by_category(result)) == {"number_checks", "sign_off"}
    merged = next(item for item in result["automatic"] if item["title"] == "3 items")
    assert merged["names"] == ["Profit Color", "Sales arrow", "Number of Records"]


def test_measures_left_out_with_a_reason_are_not_missing_measure_failures():
    from datasource_semantic_migration.action_items import reconcile_import_exclusions

    evaluation = {
        "blocking_findings": [
            {"source_name": "Makepoint", "failure_codes": ["MISSING_TARGET_MEASURE"]},
            {"source_name": "Order Diff", "failure_codes": ["MISSING_TARGET_MEASURE"]},
        ]
    }
    untranslated = [{"items": "center, Makepoint, Makepoint PH", "reason": "map point helpers"}]

    kept = reconcile_import_exclusions(evaluation, untranslated)["blocking_findings"]
    assert [item["source_name"] for item in kept] == ["Order Diff"]


def test_unmapped_datasource_is_reported_once():
    result = actions(
        scorecard_evaluation={
            "blocking_findings": [{"source_name": "Sales above Target?", "failure_codes": ["EXTERNAL_DATASOURCE_UNMAPPED"]}],
            "relationship_blockers": [],
        },
        business_untranslated=[{"items": "Sales above Target?", "reason": "references Sales Target in another data source"}],
    )

    assert by_category(result)["data_mapping"] == ["Sales above Target?"]
    assert "business_definition" not in by_category(result)
