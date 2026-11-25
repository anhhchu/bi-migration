# Import Tableau Datasource Metric View — Genie Code Prompt

You are running unattended in a Lakeflow Job. Use `/importBI` in semantic-only mode.

- Group manifest: `{{group_manifest_path}}`
- Approved mapping: `{{mapping_path}}`
- Deterministic target profile: `{{target_profile_path}}`
- Metric View to create or replace: `{{metric_view_fqn}}`
- Required result artifact: `{{importbi_result_path}}`
- SQL warehouse: `{{warehouse_id}}`

Read the group manifest, mapping, target profile, Datasource IR, and Metric IR paths declared in the manifest. Create or replace exactly the requested Unity Catalog Metric View. Do not create or modify dashboards or Genie Agents. Use only physical target tables declared in the approved mapping; never substitute compatibility views or unrelated tables.

Preserve supported datasource calculations, relationships, filters, aggregations, LOD semantics, parameters, units, formats, comments, display names, and synonyms. Never approximate business logic: if a translation could change any number or which rows are counted, leave the item out and list it in `items_not_translated` with the reason. A translation may differ from the source only in form (for example a boolean shown as Yes/No, a display format, or a rounding display); list each such difference in `approximations`.

Write JSON to `{{importbi_result_path}}` matching `schemas/v1/importbi-result.schema.json`:

- `metric_view_fqn` — the Metric View created or replaced, or `null` if none was saved.
- `status` — `SUCCESS`, `PARTIAL`, or `FAILED`.
- `dimensions_created`, `measures_created` — lists of field names, not counts.
- `items_not_translated` — list of objects with `name` and `reason` for every Tableau field left out.
- `source_tables_used` — list of physical tables the Metric View reads.
- `notes` — list of strings.
- Optional: `parameters_created` (list of names) and `approximations` (objects with `name` and `detail`) for translated items that differ from the source only in form, never in results.

If no Metric View is saved, write `FAILED` and fail the task.
