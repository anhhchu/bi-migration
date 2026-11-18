from bi_migration.preflight import build_readiness_report


def test_readiness_blocks_unresolved_relationships():
    mapping = {
        "status": "approved",
        "fields": [],
        "relationships": [{
            "datasource": "sales",
            "source": {"left_table": "Orders", "right_table": "Customers"},
            "assets": ["workbook"],
            "status": "unresolved",
        }],
    }

    report = build_readiness_report([], [], mapping, [], [])

    assert not report["ready"]
    assert report["coverage"]["unresolved_relationships"] == 1
    assert report["issues"] == [{"code": "unresolved_relationships", "count": 1, "severity": "error"}]
