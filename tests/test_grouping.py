from bi_migration.grouping import group_assets
from bi_migration.tableau import parse_tableau


def test_group_assets_by_shared_table():
    assets = [
        parse_tableau("tests/fixtures/tableau/sales_a.twb"),
        parse_tableau("tests/fixtures/tableau/sales_b.twb"),
    ]
    groups = group_assets(assets)
    assert len(groups) == 1
    assert groups[0]["assets"] == ["sales_a", "sales_b"]
    assert "table:[dbo].[fact_sales]" in groups[0]["shared_dependencies"]
