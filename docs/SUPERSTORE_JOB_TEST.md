# Superstore Genie Code Job Test

## Verified Input

`dbfs:/Volumes/serverless_stable_dvmvgw_catalog/genie/marsh/tableau/Super Sample Superstore.twbx`

## Create the Test Job

Genie Code tasks can currently be added only through the Databricks Jobs UI.

1. Open **Workflows > Jobs & Pipelines**.
2. Create a job named `BI Migration - Superstore importBI test`.
3. Add a task named `import_superstore` with type **Genie Code**.
4. Paste the contents of `prompts/superstore_importbi.md` into **Prompt**.
5. Save the task and run the job.

Auto-approval is always enabled for a Genie Code job task. The prompt therefore limits the test to a draft dashboard and dashboard-local metric views.

## Capture

- Job ID and run ID.
- Task status, duration, and final response.
- Genie Code conversation link.
- Draft dashboard ID and link.
- Generated local metric-view definitions.
- Unsupported and unresolved features.
- Any unexpected object creation or modification.

## Project Decisions from the Test

Use the results to determine:

- How much mapping context `/importBI` needs before execution.
- Whether local metric views preserve Tableau KPI and filter semantics.
- Which generated definitions are reusable across dashboards.
- How to extract, compare, validate, and promote local metric views.
- Which compatibility rules and exception categories the migration factory needs.
- Expected runtime, review effort, and failure modes per workbook.
