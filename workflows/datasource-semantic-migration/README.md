# Datasource Semantic Migration

Standalone Lakeflow Jobs that migrate Tableau datasource definitions (`.tds` and `.tdsx`) into governed candidate Unity Catalog Metric Views.

The workflow separates proposal from execution:

1. Inventory and propose readable semantic groups.
2. Let a user review those groups.
3. Migrate approved groups in parallel.
4. Evaluate and automatically repair each candidate Metric View.

It does **not** create dashboards or prove numerical parity with Tableau. A `PASS_SEMANTIC_ONLY` result means the definition is structurally present and executable under the implemented checks—not that its values match Tableau.

## Architecture

Deployment creates four Jobs:

| Job | Purpose |
|---|---|
| `datasource_semantic_orchestrator` | Inventory datasource files and propose semantic groups. |
| `datasource_semantic_migration` | Approve one proposal and migrate every group. |
| `datasource_semantic_group` | Build and evaluate one candidate Metric View. Invoked by the migration Job. |
| `datasource_semantic_repair` | Apply bounded deterministic or Genie-assisted repairs. |

Deterministic Python owns file validation, parsing, grouping validation, mapping enforcement, target profiling, evaluation, retry control, rollback, and reports. Genie Code is limited to:

- proposing semantic groups;
- running `/importBI` to create a Metric View without creating a dashboard;
- producing a structured semantic repair patch when deterministic code cannot safely translate a supported measure.

## Prerequisites

- `uv` for the local Python environment and wheel build.
- Serverless Lakeflow Jobs and Genie Code task support.
- Permission to deploy Jobs and create Genie Code automations.
- `READ_VOLUME` and `WRITE_VOLUME` on workflow Volumes.
- `USE CATALOG`, `USE SCHEMA`, object-creation privileges in the candidate schema, and `SELECT` on mapped target tables.

The target workspace must already contain:

- a Unity Catalog Volume for workflow inputs, artifacts, and reports;
- candidate and staging schemas;
- a running SQL warehouse;
- the physical Databricks tables referenced by uploaded mappings.

## Install the Databricks CLI

Install the modern Databricks CLI binary, version `1.0.0` or newer. Do not install the legacy `databricks-cli` Python package from PyPI.

On macOS or Linux with Homebrew:

```bash
brew tap databricks/tap
brew install databricks
databricks -v
```

On macOS or Linux without Homebrew:

```bash
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
databricks -v
```

On Windows PowerShell:

```powershell
winget install Databricks.DatabricksCLI
databricks -v
```

Upgrade an existing Homebrew or WinGet installation with `brew upgrade databricks` or `winget upgrade Databricks.DatabricksCLI`.

## Configure an OAuth Profile

Create a descriptive profile for each workspace rather than relying on implicit defaults:

```bash
databricks auth login \
  --host https://<workspace-host> \
  --profile <profile-name>

databricks auth profiles
databricks current-user me --profile <profile-name>
```

The login command opens a browser for OAuth authentication. Do not use a personal access token or set `DATABRICKS_AUTH_STORAGE=plaintext`. Pass `--profile <profile-name>` to every command in this guide.

## Configure a New Environment

Discover the workspace resources that will be referenced by the bundle:

```bash
databricks warehouses list --profile <profile-name>
databricks catalogs list --profile <profile-name>
databricks schemas list <catalog> --profile <profile-name>
```

In `databricks.yml`, add one target per environment. The target name is a local deployment label; it does not need to match the CLI profile name. Use the same target and profile together for validation, deployment, and runs:

```yaml
targets:
  customer-dev:
    mode: development
    variables:
      output_volume_path: /Volumes/<catalog>/<schema>/<volume>
      candidate_catalog: <catalog>
      candidate_schema: bi_migration
      staging_schema: bi_migration_staging
      warehouse_id: <warehouse-id>
      analysis_batch_size: 25
      analysis_batch_workers: 8
```

Do not copy the repository's example catalog, warehouse ID, or Volume path into another workspace. Replace every placeholder with resources from that environment. The workflow creates run folders and candidate Metric Views; it does not create catalogs, schemas, Volumes, warehouses, or mapped source tables.

The default repair limit is three attempts. Acceptance thresholds are defined in `src/datasource_semantic_migration/metric_repair.py`; relationship policy is documented in `config/default-policy.yaml`.

## Install and Deploy

From this directory:

```bash
uv sync
uv run pytest
databricks bundle validate \
  --target customer-dev \
  --profile <profile-name>

uv run python deploy.py \
  --profile <profile-name> \
  --target customer-dev
```

`deploy.py` performs these operations:

1. Strict bundle validation.
2. Wheel build and bundle deployment.
3. Creation or reuse of three Genie Code automations.
4. Replacement of placeholder notebook tasks with native `genie_task` definitions.
5. Output of all four Job IDs and Genie configuration IDs.

Do not deploy this workflow with `databricks bundle deploy` alone. The bundle intentionally contains inspectable placeholder notebooks; `deploy.py` replaces those placeholders with native Genie Code tasks after deployment.

Use `--recreate-automation` only when a stored Genie Code automation must be replaced:

```bash
uv run python deploy.py \
  --profile <profile-name> \
  --target customer-dev \
  --recreate-automation
```

## Prepare Inputs

Provide one Unity Catalog Volume folder with this contract:

```text
/Volumes/<catalog>/<schema>/<volume>/<project>/
  datasources/
    *.tds
    *.tdsx
  mappings/
    table-mapping.yaml
```

`table-mapping.csv` and `table-mapping.yml` are also supported. The filename is significant.

The mapping should identify the physical Databricks tables corresponding to Tableau source tables. Add grain, keys, relationships, temporal predicates, current-record filters, and unit conversions when known. See `datasource-samples/table-mapping.yaml`.

The workflow does not substitute unrelated tables or compatibility views. Missing or ambiguous mapping evidence becomes a blocking finding.

### Optional TWBX conversion

To extract connected datasources from sample workbooks, validate them, and upload only valid TDSX packages:

```bash
uv run python scripts/convert_twbx_to_tdsx.py --upload \
  --profile <profile-name> \
  --volume-root /Volumes/<catalog>/<schema>/<volume>/<project>
```

Local conversion output is written beneath `build/tdsx-conversion/`.

## Run the Workflow

### 1. Propose semantic groups

```bash
databricks bundle run datasource_semantic_orchestrator \
  --target customer-dev \
  --profile <profile-name> \
  --params input_volume_path=/Volumes/<catalog>/<schema>/<volume>/<project>
```

The proposal Job:

- inventories and deduplicates TDS/TDSX files;
- parses Datasource IR and Metric IR in batches;
- asks Genie Code for readable semantic domains;
- validates membership, confidence, helper classification, and target compatibility;
- writes `reports/semantic-grouping-review.{json,html}`;
- stops with `GROUPING_REVIEW_REQUIRED` before creating Metric Views.

### 2. Review and migrate

Open the grouping report, then run:

```bash
databricks bundle run datasource_semantic_migration \
  --target customer-dev \
  --profile <profile-name>
```

With no parameters, the Job uses the latest pending proposal. To migrate an older proposal explicitly:

```bash
databricks bundle run datasource_semantic_migration \
  --target customer-dev \
  --profile <profile-name> \
  --params proposal_run_id=<proposal-job-run-id>
```

The migration Job records the approver, launches one child Job per readable semantic group, and refreshes the run-level report.

### 3. Rerun repair only

Repair an existing candidate without rebuilding it:

```bash
databricks bundle run datasource_semantic_repair \
  --target customer-dev \
  --profile <profile-name> \
  --params group_path=/Volumes/<catalog>/<schema>/<volume>/runs/<run-id>/groups/<group-slug>
```

## How Metric Views Are Evaluated

Evaluation compares Tableau Metric IR with the candidate Metric View YAML and target profile. It currently evaluates definitions and execution, not Tableau-displayed values.

### Per-measure checks

Each source business measure receives a scorecard containing its source name, matched target measure, status, query evidence, failure codes, dependencies, and repair route.

The evaluator checks:

1. **Translation presence** — a target measure matches the normalized Tableau display name.
2. **Supported disposition** — missing external mappings and unsupported metric shapes are explicitly classified.
3. **Aggregation structure** — row-level calculations requiring aggregation must contain an aggregate expression.
4. **Relationship safety** — target-profile relationships marked `BLOCKED` prevent readiness.
5. **Queryability** — every translated measure runs through:

   ```sql
   SELECT MEASURE(`<measure>`) FROM `<catalog>`.`<schema>`.`<metric-view>`
   ```

6. **Regression safety** — a repair cannot turn a previously passing measure query into a failing query.

### Coverage formulas

| Gate | Formula | Default |
|---|---|---:|
| Translation coverage | translated target measures / source business measures | 95% |
| Governed disposition coverage | passed, approved-excluded, or not-comparable measures / source measures | 100% |
| Evidence coverage | measures with retained semantic-pass evidence / source measures | 100% |
| Measure queryability | successful measure queries / translated measures | 100% |
| Unsafe relationships | target-profile relationships with `BLOCKED` status | 0 |
| Blocking findings | unresolved mapping, semantic, or query failures | 0 |

Reports include the numerator, denominator, threshold, gap, and pass/fail result for each gate.

### Status meanings

- `PASS_SEMANTIC_ONLY` — the target definition is present and no implemented semantic/query failure was recorded. Numerical parity is not proven.
- `FAILED_SEMANTICS` — the target definition is missing or structurally invalid.
- `FAILED_VALUE` — the generated Metric View measure query failed. This identifies execution failure, not a Tableau value mismatch.
- `BLOCKED_UNRESOLVED_MAPPING` — required source logic has no approved target mapping.
- `EXCLUDED_UNSUPPORTED` — the source metric cannot safely become a Metric View measure and requires exclusion, a base view, or a governed function.

## Automatic Repair

Repair is deterministic first:

- A bare field with an unambiguous missing aggregate can be patched to `SUM(field)`.
- Missing supported measures or failed measure expressions may request a structured Genie patch.
- External mappings, unsafe relationships, and unsupported metric shapes are not invented.

Current limitation: a failed measure query is routed to Genie without first separating expression errors from permissions, compute, missing-source, or evaluator failures. `METRIC-VIEW-EVALUATION-REPAIR-PLAN.md` defines the planned operational-error classifier and stricter Genie eligibility gate.

Every attempt snapshots the candidate, deploys changes at the same candidate FQN, reruns measure queries, and evaluates progress. The candidate is rolled back when:

- a previously passing query regresses; or
- translated, governed, evidenced, or query-passing counts do not improve and no blocker is removed.

Another attempt starts only after measurable improvement. Otherwise the workflow stops with a specific result such as `NO_PROGRESS`, `BLOCKED_EVIDENCE`, `UNRESOLVABLE_AUTOMATICALLY`, `REGRESSION_REJECTED`, or `EXHAUSTED`.

The current evaluator does not compare Metric View results with Hyper or Tableau worksheet values. See `METRIC-VIEW-EVALUATION-REPAIR-PLAN.md` for planned extensions and current repair limitations.

## Outputs

```text
<output-volume>/runs/<proposal-run-id>/
  manifest.json
  groups/<group-slug>/
    mapping.yaml
    metric-view.yaml
    metric-view.sql
    _internal/
      group-manifest.json
      evaluation.json
      repair/
  reports/
    semantic-grouping-review.json
    semantic-grouping-review.html
    grouping-approval.json
    index.json
    index.html
    groups/<group-slug>/
      migration-review.json
      migration-review.html
      repair-review.json
      repair-review.html
  _internal/
```

Start with the HTML files under `reports/`. Detailed IR, SQL, patches, failure classifications, query results, and retry evidence remain under `_internal/` for troubleshooting.

## Local Development

```bash
uv sync
uv run pytest
```

Key references:

- `SEMANTIC-MIGRATION-PLAN.md` — workflow architecture and input contract.
- `METRIC-VIEW-EVALUATION-REPAIR-PLAN.md` — evaluation and repair design.
- `resources/jobs.yml` — deployed Job DAGs.
- `src/datasource_semantic_migration/metric_repair.py` — implemented scorecards, gates, routing, and progress rules.
