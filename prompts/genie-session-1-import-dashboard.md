# Genie Code Session 1 — Import Tableau Dashboards

You are running unattended in a Lakeflow Job.

- Run ID: `{{run_id}}`
- Semantic group: `{{group_id}}`
- Group run directory: `{{group_run_path}}`
- Rendered `/importBI` prompt: `{{group_run_path}}/session-1/importbi-prompt.md`
- Output directory: `{{group_run_path}}/session-1`

Read the rendered prompt from the Unity Catalog Volume and execute it exactly. Use only the workbooks and approved mapping contract named there. Do not substitute compatibility views, unrelated tables, joins, or calculations.

Create the requested draft AI/BI dashboards. Record skipped, degraded, unsupported, and unresolved items rather than inventing an implementation.

Write `{{group_run_path}}/session-1/importbi-result.json` containing:

```json
{
  "run_id": "...",
  "status": "SUCCESS | PARTIAL | FAILED",
  "dashboards": [{"dashboard_id": "...", "display_name": "..."}],
  "exceptions_path": ".../importbi-exceptions.json",
  "notes": []
}
```

Also write `{{group_run_path}}/session-1/importbi-exceptions.json`. If no dashboard was created, write both artifacts and fail the task.
