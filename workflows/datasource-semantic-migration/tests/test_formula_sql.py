import pytest

from datasource_semantic_migration.sources.tableau.formula_sql import FormulaTranslator, Untranslatable

IR = {
    "fields": [
        {"field_id": "[Amount]", "name": "Amount", "remote_name": "Amount"},
        {"field_id": "[Metric Type]", "name": "Metric Type", "remote_name": "Metric Type"},
        {"field_id": "[Order Date]", "name": "Order Date", "remote_name": "Order Date", "datatype": "date"},
        {"field_id": "[Ship Date]", "name": "Ship Date", "remote_name": "Ship Date", "datatype": "date"},
        {"field_id": "[Customer]", "name": "Customer", "remote_name": "Customer Name"},
    ],
    "calculations": [
        {"calculation_id": "[Calculation_1]", "name": "Actual", "formula": "if [Metric Type]='Actual' THEN [Amount] END"},
        {"calculation_id": "[Calculation_2]", "name": "Budget", "formula": "IF [Metric Type]=\"Budget\" THEN [Amount] END"},
        {"calculation_id": "[Calculation_3]", "name": "Gap", "formula": "SUM([Calculation_1]) - SUM([Calculation_2])"},
        {"calculation_id": "[Order Date]", "name": "Order Date", "datatype": "date", "formula": "DATEADD('year', 4, [Order Date])"},
    ],
    "parameters": [
        {"parameter_id": "[Parameter 1]", "name": "Unit", "default_value": '"Software"'},
        {"parameter_id": "[Parameter 2]", "name": "Year", "default_value": "2024"},
        {"parameter_id": "[Parameter 4]", "name": "Minimum Date", "datatype": "date", "default_value": "#2021-10-01#"},
    ],
}
COLUMNS = ["Amount", "Metric Type", "Order Date", "Ship Date", "Customer Name"]


@pytest.fixture
def translator():
    return FormulaTranslator(IR, COLUMNS)


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("[Calculation_1]", "(CASE WHEN `Metric Type` = 'Actual' THEN `Amount` END)"),
        ("ZN(SUM([Amount]))", "COALESCE(SUM(`Amount`), 0)"),
        ("COUNTD([Customer])", "COUNT(DISTINCT `Customer Name`)"),
        ("IIF([Amount] > 0, 1, 0)", "CASE WHEN `Amount` > 0 THEN 1 ELSE 0 END"),
        ("[Metric Type] == 'Actual' AND [Amount] >= 10", "`Metric Type` = 'Actual' AND `Amount` >= 10"),
        ("[Parameters].[Parameter 1] = 'x'", "'Software' = 'x'"),
        # [Order Date] is replaced by a calculation of the same name, so it means the shifted date, as in Tableau.
        ("DATEDIFF('day', [Order Date], TODAY())", "CAST(DATEDIFF(DAY, (DATEADD(YEAR, 4, `Order Date`)), CURRENT_DATE()) AS INT)"),
        # Tableau's date - date is a number of days; Databricks would return an interval.
        ("[Ship Date] - [Order Date]", "CAST(DATEDIFF(DAY, (DATEADD(YEAR, 4, `Order Date`)), `Ship Date`) AS INT)"),
        # date - number stays date arithmetic, with DATEDIFF cast to INT for it.
        (
            "[Parameters].[Parameter 4] - (DATEDIFF('day', [Ship Date], [Ship Date]) + 1)",
            "TO_DATE('2021-10-01') - (CAST(DATEDIFF(DAY, `Ship Date`, `Ship Date`) AS INT) + 1)",
        ),
        ("MAX([Amount], 0)", "GREATEST(`Amount`, 0)"),
        ("// a comment\nSUM([Amount])", "SUM(`Amount`)"),
    ],
)
def test_common_formulas_translate(translator, formula, expected):
    assert translator.translate(formula) == expected


@pytest.mark.parametrize(
    ("formula", "reason"),
    [
        ("{ FIXED [Customer] : SUM([Amount]) }", "LOD"),
        ("RUNNING_SUM(SUM([Amount]))", "table calculation"),
        ("[Other Source].[Amount]", "another datasource"),
        ("REGEXP_MATCH([Customer], 'a')", "not supported"),
        ("[Unknown Field]", "unknown field"),
    ],
)
def test_unsupported_formulas_are_refused_with_a_reason(translator, formula, reason):
    with pytest.raises(Untranslatable, match=reason):
        translator.translate(formula)


def test_calculation_replacing_a_field_reads_the_field_inside_its_formula(translator):
    assert translator.translate("[Order Date]") == "(DATEADD(YEAR, 4, `Order Date`))"


def _measure(formula, semantic_type):
    return {"expression": {"kind": "source_calculation", "formula": formula, "classification": {"semantic_type": semantic_type}}}


def test_measure_references_total_row_level_calculations_once(translator):
    assert translator.measure_reference(_measure("[Calculation_1]", "ROW_LEVEL"))[0] == (
        "SUM((CASE WHEN `Metric Type` = 'Actual' THEN `Amount` END))"
    )
    # Aggregated only through the calculations it references: not wrapped in SUM again.
    assert translator.measure_reference(_measure("[Calculation_3]", "ROW_LEVEL"))[0].startswith("(SUM(")
    field = {"expression": {"kind": "field_aggregate", "field_id": "[Amount]"}, "aggregation": "AVG"}
    assert translator.measure_reference(field) == ("AVG(`Amount`)", "AVG")
    with pytest.raises(Untranslatable, match="LOD"):
        translator.measure_reference(_measure("x", "LOD_FIXED"))


def test_formulas_name_fields_by_id_even_when_a_calculation_has_the_same_caption():
    # Real Superstore pattern: a calculation captioned "Order Date" shifts the field [Order Date].
    ir = {
        "fields": [
            {"field_id": "[Order Date]", "name": "Order Date", "datatype": "date"},
            {"field_id": "[Ship Date]", "name": "Ship Date", "datatype": "date"},
        ],
        "calculations": [
            {"calculation_id": "[Calculation_9]", "name": "Order Date", "datatype": "date", "formula": "[Order Date]+365+365+365+365"},
            {"calculation_id": "[Calculation_7]", "name": "Days to Ship", "datatype": "integer", "formula": "[Ship Date]-[Order Date]"},
            {"calculation_id": "[Calculation_5]", "name": "In Window", "formula": "[Calculation_9] >= #2021-10-01#"},
        ],
        "parameters": [],
    }
    translator = FormulaTranslator(ir, ["Order Date", "Ship Date"])

    # Days to Ship reads the field, not the shifted calculation.
    assert translator.translate("[Calculation_7]") == "(CAST(DATEDIFF(DAY, `Order Date`, `Ship Date`) AS INT))"
    # The shift is applied once.
    assert translator.translate("[Calculation_9]") == "(`Order Date` + 365 + 365 + 365 + 365)"
