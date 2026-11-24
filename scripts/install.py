#!/usr/bin/env python3
"""One-step install of the semantic migration workflow and the review App.

Prerequisites: Databricks CLI with an OAuth profile, Python 3.11+, and uv.

    databricks auth login --host https://<workspace> --profile my-ws
    python3 scripts/install.py --profile my-ws --catalog main

The script checks access, picks a SQL warehouse, creates the schemas and Volumes it
needs (after confirmation), deploys the workflow Jobs, then deploys the App wired to them.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from install_settings import ROOT, WORKFLOW_DIR, apply_settings, save_settings  # noqa: E402

WORKFLOW = WORKFLOW_DIR


def step(message: str) -> None:
    print(f"\n▸ {message}", flush=True)


def fail(message: str) -> None:
    print(f"\n✖ {message}", file=sys.stderr)
    sys.exit(1)


def cli(profile: str, *arguments: str, check: bool = True) -> Any:
    command = ["databricks", *arguments, "--profile", profile, "-o", "json"]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        if not check:
            return None
        fail(f"{' '.join(command[1:4])} failed: {(result.stderr or result.stdout).strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def run_script(command: list[str], *, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    """Run a deploy script and return the JSON summary it prints last."""
    result = subprocess.run(command, cwd=cwd, env={**os.environ, **env}, capture_output=True, text=True)
    if result.returncode:
        fail(f"{' '.join(command[:2])} failed:\n{(result.stderr or result.stdout).strip()[-2000:]}")
    output = result.stdout.strip()
    return json.loads(output[output.rfind("\n{") + 1 :] if "\n{" in output else output)


def pick_warehouse(profile: str, requested: str | None) -> dict[str, Any]:
    warehouses = cli(profile, "warehouses", "list") or []
    if requested:
        match = next((item for item in warehouses if item["id"] == requested), None)
        if not match:
            fail(f"SQL warehouse {requested} was not found or is not visible to this profile.")
        return match
    if not warehouses:
        fail("No SQL warehouse is available. Create one (serverless recommended) or pass --warehouse-id.")
    # Prefer a running warehouse, then serverless, then the starter warehouse every workspace has.
    def rank(item: dict[str, Any]) -> tuple[bool, bool, bool]:
        return (
            item.get("state") != "RUNNING",
            not item.get("enable_serverless_compute"),
            "starter" not in str(item.get("name", "")).casefold(),
        )

    return sorted(warehouses, key=rank)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the BI semantic migration workflow and App.")
    parser.add_argument("--profile", required=True, help="Databricks CLI profile (OAuth)")
    parser.add_argument("--catalog", required=True, help="Existing Unity Catalog catalog to install into")
    parser.add_argument("--schema", default="bi_migration", help="Schema for candidate Metric Views and Volumes")
    parser.add_argument("--warehouse-id", help="SQL warehouse ID (default: running, serverless, or starter warehouse)")
    parser.add_argument("--upload-volume", help="Existing Volume for App uploads, as catalog.schema.volume")
    parser.add_argument("--target", default="dev", help="Bundle target name")
    parser.add_argument("--yes", action="store_true", help="Create missing schemas and Volumes without asking")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without changing the workspace")
    parser.add_argument(
        "--configure-only",
        action="store_true",
        help="Save these settings for an existing installation without creating or deploying anything",
    )
    args = parser.parse_args()

    staging_schema = f"{args.schema}_staging"
    output_volume = f"{args.catalog}.{args.schema}.semantic_workflows"
    upload_volume = args.upload_volume or f"{args.catalog}.{args.schema}.migration_inputs"
    if len(upload_volume.split(".")) != 3:
        fail("--upload-volume must be catalog.schema.volume")

    step("Checking prerequisites")
    for tool in ("databricks", "uv"):
        if not shutil.which(tool):
            fail(f"'{tool}' is not installed. See the Installation guide.")
    user = cli(args.profile, "current-user", "me", check=False)
    if not user:
        fail(f"Profile '{args.profile}' is not signed in. Run: databricks auth login --profile {args.profile}")
    print(f"  Signed in as {user.get('userName')}")
    if not cli(args.profile, "catalogs", "get", args.catalog, check=False):
        fail(f"Catalog '{args.catalog}' was not found, or you lack USE CATALOG on it.")
    warehouse = pick_warehouse(args.profile, args.warehouse_id)
    print(f"  SQL warehouse: {warehouse['name']} ({warehouse['id']}); choose another with --warehouse-id")

    missing = []
    for schema in (args.schema, staging_schema):
        if not cli(args.profile, "schemas", "get", f"{args.catalog}.{schema}", check=False):
            missing.append(("schema", schema))
    for volume in (output_volume, upload_volume):
        if not cli(args.profile, "volumes", "read", volume, check=False):
            missing.append(("volume", volume))

    print("\nPlan:")
    print(f"  Candidate Metric Views  {args.catalog}.{args.schema}")
    print(f"  Staging schema          {args.catalog}.{staging_schema}")
    print(f"  Run artifacts Volume    {output_volume}")
    print(f"  Upload Volume           {upload_volume}")
    print(f"  Create first            {', '.join(name for _, name in missing) or 'nothing'}")
    print("  Then deploy             semantic workflow Jobs, dashboard Jobs, and the App")
    settings = {
        "catalog": args.catalog,
        "schema": args.schema,
        "staging_schema": staging_schema,
        "output_volume": output_volume,
        "upload_volume": upload_volume,
        "warehouse_id": warehouse["id"],
        "target": args.target,
    }
    if args.dry_run:
        return
    if args.configure_only:
        if missing:
            fail(f"These do not exist yet: {', '.join(name for _, name in missing)}. Run without --configure-only.")
        saved = save_settings(args.profile, settings)
        apply_settings(settings, args.target)
        print(f"\n✔ Saved settings to {saved.relative_to(ROOT)}; deploy scripts will use them.")
        return
    if missing and not args.yes:
        if input("\nCreate the missing objects and deploy? [y/N] ").strip().lower() not in {"y", "yes"}:
            fail("Cancelled; nothing was changed.")

    for kind, name in missing:
        step(f"Creating {kind} {name}")
        if kind == "schema":
            cli(args.profile, "schemas", "create", name, args.catalog)
        else:
            catalog, schema, volume = name.split(".")
            cli(args.profile, "volumes", "create", catalog, schema, volume, "MANAGED")

    saved = save_settings(args.profile, settings)
    apply_settings(settings, args.target)
    print(f"  Saved settings to {saved.relative_to(ROOT)}")

    step("Deploying the semantic workflow (Jobs and Genie Code tasks)")
    workflow = run_script(
        ["uv", "run", "python", "deploy.py", "--profile", args.profile, "--target", args.target],
        cwd=WORKFLOW,
        env={},
    )
    print(f"  Propose Job {workflow['proposal_job_id']} · Migrate Job {workflow['migration_job_id']}")

    step("Deploying the App")
    run_script(
        [
            sys.executable, "scripts/deploy.py",
            "--profile", args.profile,
            "--target", args.target,
            "--component", "all",
            "--datasource-semantic-proposal-job-id", str(workflow["proposal_job_id"]),
            "--datasource-semantic-migration-job-id", str(workflow["migration_job_id"]),
        ],
        cwd=ROOT,
        env={},
    )
    app = cli(args.profile, "apps", "get", "bi-migration-review", check=False) or {}

    print("\n✔ Installed.")
    print(f"  App: {app.get('url', 'see Compute → Apps in your workspace')}")
    print(f"  Put Tableau files in a Volume folder with datasources/ and mappings/table-mapping.yaml,")
    print(f"  or upload them in the App. Give App users READ VOLUME on {output_volume}.")


if __name__ == "__main__":
    main()
