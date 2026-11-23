# Datasource Semantic Migration Workflow

Metric-level evaluation and bounded automatic repair are specified in `METRIC-VIEW-EVALUATION-REPAIR-PLAN.md`.

## 1. Summary

Build a standalone Lakeflow workflow that converts Tableau `.tds` and `.tdsx` datasource definitions into validated candidate Unity Catalog Metric Views.

Users provide one Job parameter:

```text
input_volume_path
```

The Volume contains Tableau datasource packages and a table-equivalence mapping file. Deployment configuration supplies output locations, candidate and staging schemas, SQL warehouse, policies, concurrency, and retention. This workflow remains separate from dashboard migration and the Databricks App until its end-to-end behavior is validated.

## 2. Input Contract

Expected Volume layout:

```text
<input_volume_path>/
  datasources/
    *.tds
    *.tdsx
  mappings/
    table-mapping.yaml
```

CSV is also accepted as `mappings/table-mapping.csv`.

Minimum YAML:

```yaml
version: "1.0"
table_mappings:
  - source:
      system: snowflake
      database: LEGACY_DW
      schema: SALES
      table: ORDERS
    target:
      table: main.sales.order_lines
```

Required mapping fields are source system, database, schema, table, and fully qualified Databricks target table. Optional hints include source and target grain, business keys, event date, temporal model, known relationships, and unit conversions.

Target scopes are derived only from mapped target tables. The workflow never scans all authorized Unity Catalog objects. If no mapping file exists, inventory and grouping may complete, but Metric View construction stops with `MAPPING_REQUIRED`.

## 3. Runtime Configuration

Users do not provide a run ID. The parent Lakeflow Job uses `{{job.run_id}}` as `workflow_run_id`. Child Jobs receive that correlation ID and record their own Job run IDs.

One-time deployment configuration supplies:

- Output Volume
- Candidate Metric View catalog and isolated schema
- Hyper staging schema
- SQL warehouse ID
- Repair and validation policy
- Maximum concurrency: 10
- Maximum repair attempts: 3
- Candidate and staging retention: 7 days

The Job identity receives only the Volume, table, schema, and warehouse permissions required by that configuration.

## 4. Job Architecture

The production deployment uses one six-task semantic-group proposal Job, one three-task approved-group migration Job, one four-task semantic-group child Job, and one automatically triggered five-task repair Job. Proposal and migration are intentionally separate so users can inspect and approve group membership before any semantic asset is created.

### Semantic-group proposal Job — six tasks

```text
inventory_inputs
  -> foreach datasource batch: analyze_datasources
  -> prepare_semantic_grouping
  -> propose_semantic_groups
  -> build_semantic_groups
  -> finalize_semantic_grouping
```

`inventory_inputs` creates the run manifest, discovers TDS/TDSX inputs, safely extracts packages, hashes exact duplicates, inventories the uploaded mapping, and partitions unique inputs into configurable batches. `analyze_datasources` parses Datasource IR, resolves calculations, and compiles Metric IR for up to 25 files per task using up to eight concurrent parsers by default. Batch-level retries avoid both one-task-per-file overhead and all-files retry blast radius. `prepare_semantic_grouping` consolidates compact source evidence, approved targets, and deterministic pairwise similarity scores. Native Genie Code `propose_semantic_groups` assigns readable business domains and classifies UI helpers without creating assets. `build_semantic_groups` deterministically rejects missing, duplicated, low-confidence, or target-incompatible memberships, then creates immutable group mappings and readable child selectors. `finalize_semantic_grouping` writes and displays the review report and stops with `GROUPING_REVIEW_REQUIRED`.

### Approved-group migration Job — three tasks

```text
approve_semantic_groups
  -> foreach approved semantic group: migrate_semantic_groups
  -> finalize_workflow
```

The user starts this Job only after reviewing the proposal report. The proposal Job writes a controlled latest-pending pointer, so the normal migration run requires no path parameter; an optional `proposal_run_id` selects an older proposal. `approve_semantic_groups` resolves the pointer, validates that the index is complete, records the signed-in approver and selected groups, marks the pointer consumed, and publishes readable child selectors. `migrate_semantic_groups` launches one child Job per approved group. `finalize_workflow` aggregates group reports, updates the manifest, and removes expired temporary artifacts.

### Semantic group child Job — four tasks

```text
prepare_candidate_context
  -> create_candidate_metric_view
  -> reconcile_evaluate_repair
  -> run_metric_view_repair
```

`prepare_candidate_context` profiles only mapped targets, validates keys, relationship cardinality, fanout, orphan rates, and temporal rules, then renders the `/importBI` context. `create_candidate_metric_view` is a native Genie Code task that creates exactly one candidate Metric View. `reconcile_evaluate_repair` runs with `ALL_DONE`, reconciles actual Unity Catalog state, reconstructs a missing result artifact when the candidate exists, validates queryability and approved lineage, captures the deployed definition, and writes initial findings. `run_metric_view_repair` always invokes the separate bounded repair controller; ready candidates complete with `NOOP`.

Genie Code automations are created once by the deployment helper and referenced by each Job's `genie_task`. DAB owns stable proposal, migration, child, and repair Job IDs; the helper reapplies the supported Genie task configuration after every bundle deployment. Optional semantic repair is a separate bounded repair run triggered by the child Job.

## 5. Tooling

| Capability | Tooling | Reason |
|---|---|---|
| Discovery, parsing, IR, hashing, grouping evidence and validation, mapping, patching, reporting | Python notebooks backed by a wheel | Deterministic, testable, and reusable outside notebook entrypoints. |
| Key, grain, fanout, orphan, interval, invariant, and edge calculations | Spark SQL | Distributed profiling and portfolio-scale feature calculation. |
| Semantic-domain proposal and readable naming | Native Genie Code task | Uses full parsed semantics and mappings instead of brittle filename or connected-component labels. |
| Candidate Metric View DDL and queries | SQL Warehouse Statement Execution API | Preserves YAML indentation and provides auditable SQL execution. |
| TDSX source-fixture reads | Tableau Hyper API | Reads packaged extracts without treating them as production targets. |
| Tableau formula grammar | Lark | Deterministic supported-subset parsing and dependency resolution. |
| Contracts | Pydantic and JSON Schema | Versioned validation for IR, findings, patches, and results. |
| Candidate Metric View construction | Native Genie Code `/importBI` task | Reuses Databricks' Tableau semantic translation for standalone TDS/TDSX inputs while avoiding dashboard creation. |
| Unsupported semantic translation during repair | Optional Genie Code fallback | Handles only repair calculations not covered by deterministic rules. |

The construction task may create only the candidate Metric View named in its context package. It cannot select tables outside the approved mapping, create dashboards or Agents, modify contracts, control retries, or declare evaluation success. Repair fallback tasks must return a structured patch rather than directly approve their output.

## 6. Processing Design

### Identity and grouping

Grouping occurs in three passes:

1. Deterministic preparation of relation, calculation, field, connection, metadata, mapping, and pairwise similarity evidence.
2. Genie Code proposal of business-domain memberships, readable names, helpers, rationale, and confidence.
3. Deterministic validation of complete and unique membership, helper classification, minimum confidence, and shared target-schema compatibility.

Exact duplicates collapse before semantic proposal. Different fact grains, temporal meanings, target schemas, or security scopes remain separate unless the approved mapping provides compatible evidence.

Source similarity remains supporting evidence only, weighted as relation graph 35%, calculations 30%, fields 20%, connection lineage 10%, and metadata 5%. It never creates a group directly. A proposed group requires confidence of at least `0.65`; otherwise the run stops before creating group directories.

### Metric View construction

Create candidates by business domain and fact grain, not filename.

- Reuse an existing Metric View when semantic fingerprints match.
- Use certified base views for stable grain, resolved keys, or temporal joins.
- Include only re-aggregatable measures.
- Route selection-dependent, iterative, or non-reaggregatable calculations to governed SQL functions.
- Preserve comments, display names, synonyms, formats, and lineage.
- Create candidates only in the deployment-configured isolated schema.
- Never promote automatically.

Native `/importBI` is the primary candidate constructor. Before invoking it, deterministic tasks create a group-scoped context package containing:

- Exact TDS/TDSX Volume paths
- Approved table-equivalence mapping revision
- Exact allowed target table FQNs
- Required source and target grains
- Join keys and temporal rules when approved
- Exact candidate Metric View FQN
- Required result and exception artifact paths

The task runs once per semantic group and must not create a dashboard or Genie Agent. A downstream reconciliation task reads the actual UC Metric View definition, verifies that exactly the requested candidate was created, verifies source lineage against the allowed-table set, and writes the candidate YAML and translation report to the group artifacts.

If `/importBI` rejects the datasource type, fails to create the requested candidate, or produces invalid lineage, the group fails with structured findings. The workflow does not silently replace Genie translation with a weaker deterministic candidate.

The rendered group prompt follows this contract:

```markdown
/importBI

Run in semantic-only mode for the datasource group defined at:
`{{group_manifest_path}}`

Use the approved table mapping:
`{{mapping_path}}`

Create or replace exactly this candidate Unity Catalog Metric View:
`{{metric_view_fqn}}`

Do not create or modify dashboards or Genie Agents. Use only the exact physical
Databricks tables declared in the approved mapping. Preserve supported datasource
calculations, relationships, filters, aggregations, LOD semantics, units, formats,
comments, display names, and synonyms. Record unsupported or ambiguous logic rather
than approximating it. Write the required structured result artifacts beneath:
`{{output_path}}`

The downstream deterministic evaluator decides whether the candidate passes.
```

Candidate names use:

```text
bim_<group_slug>_<semantic_hash8>_candidate
```

## 7. Mapping and Relationship Safety

Mapping revisions are immutable and never overwrite uploaded contracts. Automatically approve a relationship revision only when:

- Referenced tables and columns exist with compatible datatypes.
- One unambiguous candidate path has the highest score.
- Join fanout is exactly `1.0` unless policy explicitly permits otherwise.
- Each fact row matches at most one applicable dimension version.
- Temporal intervals do not overlap per business key.
- Orphan and unmatched rates satisfy policy.
- Current-record predicates match the observed null or sentinel convention.
- Critical invariants and previously passing metrics do not regress.

Otherwise emit `UNRESOLVABLE_AUTOMATICALLY`.

## 8. Evaluation and Repair

### TDS evidence

Validate structure, calculation coverage, Metric IR, relationships, grain, compilation, invariants, dependencies, and queryability. Maximum evidence status is `PASS_SEMANTIC_ONLY`.

### TDSX evidence

Additionally:

- Reconcile Hyper and staged Spark schemas, rows, and numeric totals.
- Build a shadow Metric View over staged Hyper data.
- Execute supported Tableau calculations through a separate Hyper SQL emitter.
- Compare totals, compatible dimensions, dates, datasource filters, LOD scopes, nulls, and boundaries.
- Report source-fixture parity, not dashboard parity.

The Tableau parser is shared, but Hyper SQL and Metric View YAML use separate emitters. Golden fixtures validate the parser to reduce shared-compiler risk. Hyper staging is excluded from target discovery and expires after the run retention period.

### Deterministic recovery and repair boundary

The normal child Job automatically reconstructs a missing `/importBI` result from the actual Unity Catalog definition and records that recovery. It never auto-approves a relationship that fails key, fanout, or temporal profiling. Metric-definition changes require a versioned mapping or candidate revision and must be evaluated before acceptance; unsupported translation remains a structured gap rather than an invented repair.

Broader deterministic repairs—field casts, unit/null corrections, unambiguous aggregations, and dependency fixes—belong in the separately deployed Metric View repair workflow. They are not hidden inside the construction Job and do not change the uploaded mapping in place.

## 9. Artifact Layout

```text
<output_volume>/runs/<workflow_run_id>/
  manifest.json
  groups/
    <group-slug>/
      mapping.yaml
      metric-view.yaml
      _internal/
  reports/
    index.json
    index.html
    groups/<group-slug>/
      migration-review.json
      migration-review.html
      repair-review.json
      repair-review.html
  _internal/
    inventory/
    extracted/
    ir/
    fingerprints/
    profiling/
```

Users first open `reports/semantic-grouping-review.html` to inspect group names, memberships, targets, helpers, and candidate names. Starting the separate migration Job writes `reports/grouping-approval.json`. After migration, users open `reports/index.html` and follow the semantic-group reviews. Reviews show the candidate asset, semantic coverage, validation evidence, untranslated business items, approximations, blocking findings, and prioritized remediation actions. Group roots expose only governed mapping and Metric View assets. Run and group `_internal/` directories contain reproducibility, retry, patch, rollback, and diagnostic evidence. Unpacked TDSX members and Hyper staging are temporary and removed after retention expiry.

## 10. Public Contracts

Add versioned JSON schemas for table-mapping input, workflow manifest, Datasource IR, Metric IR, semantic-grouping proposal, `/importBI` construction result, structured finding, mapping revision manifest, deterministic patch, Genie patch, and evaluation summary.

Every artifact includes schema version, workflow run ID, input hashes, generator version, provenance, and creation time.

## 11. End-to-End Delivery Contract

The repository ships the complete proposal, approved migration, semantic-group, and automatic repair workflows together. A deployment is accepted only when one command deploys all four Jobs, creates or reuses the grouping, import, and repair Genie Code automations, wires the native tasks, and a reviewed Volume-only migration produces a workflow report plus one terminal repair result per semantic group.

Deterministic components remain independently testable. Users operate one intentional approval boundary between grouping and migration; internal implementation phases remain automated. A proposal reaches `GROUPING_REVIEW_REQUIRED`; an approved migration reaches `PASS_SEMANTIC_ONLY`, `PASS_SOURCE_PARITY`, `PARTIAL`, or `FAILED`.

## 12. Test Plan

Create at least 20 labeled datasource fixtures covering exact and renamed duplicates, compatible and incompatible versions, flat, star, snowflake, bridge, SCD2, bitemporal, safe and unsafe joins, TDS-only, TDSX, and supported and unsupported calculations.

Acceptance criteria:

- 100% exact duplicate precision and recall.
- Zero false semantic-group merges.
- At least 95% compatible-group recall.
- Zero unsafe relationship approvals.
- 100% detection of injected fanout and temporal overlap.
- 100% repair success for supported deterministic rules.
- Zero accepted regressions.
- Identical classifications and hashes across repeated runs.
- `/importBI` creates exactly one requested candidate per group and creates no dashboards or Genie Agents.
- Candidate lineage contains only target tables declared in the approved mapping revision.
- No hardcoded asset, catalog, schema, table, workbook, or field names.

## 13. Implemented Deliverables

- Standalone Python package and CLI under this workflow directory.
- Versioned contract schemas and schema registry.
- A six-task proposal Job, three-task approved migration Job, four-task semantic-group child Job, and five-task repair Job with inspectable notebook entrypoints.
- A deployment helper that deploys all four stable bundle Jobs, creates or reuses three scoped Genie Code automations, and injects native `genie_task` definitions after every bundle deployment.
- Deployment and policy configuration examples with safe defaults.
- Minimal TDS and mapping fixtures.
- Unit tests for configuration, input contract, schema registry, and deterministic manifest generation.
- Safe recursive `.tds` and `.tdsx` discovery with exact-content deduplication.
- Bounded TDSX extraction that rejects traversal, links, encryption, duplicate paths, and oversized payloads.
- Deterministic input inventory with shallow datasource metadata, mapping files, and embedded extract lineage.
- Concurrent parsing of connections, physical relations, relationship expressions, fields, calculations, parameters, filters, groups, and drill paths into versioned Datasource IR.
- Consolidated Datasource IR index with deterministic counts, hashes, duplicate lineage, and per-package parse results.
- Lark-based Tableau formula tokenization with resolved field, parameter, calculation, relation-qualified, and external datasource references.
- Deterministic calculation dependency graphs, cycle detection, semantic classification, findings, and concurrent Metric IR compilation.
- Genie Code semantic-domain proposals with deterministic evidence, membership validation, helper suppression, readable slugs, and target-schema compatibility gates.
- Immutable group mapping contracts with explicit relationship, grain, temporal, and current-record rules.
- Target profiling, native `/importBI` candidate construction, catalog reconciliation, definition capture, semantic evaluation, and JSON/HTML workflow reports.
