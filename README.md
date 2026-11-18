# BI Migration Blueprint v1

V1 inventories Tableau workbooks, groups shared dependencies, and drafts source-to-Databricks YAML mappings for review.

```bash
uv run bi-migrate analyze \
  --input tests/fixtures/tableau \
  --target-metadata examples/target_metadata.json \
  --domain sales \
  --output build/demo
```

Outputs:

- `inventory.json`
- `dependency_graph.json`
- `groups.json`
- `mappings/domains/<domain>.yaml`
- `reports/unresolved_mappings.csv`
- `reports/kpi_candidates.csv`

The generated mapping is a proposal. A domain owner must approve it before semantic objects or dashboards are created.

## Deploy the application and workflow Jobs

Deploy the two editable workflow Jobs first. This can run independently without redeploying the App:

```bash
python3 scripts/deploy.py --profile DEFAULT --target default --component jobs
```

After the Jobs are ready, deploy the bundle and App using their discovered IDs:

```bash
python3 scripts/deploy.py --profile DEFAULT --target default --component app
```

For a new environment or coordinated release, run both stages sequentially:

```bash
python3 scripts/deploy.py --profile DEFAULT --target default --component all
```

Preview the resulting Job definitions without changing workspace resources:

```bash
python3 scripts/deploy.py --profile DEFAULT --target default --component jobs --dry-run
python3 scripts/deploy.py --profile DEFAULT --target default --component app --dry-run
```

For existing Jobs, the script updates deterministic notebook tasks only; it never sends the API-redacted `import_dashboard`, `build_metric_view`, or `build_genie_agent` task bodies back to Databricks. On a new workspace, it creates notebook placeholders; configure those three tasks as Genie Code once using the prompts shown in the App.

## V2 backend pipeline

Generate a deterministic Tableau test corpus and run ingest, inventory, grouping, mapping-document compilation, and readiness checks:

```bash
uv run bi-migrate generate-corpus --output build/v2-corpus

uv run bi-migrate backend \
  --input build/v2-corpus/tableau \
  --mapping-docs build/v2-corpus/mappings \
  --target-metadata build/v2-corpus/target_metadata.json \
  --domain sales \
  --output build/v2-run
```

Invalid workbooks and mapping documents are quarantined in report outputs instead of stopping the portfolio run. See `V2_PLAN.md` for contracts and acceptance criteria.

The backend also emits mapping templates, contracts, and readiness reports under `groups/<group-id>/`. Review and supply target evidence independently for each semantic group instead of treating unrelated dashboards as one mapping domain.

For the Superstore pilot, use `examples/superstore_target_metadata.json`, generated from:

- `serverless_stable_dvmvgw_catalog.genie.superstore_orders`
- `serverless_stable_dvmvgw_catalog.genie.superstore_toc_annotations`
