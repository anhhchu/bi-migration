# Repository Guidelines

## Project Structure & Module Organization

- `workflows/datasource-semantic-migration/` is the active semantic-model workflow (its own bundle, `deploy.py`, and tests). Code shared by every BI tool sits in `src/datasource_semantic_migration/`; each BI tool's parsing sits in `sources/<source>/` (today `tableau/`). Prompts sit in `prompts/<source>/` or `prompts/shared/`.
- `workflows/dashboard-migration/` is the paused dashboard workflow: `src/bi_migration/` (inventory, grouping, mapping, preflight, pipeline; `bi-migrate` CLI in `cli.py`), Job `notebooks/`, `prompts/`, `schemas/`, `skills/`, and `tests/` (fixtures in `tests/fixtures/tableau/`). The root `databricks.yml` and `scripts/deploy.py` still deploy its Jobs.
- `app/bi-migration-review/` is the Databricks AppKit application. Backend routes are in `server/server.ts`; React UI code is in `client/src/`.
- Treat `build/` and generated app `dist/` directories as disposable artifacts.

## Build, Test, and Development Commands

From `workflows/datasource-semantic-migration/`:

- `uv run pytest` runs the workflow tests.
- `uv run python deploy.py --profile DEFAULT --target dev` deploys the workflow.

From `workflows/dashboard-migration/`:

- `uv run pytest` runs the paused dashboard migration tests.
- `uv run bi-migrate backend ...` runs its inventory and mapping pipeline.

From the repository root:

- `databricks bundle validate -t dev --profile DEFAULT` validates the App bundle.

From `app/bi-migration-review/`:

- `npm run dev` starts the local AppKit development server.
- `npm run typecheck` checks server and client TypeScript.
- `npm test` runs Vitest tests.
- `npm run lint` and `npm run format` check ESLint and Prettier compliance.
- `npm run build` creates production server and client artifacts.

## Coding Style & Naming Conventions

Use four-space indentation and snake_case for Python functions, modules, and variables. Use two-space indentation, camelCase variables, PascalCase React components, and single quotes in TypeScript. Keep functions focused and preserve existing AppKit component patterns. Use readable kebab-case slugs for user-facing Volume directories; retain stable internal IDs only in metadata and inventory control paths.

## Testing Guidelines

Name Python tests `test_<behavior>.py` and test functions `test_<expected_result>`. Add focused tests beside the affected pipeline module. For UI changes, run `npm run typecheck`, `npm test`, and `npm run build`. Do not repair unrelated failures.

## Commit & Pull Request Guidelines

History is minimal, so use short imperative commit subjects such as `Fix approved mapping path`. Keep commits scoped. Pull requests should explain the user journey affected, list validation commands, reference relevant issues, and include screenshots for UI changes. Never commit credentials, local `.env` files, downloaded Tableau workbooks, or generated Volume artifacts.

## Databricks Safety

Always pass `--profile DEFAULT` for workspace CLI commands. Store production workflow inputs and outputs in configured Unity Catalog Volumes; do not embed local filesystem paths in generated manifests or prompts.

Never set `DATABRICKS_AUTH_STORAGE=plaintext` when invoking the Databricks CLI. Use the profile's standard OAuth credential storage and refresh it with `databricks auth login --profile DEFAULT` when required.

Before any expensive Databricks maintenance operation, explain the implementation and expected cost, then wait for user confirmation. This includes UC Volume "renames" that require recursive copy, artifact path rewriting, verification, and deletion because the CLI has no atomic move command. Report the estimated file count and data size before proceeding.

## Databricks Job Runs

Do not rerun a Databricks Job merely to verify a deployment or repeatedly poll an active run. When execution is required, trigger the Job once with `--no-wait`, report the Databricks run URL immediately, and let the user monitor or repair the run in the workspace. Inspect completed output only when the user explicitly asks for analysis or troubleshooting.
