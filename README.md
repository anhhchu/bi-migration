# BI Migration Blueprint

Migrate Tableau semantic models to governed Unity Catalog **Metric Views**. Point the workflow at Tableau datasource files (`.tds`/`.tdsx`) and a table mapping; it groups them into semantic domains, builds one candidate Metric View per group, evaluates it, repairs what it can automatically, and leaves people only the decisions that need them. A Databricks App drives the whole flow.

> **Supported today:** datasource semantic migration. Dashboard migration (`.twb`/`.twbx` → AI/BI dashboards) is paused while it is being fixed; its code is still in the repository but hidden in the App.

## How it works

| Step       | What happens                                                                                                       |
| ---------- | ------------------------------------------------------------------------------------------------------------------ |
| 1. Propose | Inventory the datasources, parse fields and calculations, and propose readable semantic groups (Genie Code)        |
| 2. Approve | Review each group's datasources and Databricks target tables in the App, then approve                              |
| 3. Review  | Each group gets a candidate Metric View, a release gate (Translation → Certify), and action items grouped by owner |

Evaluation checks translation, contract (grain and additivity), and design (structure and query execution). Parity with Tableau numbers, performance, and certification are reported as "not run" until those steps exist. Details: [workflow README](workflows/datasource-semantic-migration/README.md).

## Install

Prerequisites: [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) 1.0+, Python 3.11+, and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/anhhchu/bi-migration.git && cd bi-migration
databricks auth login --host https://<workspace-host> --profile my-ws
python3 scripts/install.py --profile my-ws --catalog <existing-catalog> --dry-run   # preview only
python3 scripts/install.py --profile my-ws --catalog <existing-catalog>
```

`install.py` checks access, picks a SQL warehouse, shows a plan, and asks before creating the schemas and Volumes it needs. It deploys the workflow Jobs (with their Genie Code tasks) and the App, wired together, and prints the App URL. It also deploys the paused dashboard Jobs, which the App still references. Options and permissions: [Installation guide](app/bi-migration-review/docs/INSTALLATION_GUIDE.md).

Workspace choices (catalog, schemas, Volumes, warehouse) are saved per CLI profile in `.databricks/bi-migration/<profile>.json` (gitignored), not in `databricks.yml`. To redeploy after code changes:

```bash
(cd workflows/datasource-semantic-migration && uv run python deploy.py --profile my-ws --target dev)  # workflow
python3 scripts/deploy.py --profile my-ws --target dev --component app                             # App
```

Use these scripts rather than plain `databricks bundle deploy`: they set the Genie Code tasks and the App's Job and Volume bindings.

## Use

1. Put your inputs in a Volume folder, or upload them in the App:

   ```text
   <input-folder>/
     datasources/   *.tds, *.tdsx
     mappings/      table-mapping.yaml   (Tableau tables → Databricks tables; see the Mapping guide)
   ```

2. Open the App → **Migrate semantic models** → propose, approve, and review.

Results are written to the output Volume:

```text
<output-volume>/runs/<run-id>--<UTC start>/
  groups/<group>/metric-view.yaml   # candidate definition
  reports/                          # HTML and JSON reviews per group
  _internal/                        # IR, query results, repair evidence
```

Candidate Metric Views are created as `<catalog>.<schema>.bim_<group>_<hash>_candidate`.

## Repository layout

- `workflows/datasource-semantic-migration/` — the semantic migration workflow: parser, evaluator, repair, reports, Jobs, and tests.
- `app/bi-migration-review/` — the Databricks App (AppKit, React).
- `scripts/install.py`, `scripts/deploy.py` — install and deploy everything.
- Dashboard migration (paused): `src/bi_migration/`, `notebooks/`, `prompts/`, `schemas/`, `skills/`, `tests/`.

## Development

```bash
(cd workflows/datasource-semantic-migration && uv run pytest)   # workflow tests
(cd app/bi-migration-review && npm install && npm test)         # App tests
(cd app/bi-migration-review && npm run dev)                     # local App, see its README
```

## Current limits

- Numbers are not yet compared with Tableau (parity), and performance and certification are not automated.
- Repair can stop early when deliberately excluded items count against its completeness gate.
- Tableau datasource filter values and some date-shift calculations are not parsed yet; they appear as action items.
