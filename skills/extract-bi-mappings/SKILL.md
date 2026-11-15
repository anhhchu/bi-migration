---
name: extract-bi-mappings
description: Inventory Tableau BI assets, group shared datasource dependencies, and draft reviewable source-to-Databricks YAML mappings before an importBI migration.
---

# Extract BI Mappings

Use the project CLI for deterministic extraction and mapping drafts. Do not infer mappings directly from filenames or screenshots.

## Required Inputs

- Path containing `.twb` or `.twbx` files.
- Target metadata JSON containing Databricks tables, columns, types, and optional synonyms.
- Business domain and output directory.

## Workflow

1. Run `uv run bi-migrate analyze --input <path> --target-metadata <json> --domain <domain> --output <path>`.
2. Review `inventory.json`, `dependency_graph.json`, and `groups.json` for extraction gaps.
3. Separate physical fields, parameters, and calculated KPIs before proposing mappings.
4. Use deterministic evidence first: names, synonyms, types, keys, grain, lineage, and value-profile statistics.
5. Use Genie Code to interpret renamed business concepts and calculations only after deterministic evidence is available.
6. Review the domain YAML and KPI candidates against source calculations and target metadata.
7. Leave ambiguous matches as `unresolved`. Never promote a mapping using confidence alone.
8. Ask the data owner to resolve grain, keys, value translations, KPI meaning, and applicable temporal rules.
9. Change the mapping status to `approved` only after technical and business review.

## Mapping Policy

- The CLI confidence score is evidence for review, not proof of semantic equivalence.
- The LLM proposes interpretations; it never approves mappings.
- Value overlap means comparing source and target value profiles inside the governed data platform. Prefer distinct-value overlap for dimensions, distributions for measures, and key-level comparison when common keys exist.
- Do not expose or persist raw sensitive values in prompts or mapping files. Store aggregate evidence such as overlap percentage, null rate, and distinct count.
- A high value-overlap score does not override incompatible grain, keys, units, filters, or temporal meaning.
- Use approved domain mappings across assets and create asset-specific overrides only for genuine exceptions.
