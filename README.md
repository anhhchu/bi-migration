# BI Migration Blueprint

BI Migration Blueprint is a Databricks control plane for migrating Tableau workbooks at portfolio scale. It inventories `.twb` and `.twbx` files, groups related workbooks into semantic domains, compiles source-to-Databricks mapping contracts, orchestrates `/importBI`, and reviews the resulting dashboards, Unity Catalog Metric Views, Genie Agents, and migration gaps.

## Workflow

1. **Upload assets** — land Tableau workbooks and optional mapping documents in a Unity Catalog Volume.
2. **Run inventory** — parse workbook metadata, datasource fields, calculations, relationships, and dependencies.
3. **Review groups and mappings** — resolve physical target fields, joins, grain, and temporal rules; approve a versioned YAML contract.
4. **Build assets** — import dashboards in parallel, reconcile dashboard IDs/configurations, build and validate a unified Metric View, then create the Genie Agent.
5. **Review results** — open generated assets and disposition migration gaps by severity and stage.
6. **Remediate or promote** — generate targeted in-place repair prompts or record the final production naming decision.

The application never reruns `/importBI` for ordinary remediation. Dashboard repair prompts reference existing dashboard IDs; Metric View and Agent repairs update their existing candidate assets.

## Repository Layout

- `src/bi_migration/` — deterministic Python inventory, parsing, grouping, mapping, and readiness pipeline.
- `app/bi-migration-review/` — Databricks AppKit server and React application.
- `notebooks/` — inspectable Lakeflow Job tasks for inventory, reconciliation, validation, and audit.
- `scripts/deploy.py` — creates/reconciles editable Jobs, deploys the bundle, and deploys the App.
- `scripts/generate_importbi_bitemporal_data.py` — repeatable Superstore bitemporal test-data generator.
- `prompts/`, `schemas/`, `skills/` — prompt contracts, mapping schema, and mapping extraction guidance.
- `tests/` — pytest coverage and small Tableau fixtures.

## Local Development

Prerequisites: Python 3.11+, `uv`, Node.js/npm, Databricks CLI, and an authenticated Databricks profile.

```bash
# Python tests
uv run pytest

# App development
cd app/bi-migration-review
npm install
npm run dev

# App validation
npm run typecheck
npm test
npm run build
```

The local AppKit development server uses the configured Databricks authentication context. Do not place workspace credentials in the repository.

## Deployment

Deployment uses a configured target in `databricks.yml`. The checked-in `default` target is a development example tied to the current workspace and Volume; add or override a target for another environment before deploying.

Authenticate explicitly and verify the target:

```bash
databricks auth profiles
databricks bundle validate -t default --profile DEFAULT
```

### 1. Deploy workflow Jobs

```bash
python3 scripts/deploy.py \
  --profile DEFAULT \
  --target default \
  --component jobs
```

This creates or reconciles the editable **Dashboard Import**, **Semantic Build**, and **Metric View Repair** Jobs. Existing Genie Code task bodies are preserved because the Jobs API redacts them; deterministic notebook tasks and dependencies are updated from the repository.

On a new workspace, configure these placeholders once in the Jobs UI using the prompts shown by the App:

- nested `import_dashboard` task in the Dashboard Import `For each`
- `build_metric_view`
- `build_genie_agent`
- `repair_metric_view` in the Metric View Repair Job

The repair workflow validates each revision deterministically and can submit another repair run automatically, stopping after five attempts or when the same failure signature repeats.

### 2. Deploy the bundle and App

```bash
python3 scripts/deploy.py \
  --profile DEFAULT \
  --target default \
  --component app
```

This deploys the Python wheel, inventory Job, notebooks, App source, and App resource bindings using the discovered external Job IDs. It does not modify Genie Code task definitions.

The App also binds the separately deployed datasource semantic workflow. Override its workspace-specific resources when they differ from the development defaults:

```bash
python3 scripts/deploy.py \
  --profile DEFAULT \
  --target default \
  --component app \
  --datasource-semantic-proposal-job-id <propose-job-id> \
  --datasource-semantic-migration-job-id <migration-job-id> \
  --datasource-semantic-volume-full-name <catalog.schema.volume>
```

For a coordinated first deployment, run both phases:

```bash
python3 scripts/deploy.py --profile DEFAULT --target default --component all
```

Preview either phase without changing workspace resources:

```bash
python3 scripts/deploy.py --profile DEFAULT --target default --component jobs --dry-run
python3 scripts/deploy.py --profile DEFAULT --target default --component app --dry-run
```

Verify the deployed App:

```bash
databricks apps get bi-migration-review --profile DEFAULT -o json
```

## Volume Artifacts

A migration is stored beneath:

```text
/Volumes/<catalog>/<schema>/<volume>/bi-migrations/<migration-name>/
  inputs/                 # Workbooks and uploaded mapping evidence
  control/                # Upload and target-metadata manifests
  inventory/              # Parsed assets, groups, contracts, and readiness
  groups/<group-slug>/
    mapping/              # Approved contract and semantic prompts
    import/               # Reconciled dashboard configs and results
    semantic/             # Metric View, Agent, audit, remediation, promotion
```

Internal identifiers such as `group-001` remain inventory metadata; user-facing group packages use concise readable slugs.

## CLI Pipeline

The deterministic backend can also run outside the App:

```bash
uv run bi-migrate generate-corpus --output build/test-corpus

uv run bi-migrate backend \
  --input build/test-corpus/tableau \
  --mapping-docs build/test-corpus/mappings \
  --target-metadata build/test-corpus/target_metadata.json \
  --domain sales \
  --output build/test-run
```

Generated mappings are proposals. A reviewer must resolve blocking datasource and relationship gaps before approving the contract or creating semantic assets.

## Current Boundaries

- Promotion records final naming and approval decisions; execution of the governed Promotion Job is tracked in GitHub issue #1.
- Existing migration artifacts are group-scoped. Run-scoped artifact history and `latest-success` pointers remain planned hardening work.
- Genie Code conversation text is not scraped. Actionable findings must be persisted as structured artifacts for review and remediation.
