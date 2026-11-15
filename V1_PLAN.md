# V1 Implementation Plan

## Goal

Prove the deterministic foundation around `/importBI` before adding live Databricks orchestration.

## Scope

1. Parse Tableau `.twb` and `.twbx` files.
2. Build workbook, dashboard, worksheet, datasource, field, calculation, connection, and table inventory.
3. Group workbooks that share datasources or physical tables.
4. Compare extracted source fields with supplied Databricks target metadata.
5. Produce draft domain YAML, confidence evidence, KPI candidates, and unresolved mappings.
6. Provide a Genie Code skill that runs the deterministic tooling and reviews its output.

## Non-Goals

- Calling `/importBI` automatically.
- Reading live Tableau, Power BI, or Databricks APIs.
- Approving semantic mappings without a human owner.
- Full Tableau XML coverage or Power BI parsing in v1.

## Acceptance Criteria

- One CLI command analyzes a directory of Tableau files.
- Shared-source workbooks are placed in the same semantic group.
- Mapping YAML passes the included JSON Schema.
- Ambiguous mappings are marked `unresolved`, never silently accepted.
- Unit tests cover TWB, TWBX, grouping, and mapping generation.
