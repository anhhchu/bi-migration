# bi-migration-review

Databricks App ([AppKit](https://developers.databricks.com/docs/appkit/v0/), React, TypeScript) for migrating Tableau semantic models to Unity Catalog Metric Views. It is the front end for the [datasource semantic workflow](../../workflows/datasource-semantic-migration/README.md); the Jobs do the work, the App starts them and shows the results.

## What users do

| Step       | In the App                                                                                      | Job it runs                      |
| ---------- | ----------------------------------------------------------------------------------------------- | -------------------------------- |
| 1. Propose | Upload `.tds`/`.tdsx` + a table mapping (YAML, JSON, or CSV), or point to existing Volume files | Propose semantic groups          |
| 2. Approve | Check each group's datasources and target tables, then approve                                  | Migrate approved semantic groups |
| 3. Review  | Per group: release gate stages, grouped action items, Catalog Explorer link, full HTML reports  | Semantic group and repair Jobs   |

The Home page explains the evaluation method. **Installation guide** and **Mapping guide** open from the header (`docs/`).

Dashboard migration is hidden while it is being fixed: set `DASHBOARD_MIGRATION_ENABLED` in `client/src/lib/features.ts` to bring it back.

## Run locally

Prerequisites: Node.js 22+, Databricks CLI with an OAuth profile, deployed workflow Jobs.

```bash
cp .env.example .env   # fill in workspace, Volume, and Job IDs
npm install
npm run dev            # http://localhost:8000
```

Locally the App calls Databricks as your CLI profile; when deployed it reads Volumes as the signed-in user and starts Jobs as its service principal.

## Checks

```bash
npm run typecheck
npm test
npm run lint
npm run format
npm run build
```

## Deploy

First-time install (workflow and App together), from the repository root:

```bash
python3 scripts/install.py --profile my-ws --catalog <existing-catalog>
```

Redeploy only the App after changes:

```bash
python3 scripts/deploy.py --profile my-ws --target dev --component app
```

Use these scripts rather than `databricks apps deploy`; they bind the Jobs and Volumes to the App. See [docs/INSTALLATION_GUIDE.md](docs/INSTALLATION_GUIDE.md).

## Project layout

```
client/src/
  App.tsx            Steps, run browser, group review
  HomePage.tsx       Landing page and evaluation method
  DocsDialog.tsx     Renders docs/*.md in the App
  lib/               Status labels, saved inputs, Catalog Explorer links, feature switches
client/public/       Static assets (Home page screenshot)
server/
  server.ts          API routes: uploads, Volume inputs, runs, approval, Job status
  semantic-input.ts  Input-folder validation
docs/                Installation and mapping guides
app.yaml             App command and resource bindings
```
