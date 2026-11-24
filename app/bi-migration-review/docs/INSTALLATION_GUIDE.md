# Installation guide

Set up the BI Migration App and its Databricks workflow. For how to use the App, open its Home page.

## Prerequisites

You need:

- the modern Databricks CLI, version 1.0.0 or newer;
- `uv`, Python 3.11+, Node.js, and npm;
- a Databricks workspace with Serverless Lakeflow Jobs and Genie Code tasks;
- a running SQL warehouse;
- Unity Catalog schemas and Volumes for inputs, candidates, staging, and workflow artifacts;
- permission to deploy Jobs and Apps and to create Genie Code automations;
- `READ_VOLUME`, `WRITE_VOLUME`, `USE CATALOG`, `USE SCHEMA`, object-creation, and mapped-table `SELECT` privileges.

### 1. Install the Databricks CLI

macOS or Linux with Homebrew:

```bash
brew tap databricks/tap
brew install databricks
databricks -v
```

macOS or Linux without Homebrew:

```bash
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
databricks -v
```

Windows PowerShell:

```powershell
winget install Databricks.DatabricksCLI
databricks -v
```

Do not install the legacy `databricks-cli` Python package.

### 2. Create an OAuth Profile

```bash
databricks auth login \
  --host https://<workspace-host> \
  --profile <profile-name>

databricks auth profiles
databricks current-user me --profile <profile-name>
```

Use OAuth, never plaintext credential storage. Pass the selected profile explicitly to every command.

### 3. Configure the Datasource Semantic Workflow

Add a target in `workflows/datasource-semantic-migration/databricks.yml`:

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

The catalog, schemas, Volume, warehouse, and mapped physical tables must already exist.

Deploy the four standalone workflow Jobs:

```bash
cd workflows/datasource-semantic-migration
uv sync
uv run pytest
uv run python deploy.py \
  --profile <profile-name> \
  --target customer-dev
```

Use this `deploy.py`; a plain bundle deployment does not restore the native Genie Code tasks.

### 4. Configure and Deploy the App

Update the selected target in the repository-root `databricks.yml` with the workspace Volume and Job IDs. Then deploy editable dashboard/semantic Jobs and the App:

```bash
cd <repository-root>
uv sync

python3 scripts/deploy.py \
  --profile <profile-name> \
  --target <target> \
  --component jobs

python3 scripts/deploy.py \
  --profile <profile-name> \
  --target <target> \
  --component app \
  --datasource-semantic-proposal-job-id <proposal-job-id> \
  --datasource-semantic-migration-job-id <migration-job-id> \
  --datasource-semantic-volume-full-name <catalog.schema.volume>
```

The deploy helper builds the App, binds the Jobs and Volumes, deploys the bundle, and starts the App.

Verify it:

```bash
databricks apps get bi-migration-review \
  --profile <profile-name> \
  -o json
```

