---
name: extract-bi-mappings
description: Interpret existing mapping documents, inventory Tableau BI assets, and create reviewable source-to-Databricks mapping evidence for the deterministic BI migration pipeline.
---

# Extract BI Mappings

Use Genie Code for document interpretation and the project CLI for deterministic extraction, validation, and mapping drafts. Genie may propose evidence; it must never approve a mapping or bypass the pipeline.

## Required Inputs

- Path containing `.twb` or `.twbx` files.
- Existing mapping material, if available. It may be prose, a table, CSV, JSON, YAML, or Markdown.
- Target metadata JSON containing authorized Databricks tables, columns, types, optional table grain, and optional synonyms.
- Business domain and output directory.

## Workflow

1. Run the deterministic pipeline once to extract source fields and suggestions: `uv run bi-migrate backend --input <path> --target-metadata <json> --domain <domain> --output <path>`.
2. Review `inventory.json`, `dependency_graph.json`, `groups.json`, and each group's `mapping_template.csv`.
3. Interpret the user's mapping material against the extracted source fields and authorized target metadata.
4. Write a canonical CSV, JSON, or YAML mapping evidence file using the contract below. Preserve uncertainty; do not invent missing values.
5. Run the pipeline again with `--mapping-docs <evidence-path>`.
6. Review `mapping_evidence.json` for provenance, conflicts, and quarantined documents.
7. Review the generated YAML, unresolved report, grain warnings, and KPI candidates in the app.
8. Have a user save corrections as drafts and approve them only after technical and business review.

## Canonical Evidence Contract

Emit one record per source field. Use these exact keys when a value is known:

- `datasource`: Tableau datasource name or ID.
- `legacy`: Tableau field caption or name. Required.
- `source_table`: Source relation, when documented.
- `source_grain`: One source row represents what.
- `target_table`: Fully qualified Unity Catalog name: `catalog.schema.table`.
- `target_expression`: Existing column name or a reviewable SQL expression.
- `target_grain`: One target row represents what.
- `conversion`: `direct`, `renamed`, `calculated`, `joined`, `temporal`, `skipped`, or `redesign`.
- `status`: Keep `proposed` unless the input explicitly contains a prior approval. Prior approval is evidence only and does not approve the compiled contract.
- `notes`: Ambiguity, assumptions, join keys, units, filters, temporal rules, or value translations.

For CSV, use this header:

`datasource,legacy,source_table,source_grain,target_table,target_expression,target_grain,conversion,status,notes`

Do not add a target just because its name looks similar. If a document names only a business concept, leave `target_table` and `target_expression` empty and explain the interpretation in `notes`.

## Interpretation Rules

- Match document rows to extracted Tableau fields, not merely to workbook filenames.
- Resolve target names only against the supplied authorized Unity Catalog metadata.
- Preserve the document's wording in `notes`; the pipeline adds file and row provenance.
- Keep competing interpretations as separate records. The compiler will mark their field unresolved.
- Treat different source and target grains as a required review, not a failed mapping. Record aggregation, allocation, join, and temporal behavior needed to reconcile them.
- Separate physical fields, parameters, calculated fields, and KPIs. Never map a Tableau parameter to a physical column without explicit evidence.
- Never send or persist raw sensitive values. Use aggregate profiles only.

## Mapping Policy

- The CLI confidence score is evidence for review, not proof of semantic equivalence.
- The LLM proposes interpretations; it never approves mappings.
- The pipeline and app are the system of record for validation and user decisions.
- A target must exist and be accessible to the signed-in Databricks user before a draft can be saved.
- Value overlap means comparing source and target value profiles inside the governed data platform. Prefer distinct-value overlap for dimensions, distributions for measures, and key-level comparison when common keys exist.
- Do not expose or persist raw sensitive values in prompts or mapping files. Store aggregate evidence such as overlap percentage, null rate, and distinct count.
- A high value-overlap score does not override incompatible grain, keys, units, filters, or temporal meaning.
- Use approved domain mappings across assets and create asset-specific overrides only for genuine exceptions.

## Stop Conditions

Leave the field unresolved and describe why when:

- The proposed target is absent from authorized metadata.
- More than one target is plausible.
- Grain reconciliation, joins, units, temporal semantics, or value translations are unspecified.
- The mapping document conflicts with the Tableau calculation or another document.
- The target requires data that does not exist.
