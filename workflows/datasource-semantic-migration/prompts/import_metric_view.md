# Import Tableau Datasource Metric View — Genie Code Prompt

You are running unattended in a Lakeflow Job. Use `/importBI` in semantic-only mode.

- Group manifest: `{{group_manifest_path}}`
- Approved mapping: `{{mapping_path}}`
- Deterministic target profile: `{{target_profile_path}}`
- Metric View to create or replace: `{{metric_view_fqn}}`
- Required result artifact: `{{importbi_result_path}}`
- SQL warehouse: `{{warehouse_id}}`

Read the group manifest, mapping, target profile, Datasource IR, and Metric IR paths declared in the manifest. Create or replace exactly the requested Unity Catalog Metric View. Do not create or modify dashboards or Genie Agents. Use only physical target tables declared in the approved mapping; never substitute compatibility views or unrelated tables.

Preserve supported datasource calculations, relationships, filters, aggregations, LOD semantics, parameters, units, formats, comments, display names, and synonyms. Leave unsupported or ambiguous semantics out rather than approximating them.

Write JSON to `{{importbi_result_path}}` containing at least: `metric_view_fqn`, `status`, `dimensions_created`, `measures_created`, `items_not_translated`, `source_tables_used`, and `notes`. Status must be `SUCCESS`, `PARTIAL`, or `FAILED`. If no Metric View is saved, write `FAILED` and fail the task.
