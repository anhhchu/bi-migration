from __future__ import annotations


def build_inventory_preflight(
    assets: list[dict],
    inventory_errors: list[dict],
    run_manifest: dict,
) -> dict:
    asset_results = []
    source_tables = set()
    physical_fields = 0
    calculated_fields = 0
    datasource_count = 0
    dashboard_count = 0
    worksheet_count = 0
    relationship_count = 0

    for asset in assets:
        datasources = asset.get("datasources", [])
        dashboards = asset.get("dashboards", [])
        worksheets = asset.get("worksheets", [])
        datasource_count += len(datasources)
        dashboard_count += len(dashboards)
        worksheet_count += len(worksheets)
        for datasource in datasources:
            source_tables.update(datasource.get("tables", []))
            relationship_count += len(datasource.get("relationships", []))
            for field in datasource.get("fields", []):
                if field.get("calculation"):
                    calculated_fields += 1
                elif field.get("type") == "physical":
                    physical_fields += 1
        asset_results.append(
            {
                "asset_id": asset.get("asset_id"),
                "source_file": asset.get("source_file"),
                "datasource_count": len(datasources),
                "dashboard_count": len(dashboards),
                "worksheet_count": len(worksheets),
                "relationship_count": sum(len(item.get("relationships", [])) for item in datasources),
                "status": "inventoried",
                "warnings": [
                    message
                    for condition, message in (
                        (not datasources, "No datasources were extracted."),
                        (not dashboards, "No dashboard pages were extracted."),
                        (not worksheets, "No worksheets were extracted."),
                    )
                    if condition
                ],
            }
        )

    registered_workbooks = run_manifest.get("workbook_count", 0)
    status = "PASS"
    if inventory_errors:
        status = "PARTIAL" if assets else "FAIL"
    elif registered_workbooks == 0 or not assets:
        status = "FAIL"

    return {
        "preflight_version": "1.0",
        "run_id": run_manifest.get("run_id"),
        "authority": "deterministic_tableau_parser",
        "status": status,
        "registered_workbooks": registered_workbooks,
        "inventoried_workbooks": len(assets),
        "quarantined_workbooks": len(inventory_errors),
        "dashboard_count": dashboard_count,
        "worksheet_count": worksheet_count,
        "datasource_count": datasource_count,
        "relationship_count": relationship_count,
        "physical_field_count": physical_fields,
        "calculated_field_count": calculated_fields,
        "source_tables": sorted(source_tables),
        "assets": asset_results,
        "errors": inventory_errors,
    }
