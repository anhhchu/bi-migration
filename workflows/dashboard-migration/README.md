# Dashboard migration (paused)

Migrates Tableau dashboards with Genie Code `/importBI`, then builds a Metric View and Genie Agent from the imported dashboards. Work is paused while the semantic-model workflow (`../datasource-semantic-migration/`) is the main path.

## Contents

- `src/bi_migration/` — inventory, grouping, mapping, preflight, and pipeline modules; `bi-migrate` CLI.
- `notebooks/` — Job tasks for inventory, dashboard import, semantic build, and Metric View repair.
- `prompts/` — Genie Code task text for those Jobs, pasted into the Jobs UI when the Jobs are set up.
- `schemas/`, `skills/`, `tests/`, `scripts/generate_importbi_bitemporal_data.py` — contracts, the mapping-extraction skill, tests, and demo data.

## Deployment

The Jobs are still deployed from the repository root: `databricks.yml` deploys the inventory Job and packages this folder as its wheel, and `scripts/deploy.py` creates the dashboard import, semantic build, and repair Jobs from `notebooks/`.

## Development

```bash
uv run pytest
```
