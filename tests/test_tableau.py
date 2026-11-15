import zipfile

from bi_migration.tableau import parse_tableau


def test_parse_twb_extracts_dependencies():
    asset = parse_tableau("tests/fixtures/tableau/sales_a.twb")
    assert asset["dashboards"][0]["worksheets"] == ["Regional Sales"]
    assert asset["worksheets"][0]["datasources"] == ["sales"]
    assert asset["datasources"][0]["tables"] == ["[dbo].[fact_sales]"]
    assert asset["datasources"][0]["fields"][2]["calculation"]


def test_parse_twbx(tmp_path):
    package = tmp_path / "sales.twbx"
    with zipfile.ZipFile(package, "w") as archive:
        archive.write("tests/fixtures/tableau/sales_a.twb", "workbooks/sales.twb")
    asset = parse_tableau(package)
    assert asset["packaged_workbook"] == "workbooks/sales.twb"
    assert asset["asset_id"] == "sales"
