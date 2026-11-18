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


def test_unrelated_embedded_extracts_do_not_group():
    assets = [
        {
            "asset_id": asset_id,
            "datasources": [
                {
                    "fingerprint": "shared-generic-fingerprint",
                    "tables": ["[Extract].[Extract]"],
                    "connections": [{"class": "hyper"}],
                }
            ],
        }
        for asset_id in ("finance", "sales")
    ]

    groups = group_assets(assets)

    assert len(groups) == 2


def test_unrelated_excel_sheet_names_do_not_group():
    assets = [
        {
            "asset_id": asset_id,
            "datasources": [
                {
                    "fingerprint": fingerprint,
                    "tables": ["[Sheet1$]"],
                    "connections": [{"class": "excel-direct"}, {"class": "hyper", "dbname": extract}],
                }
            ],
        }
        for asset_id, fingerprint, extract in (
            ("hospital", "hospital-fingerprint", "hospital.hyper"),
            ("sales", "sales-fingerprint", "sales.hyper"),
        )
    ]

    groups = group_assets(assets)

    assert len(groups) == 2


def test_related_local_extracts_group_by_physical_field_overlap():
    shared_fields = [
        "Order ID", "Order Date", "Customer ID", "Customer Name", "Product ID", "Product Name",
        "Category", "Sub-Category", "Sales", "Profit", "Quantity", "Discount", "Region", "State",
    ]
    assets = [
        {
            "asset_id": asset_id,
            "datasources": [
                {
                    "fingerprint": fingerprint,
                    "tables": ["[Extract].[Extract]"],
                    "connections": [{"class": "hyper", "dbname": extract}],
                    "fields": [{"name": field} for field in [*shared_fields, unique_field]],
                }
            ],
        }
        for asset_id, fingerprint, extract, unique_field in (
            ("superstore-a", "one", "one.hyper", "Ship Mode"),
            ("superstore-b", "two", "two.hyper", "Return Reason"),
        )
    ]

    groups = group_assets(assets)

    assert len(groups) == 1
    assert groups[0]["similarity_edges"][0]["shared_field_count"] == len(shared_fields)


def test_small_generic_field_overlap_does_not_group_local_extracts():
    assets = [
        {
            "asset_id": asset_id,
            "datasources": [
                {
                    "fingerprint": asset_id,
                    "tables": ["[Extract].[Extract]"],
                    "connections": [{"class": "hyper"}],
                    "fields": [{"name": field} for field in ["Date", "Amount", "Region", unique_field]],
                }
            ],
        }
        for asset_id, unique_field in (("finance", "Account"), ("sales", "Product"))
    ]

    assert len(group_assets(assets)) == 2
