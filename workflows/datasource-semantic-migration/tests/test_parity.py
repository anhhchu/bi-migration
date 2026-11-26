from datasource_semantic_migration.parity import (
    bind_columns,
    choose_dimensions,
    compare_results,
    comparison_queries,
    measure_outcomes,
    parity_summary,
    plan_measures,
    shadow_metric_view,
    shadow_source_sql,
    source_lineage,
)

METRIC_VIEW = {
    "source": "SELECT s.net / 100.0 AS sales, c.state_code AS state_province, s.region AS region, s.days AS days FROM t s",
    "joins": [{"name": "c", "source": "main.x.c"}],
    "dimensions": [{"name": "Region", "expr": "region"}, {"name": "State", "expr": "source.state_province"}],
    "measures": [
        {"name": "Sales", "expr": "SUM(sales)"},
        {"name": "Days", "expr": "SUM(days)"},
        {"name": "Forecast", "expr": "SUM(sales) * 2"},
    ],
}
OUTPUTS = [("sales", "double"), ("state_province", "string"), ("region", "string"), ("days", "int")]
EXTRACT = ["Sales", "State", "Region"]


def test_lineage_reads_plain_select_items():
    assert source_lineage(METRIC_VIEW["source"]) == {"state_province": "state_code", "region": "region", "days": "days"}


def test_columns_bind_by_name_named_item_and_column_mapping():
    binding = bind_columns(OUTPUTS, EXTRACT, metric_view=METRIC_VIEW)
    assert binding["bound"] == {"sales": "Sales", "state_province": "State", "region": "Region"}
    assert binding["how"]["state_province"] == "named item"
    assert binding["unbound"] == ["days"]

    without_dimension = {**METRIC_VIEW, "dimensions": [{"name": "Region", "expr": "region"}]}
    mapped = bind_columns(OUTPUTS, EXTRACT, metric_view=without_dimension, column_mappings={"State": "state_code"})
    assert mapped["bound"]["state_province"] == "State" and mapped["how"]["state_province"] == "column mapping"


def test_shadow_view_keeps_the_candidate_but_reads_the_extract():
    binding = bind_columns(OUTPUTS, EXTRACT, metric_view=METRIC_VIEW)
    sql = shadow_source_sql("cat.stage.bim_x_1", OUTPUTS, binding)
    assert sql == (
        "SELECT `Sales` AS `sales`, `State` AS `state_province`, `Region` AS `region`, CAST(NULL AS int) AS `days` "
        "FROM cat.stage.bim_x_1"
    )
    shadow = shadow_metric_view(METRIC_VIEW, sql)
    assert "joins" not in shadow and shadow["measures"] == METRIC_VIEW["measures"]
    assert METRIC_VIEW["joins"]


def _reference(source):
    if source["display_name"] == "Forecast":
        raise ValueError("function FORECAST is not supported yet")
    return "SUM(`Sales`)", "SUM"


def test_plans_say_why_a_measure_cannot_be_compared():
    binding = bind_columns(OUTPUTS, EXTRACT, metric_view=METRIC_VIEW)
    sources = [{"display_name": "Sales"}, {"display_name": "Days"}, {"display_name": "Forecast"}]
    plans = {
        plan["measure"]: plan
        for plan in plan_measures(
            metric_view=METRIC_VIEW, source_measures=sources, output_columns=OUTPUTS, binding=binding, reference_for=_reference
        )
    }
    assert plans["Sales"]["comparable"] and plans["Sales"]["reference_sql"] == "SUM(`Sales`)"
    assert "days not found in the extract" in plans["Days"]["reason"]
    assert "FORECAST is not supported" in plans["Forecast"]["reason"]


def test_low_cardinality_dimensions_are_chosen():
    dimensions = [{"dimension": "Region", "extract_column": "Region"}, {"dimension": "Order", "extract_column": "Order"}]
    assert choose_dimensions(dimensions, {"Region": 4, "Order": 5000}) == [dimensions[0]]


def test_comparison_queries_batch_every_measure():
    plans = [{"measure": "Sales", "comparable": True, "reference_sql": "SUM(`Sales`)", "family": "SUM"}]
    queries = comparison_queries(shadow_view="v", extract_table="x", plans=plans, dimension={"dimension": "Region", "extract_column": "Region"})
    assert queries["candidate"] == "SELECT `Region` AS g, MEASURE(`Sales`) AS m0 FROM v GROUP BY ALL"
    assert queries["reference"] == "SELECT `Region` AS g, SUM(`Sales`) AS m0 FROM x GROUP BY ALL"


def test_values_compare_exactly_within_tolerance_or_not():
    plans = [
        {"measure": "Sales", "comparable": True, "family": "SUM"},
        {"measure": "Orders", "comparable": True, "family": "ROW_COUNT"},
        {"measure": "Ratio", "comparable": True, "family": "CALCULATION"},
    ]
    candidate = [{"g": "East", "m0": 100.0, "m1": 10, "m2": 0.333333}, {"g": "West", "m0": 50.0, "m1": 6, "m2": None}]
    reference = [{"g": "East", "m0": 100.0, "m1": 10, "m2": 0.3333334}, {"g": "West", "m0": 50.0, "m1": 5, "m2": None}]
    results = compare_results(plans, candidate, reference, grouped_by="Region")
    assert results["Sales"]["status"] == "EXACT"
    assert results["Ratio"]["status"] == "WITHIN_TOLERANCE"
    assert results["Orders"]["status"] == "MISMATCH"
    assert results["Orders"]["differences"] == [{"group": "West", "candidate": 6, "reference": 5}]

    outcomes = {item["measure"]: item["status"] for item in measure_outcomes(plans + [{"measure": "Days", "comparable": False, "reason": "x"}], [results])}
    assert outcomes == {"Sales": "PASS_EXACT", "Orders": "FAILED_VALUE", "Ratio": "PASS_WITH_TOLERANCE", "Days": "NOT_COMPARABLE"}
    summary = parity_summary(measure_outcomes(plans, [results]), available=True)
    assert summary["status"] == "MISMATCH" and summary["compared_count"] == 3


def test_extract_columns_get_unique_delta_safe_names():
    from datasource_semantic_migration.parity import safe_column_names

    assert safe_column_names(["Business Unit", "Sub-Category", "Sub Category", "2024 Target", "Profit (bin)"]) == {
        "Business Unit": "business_unit",
        "Sub-Category": "sub_category",
        "Sub Category": "sub_category_2",
        "2024 Target": "c_2024_target",
        "Profit (bin)": "profit_bin",
    }
