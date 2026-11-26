# Datasource Mapping Guide

Mapping evidence connects source BI datasources to approved physical Databricks tables. Users map datasources and source fields; workbook UI objects and derived KPIs are resolved downstream.

## Minimum Mapping

For each source table provide:

- source datasource and table name;
- target Unity Catalog table name;
- source and target grain;
- field-to-column mappings;
- required unit conversions.

## Recommended Relationship Evidence

For production-quality conversion also provide:

- join keys and join type;
- expected cardinality;
- temporal or as-of predicates;
- current-record filters;
- uniqueness and fanout expectations.

## Supported Files

Put any YAML, JSON, or CSV file in the input `mappings/` folder; the file name doesn't matter, and several files are merged. The only requirement is a Tableau table paired with its Databricks table (`catalog.schema.table`). Any of these works:

```yaml
Orders: main.sales.orders
Returns: main.sales.returns
```

```csv
source_table,target_table,grain
Orders,main.sales.orders,one row per order line
```

```yaml
table_mappings:
  - source: { table: Orders, datasource: Superstore }
    target: { table: main.sales.orders, grain: one row per order line, business_keys: [order_id] }
```

Column and key names are flexible (`source_table`, `tableau_table`, `from`; `target_table`, `databricks_table`, `to`), and extra columns are ignored. Optional details such as `datasource`, `grain`, `business_keys`, and relationships improve the result. The workflow accepts incomplete documents but records missing evidence as unresolved instead of inventing joins or calculations. If a row is missing a table, the run stops with the file and row to fix.

**Extracts built outside Tableau (for example Alteryx):** their table is always named `Extract`, so a row `source: { table: Extract }` would apply to every such datasource. Give each its own row with `datasource`, for example `source: { table: Extract, datasource: Sales Output }`. If one row without `datasource` matches datasources that read different extracts, the run stops before grouping and names the datasources.

## Review Rules

- Use physical governed tables, not compatibility views, unless explicitly approved.
- Confirm grain before approving a join.
- Treat ambiguous matches as review items.
- Record unsupported Tableau calculations with a governed disposition.
- Revise approved mappings when repair evidence identifies a datasource, relationship, grain, or conversion defect.
