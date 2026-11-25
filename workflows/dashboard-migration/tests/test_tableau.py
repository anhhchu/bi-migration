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


def test_parse_twb_extracts_physical_joins(tmp_path):
    workbook = tmp_path / "joined.twb"
    workbook.write_text("""<?xml version=\"1.0\"?>
<workbook><datasources><datasource name=\"sales\"><connection>
  <relation type=\"join\" join=\"left\">
    <relation type=\"table\" table=\"[Orders]\" />
    <relation type=\"table\" table=\"[Customers]\" />
    <clause type=\"join\"><expression op=\"=\"><expression op=\"[Orders].[Customer ID]\"/><expression op=\"[Customers].[Customer ID]\"/></expression></clause>
  </relation>
</connection></datasource></datasources></workbook>""", encoding="utf-8")

    relationship = parse_tableau(workbook)["datasources"][0]["relationships"][0]

    assert relationship == {
        "left_table": "Orders",
        "right_table": "Customers",
        "join_type": "left",
        "condition": "([Orders].[Customer ID] = [Customers].[Customer ID])",
        "source_kind": "physical_join",
    }


def test_parse_nested_join_uses_condition_tables(tmp_path):
    workbook = tmp_path / "nested.twb"
    workbook.write_text("""<workbook><datasources><datasource name="sales"><connection>
      <relation type="join" join="inner">
        <relation type="join" join="left">
          <relation type="table" table="[Orders$]"/><relation type="table" table="[Returns$]"/>
          <clause><expression op="="><expression op="[Orders].[Order ID]"/><expression op="[Returns].[Order ID]"/></expression></clause>
        </relation>
        <relation type="table" table="[People$]"/>
        <clause><expression op="="><expression op="[Orders].[Region]"/><expression op="[People].[Region]"/></expression></clause>
      </relation>
    </connection></datasource></datasources></workbook>""", encoding="utf-8")

    relationships = parse_tableau(workbook)["datasources"][0]["relationships"]

    assert relationships[0]["left_table"] == "Orders"
    assert relationships[0]["right_table"] == "People"
