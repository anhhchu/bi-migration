/importBI

Import the Tableau workbook at:

`/Volumes/serverless_stable_dvmvgw_catalog/genie/marsh/tableau/Super Sample Superstore.twbx`

Create a draft Databricks AI/BI dashboard for migration evaluation.

Use these Databricks tables instead of retaining legacy Tableau extract connections:

- `serverless_stable_dvmvgw_catalog.genie.superstore_orders` for order, customer, product, sales, quantity, discount, profit, shipping, and return analysis.
- `serverless_stable_dvmvgw_catalog.genie.superstore_toc_annotations` only for dashboard navigation and annotation content. Do not join it to the orders table.

Create dashboard-local metric views for this test. Do not promote them to Unity Catalog and do not publish the dashboard.

Preserve the source dashboard's pages, KPIs, filters, drill paths, formatting, and navigation where supported. For unsupported or ambiguous behavior, do not guess silently.

In the final response, report:

1. Created dashboard name and link.
2. Local metric views and their measures, dimensions, source tables, joins, and filters.
3. Source Tableau calculations or parameters that were translated.
4. Unsupported, approximated, or unresolved features.
5. Any KPI or filter whose result could not be validated.
6. Recommended reusable metric definitions that could later be promoted to Unity Catalog.
