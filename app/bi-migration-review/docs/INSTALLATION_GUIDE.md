# Installation guide

Install the semantic migration workflow and this App in four steps.

## 1. Install the tools

- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) 1.0 or newer (not the legacy `databricks-cli` Python package)
- Python 3.11+ and [uv](https://docs.astral.sh/uv/) (`brew install uv`, or `pip install uv`)

```bash
brew tap databricks/tap && brew install databricks   # macOS/Linux; Windows: winget install Databricks.DatabricksCLI
databricks -v
```

Get the code:

```bash
git clone https://github.com/anhhchu/bi-migration.git
cd bi-migration
```

## 2. Sign in

```bash
databricks auth login --host https://<workspace-host> --profile my-ws
```

## 3. Preview

From the repository root:

```bash
python3 scripts/install.py --profile my-ws --catalog <existing-catalog> --dry-run
```

This only reads the workspace and prints the plan: warehouse, schemas, Volumes, and what will be created.

## 4. Install

```bash
python3 scripts/install.py --profile my-ws --catalog <existing-catalog>
```

The script checks your access, picks a SQL warehouse, shows a plan, and asks before creating anything. It then:

1. Creates, if missing, schema `bi_migration` (candidate Metric Views) and its Volumes `semantic_workflows` (run artifacts) and `migration_inputs` (uploads). Point to existing ones instead with the options below.
2. Deploys the workflow Jobs and their Genie Code tasks.
3. Deploys the App, connected to those Jobs and Volumes, and prints its URL.

| Option                                 | Use it to                                   |
| -------------------------------------- | ------------------------------------------- |
| `--schema <name>`                      | Use another or an existing schema           |
| `--output-volume <catalog.schema.vol>` | Reuse an existing Volume for run artifacts  |
| `--warehouse-id <id>`                  | Choose the SQL warehouse                    |
| `--app-name <name>`                    | Name the App (unique per workspace)         |
| `--upload-volume <catalog.schema.vol>` | Reuse an existing upload Volume             |
| `--dry-run`                            | See the plan without changing the workspace |
| `--yes`                                | Skip the confirmation                       |
| `--configure-only`                     | Record settings for an existing install     |

Your choices are saved per CLI profile (one profile per workspace) in `.databricks/bi-migration/<profile>.json`, which is gitignored. Later deploys read them, so each workspace keeps its own catalog, Volumes, and warehouse. Run the same command again to change them or update the installation.

No permission to create schemas or Volumes? Ask an admin for an existing schema and two Volumes, then:

```bash
python3 scripts/install.py --profile my-ws --catalog <catalog> --schema <schema> \
  --output-volume <catalog>.<schema>.<volume> --upload-volume <catalog>.<schema>.<volume>
```

## Permissions

| You have                                         | Do this                                                                                   |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| `CREATE SCHEMA` on the catalog                   | Nothing extra; the installer creates the schema and Volumes                               |
| An existing schema with `CREATE VOLUME`          | `--schema <existing>`; the installer creates the two Volumes in it                        |
| An existing schema and Volumes, no create rights | `--schema <existing> --output-volume <c.s.v> --upload-volume <c.s.v>`; nothing is created |

Always needed: `USE CATALOG` and `USE SCHEMA`, `CREATE TABLE` on the schema (Metric Views are created there), `READ VOLUME` and `WRITE VOLUME` on both Volumes, `SELECT` on the Databricks tables your mapping points to, and permission to create Jobs and Apps. Give App users `READ VOLUME` on the run-artifacts Volume.
