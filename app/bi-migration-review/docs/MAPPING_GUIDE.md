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

Upload `table-mapping.yaml`, `table-mapping.yml`, or `table-mapping.csv` beneath the input `mappings/` folder. The workflow accepts incomplete user documents but records missing evidence as unresolved instead of inventing joins or calculations.

## Review Rules

- Use physical governed tables, not compatibility views, unless explicitly approved.
- Confirm grain before approving a join.
- Treat ambiguous matches as review items.
- Record unsupported Tableau calculations with a governed disposition.
- Revise approved mappings when repair evidence identifies a datasource, relationship, grain, or conversion defect.
