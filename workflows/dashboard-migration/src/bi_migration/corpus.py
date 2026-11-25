from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


def _workbook(datasource: str, table: str, fields: list[tuple[str, str, str | None]], worksheet: str, dashboard: str) -> str:
    columns = []
    for name, datatype, calculation in fields:
        calculation_xml = f'<calculation formula="{escape(calculation, {chr(34): "&quot;"})}" />' if calculation else ""
        columns.append(
            f'<column name="[{escape(name)}]" caption="{escape(name)}" datatype="{datatype}" role="measure">{calculation_xml}</column>'
        )
    return f'''<?xml version="1.0" encoding="utf-8"?>
<workbook>
  <datasources><datasource name="{escape(datasource)}" caption="{escape(datasource)}">
    <connection class="sqlserver" server="legacy" dbname="warehouse"><relation name="source" table="{escape(table)}" type="table" /></connection>
    {''.join(columns)}
  </datasource></datasources>
  <worksheets><worksheet name="{escape(worksheet)}"><datasource-dependencies datasource="{escape(datasource)}" /></worksheet></worksheets>
  <dashboards><dashboard name="{escape(dashboard)}"><zones><zone name="{escape(worksheet)}" /></zones></dashboard></dashboards>
</workbook>'''


def generate_corpus(output_path: str | Path) -> dict:
    output = Path(output_path)
    tableau = output / "tableau"
    mappings = output / "mappings"
    tableau.mkdir(parents=True, exist_ok=True)
    mappings.mkdir(parents=True, exist_ok=True)
    specs = [
        ("sales_overview", "sales", "[dbo].[fact_sales]", [("Order ID", "string", None), ("Sales", "real", None), ("Margin %", "real", "SUM([Profit]) / SUM([Sales])")]),
        ("sales_region", "sales-copy", "[dbo].[fact_sales]", [("Region", "string", None), ("Sales", "real", None)]),
        ("returns", "returns", "[dbo].[fact_returns]", [("Order ID", "string", None), ("Returned", "string", None)]),
        ("finance", "finance", "[dbo].[fact_ledger]", [("Account", "string", None), ("Amount", "real", None)]),
    ]
    specs.extend(
        (
            f"sales_variant_{number:02d}",
            f"sales-variant-{number:02d}",
            "[dbo].[fact_sales]",
            [("Order ID", "string", None), ("Sales", "real", None), ("Region", "string", None)],
        )
        for number in range(1, 9)
    )
    specs.extend(
        (
            f"returns_variant_{number:02d}",
            f"returns-variant-{number:02d}",
            "[dbo].[fact_returns]",
            [("Order ID", "string", None), ("Returned", "string", None)],
        )
        for number in range(1, 4)
    )
    specs.extend(
        (
            f"finance_variant_{number:02d}",
            f"finance-variant-{number:02d}",
            "[dbo].[fact_ledger]",
            [("Account", "string", None), ("Amount", "real", None)],
        )
        for number in range(1, 4)
    )
    specs.extend(
        (
            f"support_{number:02d}",
            f"support-{number:02d}",
            "[dbo].[fact_tickets]",
            [("Ticket ID", "string", None), ("Resolution Hours", "real", None)],
        )
        for number in range(1, 5)
    )
    for name, datasource, table, fields in specs:
        xml = _workbook(datasource, table, fields, f"{name} sheet", f"{name} dashboard")
        (tableau / f"{name}.twb").write_text(xml, encoding="utf-8")
    with zipfile.ZipFile(tableau / "sales_packaged.twbx", "w") as package:
        package.writestr("workbooks/sales_packaged.twb", _workbook("sales-package", "[dbo].[fact_sales]", [("Order ID", "string", None), ("Sales", "real", None)], "Packaged Sales", "Packaged"))
    (tableau / "corrupt.twbx").write_text("not a zip file", encoding="utf-8")

    mapping_rows = [
        {"Source Field": "Order ID", "Target Table": "main.gold.orders", "Target Field": "order_id", "Source Grain": "order line", "Target Grain": "order line"},
        {"Source Field": "Sales", "Target Table": "main.gold.orders", "Target Field": "sales_amount", "Conversion": "renamed"},
        {"Source Field": "Region", "Target Table": "main.gold.orders", "Target Field": "region_name", "Conversion": "renamed"},
    ]
    with (mappings / "sales_mapping.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Source Field",
                "Target Table",
                "Target Field",
                "Source Grain",
                "Target Grain",
                "Conversion",
            ],
        )
        writer.writeheader()
        writer.writerows(mapping_rows)

    target_metadata = {
        "tables": [
            {
                "name": "main.gold.orders",
                "grain": "order line",
                "columns": [
                    {"name": "order_id", "type": "string", "synonyms": ["Order ID"]},
                    {"name": "sales_amount", "type": "real", "synonyms": ["Sales"]},
                    {"name": "region_name", "type": "string", "synonyms": ["Region"]},
                ],
            },
            {
                "name": "main.gold.returns",
                "grain": "one row per returned order",
                "columns": [
                    {"name": "order_id", "type": "string", "synonyms": ["Order ID"]},
                    {"name": "return_status", "type": "string", "synonyms": ["Returned"]},
                ],
            },
        ]
    }
    (output / "target_metadata.json").write_text(json.dumps(target_metadata, indent=2), encoding="utf-8")
    return {"workbooks": len(specs) + 2, "mapping_documents": 1, "output": str(output)}
