import pytest

from datasource_semantic_migration.sources.tableau.formula_sql import FormulaTranslator, Untranslatable

IR = {
    "fields": [
        {"field_id": "[Amount]", "name": "Amount", "remote_name": "Amount"},
        {"field_id": "[Metric Type]", "name": "Metric Type", "remote_name": "Metric Type"},
        {"field_id": "[Order Date]", "name": "Order Date", "remote_name": "Order Date"},
        {"field_id": "[Customer]", "name": "Customer", "remote_name": "Customer Name"},
    ],
    "calculations": [
        {"calculation_id": "[Calculation_1]", "name": "Actual", "formula": "if [Metric Type]='Actual' THEN [Amount] END"},
        {"calculation_id": "[Calculation_2]", "name": "Budget", "formula": "IF [Metric Type]=\"Budget\" THEN [Amount] END"},
        {"calculation_id": "[Calculation_3]", "name": "Gap", "formula": "SUM([Calculation_1]) - SUM([Calculation_2])"},
        {"calculation_id": "[Order Date]", "name": "Order Date", "formula": "DATEADD('year', 4, [Order Date])"},
    ],
    "parameters": [
        {"parameter_id": "[Parameter 1]", "name": "Unit", "default_value": '"Software"'},
        {"parameter_id": "[Parameter 2]", "name": "Year", "default_value": "2024"},
    ],
}
COLUMNS = ["Amount", "Metric Type", "Order Date", "Customer Name"]


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
        ("DATEDIFF('day', [Order Date], TODAY())", "DATEDIFF(DAY, (DATEADD(YEAR, 4, `Order Date`)), CURRENT_DATE())"),
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
