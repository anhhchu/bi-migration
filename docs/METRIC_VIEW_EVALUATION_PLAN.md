# Metric View Evaluation Plan

## 1. Purpose

Evaluate whether a Unity Catalog Metric View created from Tableau workbooks preserves the intended business semantics, even when the Databricks target uses different data, grain, relationships, temporal modeling, or physical schemas.

The system must automate evaluation for the full metric portfolio. Reviewers handle only ambiguous or failed evidence; they do not author one validation contract per metric.

## 2. Evaluation Principles

1. **Semantic equivalence before numeric equality.** A correct metric must preserve definition, population, aggregation, units, filters, and time behavior.
2. **Compare at a safe common grain.** Never compare source and target rows when their grains differ.
3. **Use deterministic evidence for pass/fail.** Genie Code can translate and explain; deterministic parsers, lineage, SQL, and rules decide validation.
4. **Make non-comparability explicit.** Missing source data or incompatible populations must produce `NOT_COMPARABLE`, not false success or failure.
5. **Persist every decision.** Inputs, signatures, generated SQL, tolerances, results, and reviewer dispositions must be reproducible.
6. **Test translation and target mapping separately.** Source logic can be validated on source data even when production source and target values are intentionally different.

## 3. Evidence Chain

Evaluate three independent links rather than presenting one blended accuracy score:

| Link | Automated evidence | Meaning |
|---|---|---|
| Tableau extract to staged source tables | Row counts, numeric-column aggregates, schemas, and content hashes computed independently in Hyper and Spark | Proves the development fixture preserves the extract |
| Tableau formulas to Metric View definitions | Worksheet-aware formula execution on Hyper compared with a shadow Metric View over the staged extract | Proves translation correctness on a common dataset |
| Approved Databricks mappings to production Metric View | Grain, uniqueness, temporal joins, fanout, orphan, unit, filter, and coverage tests on target tables | Proves safe target-model implementation |

Dashboard behavior and production-data plausibility are reported separately. Passing the second link does not prove the production mapping, and passing the third link does not prove Tableau semantic parity.

## 4. Required Inputs

### Tableau evidence

- Workbook, datasource, field, parameter, relationship, and calculation inventory
- Resolved calculation dependency graph, including aliases and `Calculation_<id>` references
- Extracted Hyper data when legally and technically available
- Dashboard filters, parameter defaults, date logic, and worksheet query behavior
- Tableau aggregation, LOD, table-calculation, and null-handling semantics
- Worksheet-level datasource filters, context filters, sheet filters, parameter defaults, and default aggregations
- Published worksheet underlying data or manually recorded headline values when available

### Databricks evidence

- Approved mapping contract and revision/hash
- Target table schemas, constraints, comments, tags, and inferred grains
- Confirmed relationship graph, cardinality, temporal predicates, and record filters
- Generated Metric View YAML and UC metadata
- Dashboard configurations produced by `/importBI`
- Target data profiles and validation-query results

## 5. Canonical Semantic Intermediate Representation

Compile every source KPI and target measure into a common Metric IR:

```yaml
metric_id: sales
display_name: Sales
expression_tree: sum(net_amount_cents / 100.0)
aggregation: sum
business_entity: sales_order_line
source_grain: one row per Tableau order line
target_grain: one current sales order line
dimensions: [order_date, category, region]
filters: []
time_field: order_date
time_semantics: calendar
unit: USD
null_semantics: ignore_null_inputs
distinct_keys: []
parameter_dependencies: []
temporal_semantics: order-date as-of dimensions
```

The compiler normalizes commutative expressions, aliases, casts, unit conversions, filter order, and equivalent date predicates before comparison.

## 6. Automated Evaluation Layers

### Layer A: structural completeness

- Every retained Tableau business metric maps to a Metric View measure or an explicit exclusion.
- Every referenced field resolves through the approved contract.
- Calculation dependencies are acyclic or have a recorded unsupported reason.
- Display-only helpers, navigation fields, and layout calculations are excluded from business-metric coverage.

### Layer B: `/importBI` translation conformance

Validate the generated local Metric View against the translation rules used by `/importBI`; do not assume that a successfully generated YAML definition is semantically correct.

- Tableau row-level calculations are classified as dimensions and aggregate calculations as measures, with ambiguous mixed-level calculations flagged.
- Tableau `FIXED`, `INCLUDE`, and `EXCLUDE` LOD expressions retain their declared scope after translation to supported Metric View constructs.
- Power BI composed measures reference governed measures rather than re-aggregating their raw inputs.
- Global row filters appear once at the semantic-model level and are not duplicated in source SQL.
- Parameters preserve datatype, quoting, defaults, allowed values, and dependency behavior.
- Composed measures use measure references consistently; widget expressions do not contain unsupported measure arithmetic.
- Percent-of-total expressions preserve the correct denominator independently of the query grouping.
- Dates remain native temporal types, and formatting metadata does not change calculation types.
- Generated dimensions and measures have stable, readable names and retain source display names as metadata.
- Undefined bin widths, oversized literal groups, read-only shared assets, and other unsupported constructs become explicit exclusions rather than approximations.

These rules are implementation-specific claims from Genie Code and must be verified against representative generated dashboard configurations and Metric View YAML. They are regression assertions, not substitutes for semantic or value validation.

### Layer C: relationship and grain safety

- Infer candidate keys and table grain from constraints and bounded profiling.
- Measure uniqueness, null rates, join coverage, unmatched keys, and join fanout.
- Reject joins that amplify the fact grain beyond the declared tolerance.
- Validate bitemporal joins using event-date business validity and current system-record filters.
- Confirm semi-additive metrics are not aggregated across invalid dimensions or time ranges.

### Layer D: semantic signature comparison

Compare normalized source and target signatures for:

- Aggregation and distinctness
- Numerator/denominator composition
- Population and filters
- Units, currency, scaling, and formatting
- Time field, calendar, period comparison, and parameter behavior
- Null, zero-division, and missing-member handling
- LOD scope and table-calculation dependencies

Produce field-level differences rather than a single opaque score.

### Layer E: executable validation

Generate source and target queries automatically. Select the lowest safe common comparison grain from shared dimensions and business keys. Examples:

- Order-line target vs order source: aggregate target to order before comparison.
- Daily source vs monthly target: aggregate both to month.
- Versioned dimensions: resolve target attributes as of the source business event date.

Store query text, parameters, row counts, runtime, and result hashes with every evaluation.

For development evaluation, create a temporary **shadow Metric View** with the candidate definition but a source redirected to Hyper-derived staging tables. For each worksheet:

1. Resolve all referenced calculations, including copied and internal Tableau calculation IDs.
2. Apply that worksheet's datasource, context, sheet, and parameter filters in Tableau order.
3. Execute the source expression with the Hyper engine.
4. Query the shadow Metric View using the same dimensions and effective filter population.
5. Compare cells at the worksheet's displayed grain.

Parameter defaults that fall outside the fixture's date range must be adapted through an explicit test-only parameter override recorded in the result; the production definition must not be changed for the test.

### Layer F: dashboard behavior coverage

Verify that Metric View measures can satisfy the dashboard configurations:

- Required dimensions and filter fields exist.
- Parameterized periods can be represented.
- Worksheet queries can be expressed without unapproved tables.
- Expected drill, grouping, and sorting dimensions are available.
- Unsupported Tableau-only behavior is recorded separately from metric correctness.
- Every governed KPI returns a result for valid default current-period, prior-period, YTD, and current-month scenarios where applicable.
- Known target-domain differences, such as reduced geography or highly correlated dimensions, are reported as data-shape warnings rather than translation failures.

## 7. Strategies When Numbers Are Comparable

### Exact snapshot comparison

Use when Tableau Hyper/source data and target data represent the same snapshot. Compare metric outputs across totals and stratified slices. Counts and identifiers normally require exact equality.

### Tolerance comparison

Use explicit tolerances for floating-point arithmetic, currency rounding, timezone boundaries, or known ingestion lag. Tolerances are inferred from datatype and unit, then overridden only by governed policy.

### Overlapping-period comparison

When systems contain partially overlapping data, discover the intersection of business dates and keys. Compare only that declared population and report coverage separately.

### Bridge-key comparison

When identifiers changed, use an approved crosswalk. Track matched, unmatched, and one-to-many bridge rates before comparing values.

### Published Tableau worksheet comparison

When Tableau Server or Cloud is available, export worksheet underlying or crosstab data at governed parameter defaults and compare cell-by-cell with the Metric View. A small set of manually captured headline values is acceptable as supplemental evidence, but not as portfolio-scale automation.

## 8. Strategies When Dashboard Numbers Cannot Be Compared

Numeric unavailability must not stop evaluation. Apply the strongest available alternatives in order.

### Static semantic equivalence

Compare normalized formulas, aggregations, filters, parameters, units, and lineage without executing source data. This can prove definition parity but not data parity.

### Invariant and conservation tests

Validate properties that should remain true regardless of dataset:

- Profit equals sales minus cost when that identity is declared.
- Component totals reconcile to overall totals.
- Distinct counts never exceed row counts.
- Returned orders do not exceed orders.
- Ratios remain within governed bounds.
- Current/prior period components use disjoint or expected windows.

### Metamorphic tests

Execute transformations with predictable outcomes:

- Adding a dimension should preserve the grand total.
- Narrowing a date filter should not increase additive totals when values are non-negative.
- Reordering filters should not change results.
- Equivalent parameterizations should return equivalent measures.
- Duplicating a dimension row must not duplicate facts.

### Synthetic golden scenarios

Generate small, purpose-built target datasets with known answers for joins, temporal versions, returns, distinct counts, LOD behavior, and period comparisons. Run the Metric View against these controlled cases independently of production data.

### Source-fixture shadow evaluation

If a workbook contains a Hyper extract, use it only as an isolated development fixture. Redirect a shadow copy of the Metric View to the staged extract and compare worksheet-aware results. This validates formula translation even though the production bitemporal dataset has different values and grain.

### Distribution and shape tests

When populations differ but represent similar businesses, compare non-binding diagnostics:

- Null and zero rates
- Cardinality and category coverage
- Sign, range, monotonicity, and quantiles
- Seasonal or directional patterns
- Contribution shares by major dimensions

These tests can produce warnings but should not claim numeric equivalence.

### Queryability and answerability tests

Compile representative dashboard and Genie questions to Metric View SQL. Verify that required measures, dimensions, filters, and parameter combinations are expressible and execute successfully. This validates usability, not value parity.

### Expert-evidence comparison

When no source execution is possible, compare against approved definitions from business glossaries, mapping documents, SQL specifications, or certified reports. Record the evidence source and approval owner.

## 9. Automated Classification

Each metric receives one primary status:

- `PASS_EXACT`
- `PASS_WITH_TOLERANCE`
- `PASS_SEMANTIC_ONLY`
- `PASS_INVARIANTS_ONLY`
- `PASS_SOURCE_FIXTURE`
- `NOT_COMPARABLE_NO_SOURCE_DATA`
- `BLOCKED_UNRESOLVED_MAPPING`
- `BLOCKED_UNSAFE_GRAIN`
- `FAILED_SEMANTICS`
- `FAILED_VALUE`
- `EXCLUDED_UNSUPPORTED`

Confidence is reported separately from status. A semantic-only pass must never be displayed as exact numeric validation.

## 10. Exception-First Human Review

Reviewers see only:

- High-impact semantic differences
- Unsafe or ambiguous joins/grains
- Unresolved calculations or parameters
- Numeric failures outside tolerance
- Metrics supported only by weak evidence

Available dispositions are `fix_now`, `accept`, `defer`, and `not_applicable`. Accepted gaps require rationale and owner. Fixes generate targeted Metric View, dashboard, or Agent remediation tasks; they do not trigger full workbook re-import by default.

## 11. Metric View Repair Workflow

Route each failed criterion to the asset that owns the defect:

| Failure class | Repair target |
|---|---|
| Missing or incorrect measure, aggregation, LOD, filter, parameter, or format | Candidate Metric View definition |
| Wrong target field, datatype, unit, grain, key, or temporal rule | New approved mapping-contract revision |
| Join fanout, orphaned dimensions, or unsafe bitemporal resolution | Certified base view or relationship definition |
| Missing governed target data | Approved additional datasource or explicit unsupported exception |
| Metric is correct but worksheet behavior differs | Existing dashboard configuration |
| Production values differ for an approved population or model reason | Evidence record; no semantic repair |

The repair controller classifies and routes failures automatically. Routine repairs do not require reviewer decisions. Human review is reserved for terminal ambiguity where multiple business definitions remain equally plausible after deterministic evidence collection.

For every repairable finding:

1. Persist the failure ID, affected metric and worksheets, expected behavior, evidence, and reproducible SQL.
2. Create a versioned candidate revision; never overwrite an approved contract or last validated Metric View definition.
3. Apply a deterministic repair rule when the failure matches a supported pattern.
4. Invoke Genie Code only for semantic translation not covered by deterministic rules, and require a structured patch rather than self-approval.
5. Update the existing candidate asset in place without rerunning `/importBI`.
6. Rerun failed tests and transitive dependency tests.
7. Reject regressions in previously passing critical metrics.
8. Promote only after blocking findings pass or receive a deterministic non-comparable or unsupported classification.

### Deterministic mapping-contract revision

Mapping defects are repaired before the Metric View. Never modify approved YAML in place.

1. Copy the approved contract into a new immutable revision such as `mapping/revisions/approved-r002.yaml`.
2. Record parent hash, revision ID, triggering findings, generator version, evidence hashes, and creation time in a sidecar manifest.
3. Infer candidate relationships from source relationships, approved field lineage, UC columns and types, declared grains, PK/FK constraints, and bounded profiling.
4. Rank candidates by mapped-key agreement, datatype compatibility, source lineage, key uniqueness, temporal compatibility, coverage, and fanout.
5. Apply only one unambiguous highest-confidence candidate.
6. Validate the complete revised relationship graph, not only the changed edge.
7. Auto-approve only when every policy gate passes; otherwise classify `UNRESOLVABLE_AUTOMATICALLY`.
8. Atomically update the group manifest pointer, rebuild the candidate Metric View, and rerun evaluation.
9. Restore the prior manifest pointer and candidate definition on any blocking regression.

Automatic approval requires:

- Referenced tables and columns exist with compatible datatypes.
- The declared fact grain remains unique after all joins.
- Each fact row matches at most one applicable dimension version.
- Temporal intervals do not overlap per business key.
- Join fanout is exactly `1.0` unless governed policy permits otherwise.
- Orphan and unmatched-key rates satisfy configured policy.
- Current-record predicates match the physical null or sentinel convention.
- Representative dependent measures preserve declared invariants.
- Previously passing critical metrics do not regress.

### Generic deterministic repair registry

Rules operate on Metric IR and structured findings, never catalog-, table-, workbook-, or field-specific names.

| Failure code | Deterministic action |
|---|---|
| `MISSING_RELATIONSHIP` | Infer candidate key paths, profile them, and create a contract revision when one path passes every gate. |
| `INVALID_JOIN_KEY` | Replace nonexistent or incompatible keys with an approved lineage-equivalent path. |
| `TEMPORAL_RULE_MISMATCH` | Apply the target's declared valid-time and current-record convention, then validate interval uniqueness. |
| `UNSAFE_FANOUT` | Reject the edge or generate a certified base view resolving one row per fact key. |
| `FIELD_EXPRESSION_MISMATCH` | Patch mapped column, cast, unit conversion, or null behavior from approved lineage. |
| `AGGREGATION_MISMATCH` | Patch only when the source calculation unambiguously establishes aggregation. |
| `MEASURE_DEPENDENCY_ERROR` | Rewrite measure references and retest the transitive dependency graph. |
| `METADATA_MISMATCH` | Patch comments, display names, synonyms, formats, and native temporal types. |
| `UNSUPPORTED_METRIC_SHAPE` | Route to a certified base view or governed SQL function. |

Genie Code is allowed only for complex source-calculation translation, opaque dependency resolution, or selecting a valid Metric View/base-view/function representation. Its output must conform to a patch schema and pass the same deterministic gates.

### Repair-loop control

```text
snapshot_candidate
  -> evaluate_metric_view
  -> classify_failures
  -> revise_mapping_contract
  -> repair_certified_base_view
  -> apply_deterministic_metric_patch
  -> genie_semantic_fallback
  -> deploy_candidate_revision
  -> reevaluate_affected_metrics
  -> regression_gate
  -> finalize_or_retry
```

Stop when evaluation passes, the failure signature repeats, a repair regresses passing metrics, the maximum attempt count is reached, or evidence cannot establish one correct repair. `UNRESOLVABLE` must never repeat the same repair method without new evidence.

### Repair artifacts

```text
semantic/repair/runs/<repair-run-id>/attempt-<n>/
  input-evaluation.json
  failure-classification.json
  contract-revision.yaml
  contract-revision-manifest.json
  deterministic-patch.json
  genie-patch.json
  candidate-before.yaml
  candidate-after.yaml
  affected-tests.json
  regression-results.json
  summary.json
```

Use lifecycle states `DRAFT`, `EVALUATING`, `NEEDS_REPAIR`, `VALIDATED`, and `PROMOTED`. Retain the last validated definition and manifest pointer for rollback.

### Repair implementation sequence

1. **Structured findings:** replace free text with failure code, owner, affected objects, expected behavior, evidence, and candidate keys or expressions.
2. **Routing and safety:** implement classification, immutable attempt directories, no-progress detection, and immediate stop on `UNRESOLVABLE`.
3. **Contract revisions:** implement versioned copy, parent hash, schema validation, manifest pointer update, and rollback.
4. **Relationship profiling:** implement existence, datatype, uniqueness, overlap, orphan, coverage, fanout, and temporal-as-of tests.
5. **Relationship rules:** implement missing relationship, invalid key, temporal convention, and unsafe-fanout repairs.
6. **Metric YAML patching:** implement metadata, units, fields, aggregations, parameters, and dependency patches.
7. **Dependency-aware evaluation:** retest changed metrics and consumers, then run critical regressions.
8. **Genie fallback:** accept only schema-valid structured patches for uncovered calculation shapes.
9. **Semantic-build integration:** complete evaluation and repair before Genie Agent creation.
10. **App integration:** show attempts, changes, evaluation deltas, rollback, terminal exceptions, and Job links.

### Repair test plan

- Repair a missing star-schema relationship from an exact mapped business key.
- Repair a snowflake path through an intermediate dimension without duplicating facts.
- Validate SCD2 and bitemporal joins using null and sentinel current-record conventions.
- Reject ambiguous candidate keys rather than guessing.
- Reject many-to-many and overlapping temporal relationships for unsafe fanout.
- Patch unit, aggregation, measure reference, parameter, and metadata defects deterministically.
- Route non-reaggregatable or selection-dependent measures to governed functions.
- Route complex LOD or opaque calculations once to the Genie fallback.
- Test missing output, malformed patch, repeated signature, and maximum attempts.
- Verify regression rollback restores the prior contract pointer and Metric View definition.
- Classify different production data as `NOT_COMPARABLE`, not endless repair.
- Run the same rules across flat, star, snowflake, SCD2, bitemporal, bridge-table, Tableau, and Power BI fixtures.

End-to-end acceptance requires a successful deterministic repair for every supported rule, a safe rejection for every unsafe pattern, reproducible artifacts, and no hardcoded asset names.

## 12. Pipeline and Artifacts

Add deterministic tasks after Metric View creation:

```text
compile_metric_ir
  -> validate_relationships_and_grain
  -> generate_validation_queries
  -> execute_comparable_tests
  -> execute_invariants_and_metamorphic_tests
  -> aggregate_metric_evaluation
```

Persist run-scoped artifacts:

```text
semantic/evaluation/runs/<evaluation-run-id>/
  source-metric-ir.json
  target-metric-ir.json
  semantic-diff.json
  grain-validation.json
  query-plan.json
  query-results.json
  shadow-metric-view.yaml
  worksheet-comparison.json
  invariant-results.json
  metric-scorecard.json
  evaluation-summary.json
```

The summary records workbook hashes, mapping-contract hash, Metric View definition hash, source/target snapshot identifiers, and upstream import run ID. Results become stale when any hash or live asset update timestamp changes.

## 13. Scale and Performance

- Compile calculations once per workbook and reuse lineage across metrics.
- Batch schema inspection and profiling queries by table.
- Sample only for discovery; use full scans for final critical validations where required.
- Cache comparison results by definition and snapshot hash.
- Execute independent metric groups in bounded parallelism.
- Prioritize business-critical and dashboard-visible metrics before long-tail candidates.

## 14. Rollout Plan

### Phase 1: deterministic semantic comparison

Implement Metric IR, expression normalization, coverage, relationship/grain checks, and exception reports using existing Tableau inventory and Metric View YAML.

### Phase 2: executable comparisons

Extract Hyper data for development baselines, generate common-grain queries, execute target SQL, and implement tolerance policies.

### Phase 3: non-numeric evidence

Add invariant, metamorphic, synthetic-golden, and queryability tests for customers without comparable source data.

### Phase 4: portfolio automation

Add run-scoped evaluation artifacts, stale-result detection, targeted remediation, criticality tiers, and cross-group scorecards.

## 15. Acceptance Criteria

- No developer-authored validation contract is required for ordinary metrics.
- At least 90% of supported Tableau metrics receive an automatic semantic classification.
- Every retained measure has lineage to source calculations and approved target fields.
- Unsafe fanout blocks validation before numeric comparison.
- Numeric results state population, grain, snapshot, and tolerance.
- Non-numeric strategies never claim value parity.
- Repeated runs are isolated and reproducible by hashes and run IDs.
- Review workload is limited to exceptions and governed acceptance decisions.
- The App links every failure to evidence, generated SQL, affected dashboards, and targeted remediation.
