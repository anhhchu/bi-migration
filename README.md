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

For the Superstore pilot, use `examples/superstore_target_metadata.json`, generated from:

- `main.genie.superstore_orders`
- `main.genie.superstore_toc_annotations`
