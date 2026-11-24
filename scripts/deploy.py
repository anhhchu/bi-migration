#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from install_settings import apply_settings, require_settings  # noqa: E402
JOB_PARAMETERS = [
    {"name": "run_id", "default": ""},
    {"name": "group_id", "default": ""},
    {"name": "group_run_path", "default": ""},
    {"name": "requested_by", "default": ""},
]
REPAIR_JOB_PARAMETERS = [
    *JOB_PARAMETERS,
    {"name": "attempt", "default": "1"},
    {"name": "max_attempts", "default": "5"},
    {"name": "repair_job_id", "default": ""},
]
ENVIRONMENTS = [
    {
        "environment_key": "semantic",
        "spec": {
            "environment_version": "4",
            "dependencies": ["databricks-sdk>=0.102.0", "PyYAML>=6.0"],
        },
    }
]


def run_cli(profile: str, *arguments: str) -> str:
    command = ["databricks", *arguments, "--profile", profile]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "Unknown Databricks CLI error"
        raise RuntimeError(f"Databricks command failed: {' '.join(command[:3])}: {detail}")
    return result.stdout


def run_json(profile: str, *arguments: str) -> dict:
    output = run_cli(profile, *arguments, "-o", "json")
    return json.loads(output or "{}")


def notebook_task(task_key: str, notebook_path: str, parameters: dict[str, str], **extra: object) -> dict:
    return {
        "task_key": task_key,
        "notebook_task": {
            "notebook_path": notebook_path,
            "source": "WORKSPACE",
            "base_parameters": parameters,
        },
        "environment_key": "semantic",
        "run_if": "ALL_SUCCESS",
        "timeout_seconds": 0,
        **extra,
    }


def placeholder_task(task_key: str, notebook_path: str, **extra: object) -> dict:
    return notebook_task(task_key, notebook_path, {}, **extra)


def common_settings(name: str, tasks: list[dict], parameters: list[dict] | None = None) -> dict:
    return {
        "name": name,
        "edit_mode": "EDITABLE",
        "format": "MULTI_TASK",
        "max_concurrent_runs": 10,
        "timeout_seconds": 0,
        "performance_target": "PERFORMANCE_OPTIMIZED",
        "queue": {"enabled": True},
        "parameters": parameters or JOB_PARAMETERS,
        "environments": ENVIRONMENTS,
        "tags": {"aidevkit_project": "ai-dev-kit", "managed_by": "scripts/deploy.py"},
        "tasks": tasks,
    }


def existing_job(profile: str, name: str) -> dict | None:
    response = run_json(profile, "jobs", "list", "--name", name, "--expand-tasks")
    jobs = response if isinstance(response, list) else response.get("jobs", [])
    exact = [job for job in jobs if job.get("settings", {}).get("name", "").casefold() == name.casefold()]
    if len(exact) > 1:
        raise RuntimeError(f"Multiple Jobs are named {name!r}; remove duplicates before deploying.")
    return exact[0] if exact else None


def deploy_job(
    profile: str,
    name: str,
    create_tasks: list[dict],
    update_tasks: list[dict],
    existing: dict | None,
    dry_run: bool,
    fields_to_remove: list[str] | None = None,
    parameters: list[dict] | None = None,
) -> int:
    settings = common_settings(name, update_tasks if existing else create_tasks, parameters)
    if dry_run:
        print(
            json.dumps(
                {
                    "operation": "UPDATE" if existing else "CREATE",
                    "job_id": existing.get("job_id") if existing else None,
                    "new_settings": settings,
                    "fields_to_remove": fields_to_remove or [],
                },
                indent=2,
            )
        )
        return int(existing.get("job_id", 0)) if existing else 0
    if existing:
        job_id = int(existing["job_id"])
        run_cli(
            profile,
            "jobs",
            "update",
            "--json",
            json.dumps(
                {
                    "job_id": job_id,
                    "new_settings": settings,
                    "fields_to_remove": fields_to_remove or [],
                }
            ),
        )
        return job_id
    return int(run_json(profile, "jobs", "create", "--json", json.dumps(settings))["job_id"])


def workflow_bundle_outputs(profile: str, target: str) -> dict[str, str]:
    """Job IDs and output Volume of the deployed datasource semantic workflow bundle."""
    command = ["databricks", "bundle", "summary", "-t", target, "--profile", profile, "-o", "json"]
    result = subprocess.run(command, cwd=ROOT / "workflows" / "datasource-semantic-migration", capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            "Deploy the semantic workflow first (or run scripts/install.py): "
            + (result.stderr.strip() or result.stdout.strip())
        )
    summary = json.loads(result.stdout)
    jobs = summary.get("resources", {}).get("jobs", {})
    try:
        proposal = jobs["datasource_semantic_orchestrator"]["id"]
        migration = jobs["datasource_semantic_migration"]["id"]
    except KeyError as error:
        raise RuntimeError("The semantic workflow Jobs are not deployed yet; run scripts/install.py.") from error
    volume_path = summary["variables"]["output_volume_path"]["value"]
    return {
        "proposal_job_id": str(proposal),
        "migration_job_id": str(migration),
        "volume": ".".join(volume_path.removeprefix("/Volumes/").strip("/").split("/")[:3]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy BI migration Jobs, bundle resources, and Databricks App.")
    parser.add_argument("--profile", default="DEFAULT")
    parser.add_argument("--target", default="dev")
    parser.add_argument("--app-name", default="bi-migration-review")
    parser.add_argument("--component", choices=("all", "jobs", "app"), default="all")
    # Defaults come from the deployed semantic workflow bundle; pass them only to override.
    parser.add_argument("--datasource-semantic-proposal-job-id")
    parser.add_argument("--datasource-semantic-migration-job-id")
    parser.add_argument("--datasource-semantic-volume-full-name")
    parser.add_argument("--upload-volume-full-name", help="Volume for App uploads (default: saved settings)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # Workspace-specific catalog, schemas, Volumes, and warehouse come from this profile's install settings.
    settings = require_settings(args.profile)
    apply_settings(settings, args.target)
    args.upload_volume_full_name = args.upload_volume_full_name or settings["upload_volume"]
    args.datasource_semantic_volume_full_name = args.datasource_semantic_volume_full_name or settings["output_volume"]
    if not (
        args.datasource_semantic_proposal_job_id
        and args.datasource_semantic_migration_job_id
        and args.datasource_semantic_volume_full_name
    ):
        workflow = workflow_bundle_outputs(args.profile, args.target)
        args.datasource_semantic_proposal_job_id = args.datasource_semantic_proposal_job_id or workflow["proposal_job_id"]
        args.datasource_semantic_migration_job_id = (
            args.datasource_semantic_migration_job_id or workflow["migration_job_id"]
        )
        args.datasource_semantic_volume_full_name = args.datasource_semantic_volume_full_name or workflow["volume"]

    current_user = run_json(args.profile, "current-user", "me")["userName"]
    bundle_root = f"/Workspace/Users/{current_user}/.bundle/bi-migration-review/{args.target}/files"
    notebooks = f"{bundle_root}/notebooks"
    # Match the bundle's development-mode prefix so API-managed Jobs sit beside bundle Jobs.
    short_name = re.sub(r"[^A-Za-z0-9]+", "_", current_user.split("@")[0]).strip("_")
    name_prefix = f"[dev {short_name}]" if args.target == "dev" else f"[{args.target}]"
    dashboard_name = f"{name_prefix} BI migration dashboard import"
    semantic_name = f"{name_prefix} BI migration semantic build"
    repair_name = f"{name_prefix} BI migration metric view repair"
    dashboard_existing = existing_job(args.profile, dashboard_name)
    semantic_existing = existing_job(args.profile, semantic_name)
    repair_existing = existing_job(args.profile, repair_name)

    nested_import = {
        "task_key": "import_dashboard",
        "notebook_task": {
            "notebook_path": f"{notebooks}/genie_task_not_configured",
            "source": "WORKSPACE",
        },
        "environment_key": "semantic",
        "timeout_seconds": 7200,
    }
    import_dashboards = {
        "task_key": "import_dashboards",
        "depends_on": [{"task_key": "prepare_import"}],
        "for_each_task": {
            "inputs": "{{tasks.prepare_import.values.workbooks}}",
            "concurrency": 10,
            "task": nested_import,
        },
        "run_if": "ALL_SUCCESS",
        "timeout_seconds": 0,
    }
    dashboard_tasks = [
        notebook_task(
            "prepare_import",
            f"{notebooks}/freeze_group_package",
            {
                "run_id": "{{job.parameters.run_id}}",
                "group_id": "{{job.parameters.group_id}}",
                "group_run_path": "{{job.parameters.group_run_path}}",
                "requested_by": "{{job.parameters.requested_by}}",
            },
        ),
        import_dashboards,
        notebook_task(
            "reconcile_dashboards",
            f"{notebooks}/reconcile_dashboard_import",
            {
                "run_id": "{{job.parameters.run_id}}",
                "group_run_path": "{{job.parameters.group_run_path}}",
            },
            depends_on=[{"task_key": "import_dashboards"}],
            run_if="ALL_DONE",
        ),
    ]

    build_metric_view = placeholder_task(
        "build_metric_view",
        f"{notebooks}/genie_task_not_configured",
        depends_on=[{"task_key": "semantic_preflight"}],
        timeout_seconds=3600,
    )
    build_genie_agent = placeholder_task(
        "build_genie_agent",
        f"{notebooks}/genie_task_not_configured",
        depends_on=[{"task_key": "validate_metric_view"}],
        timeout_seconds=3600,
    )
    semantic_tasks = [
        notebook_task(
            "semantic_preflight",
            f"{notebooks}/semantic_preflight",
            {
                "run_id": "{{job.parameters.run_id}}",
                "group_run_path": "{{job.parameters.group_run_path}}",
            },
        ),
        build_metric_view,
        notebook_task(
            "validate_metric_view",
            f"{notebooks}/validate_metric_view",
            {
                "run_id": "{{job.parameters.run_id}}",
                "group_run_path": "{{job.parameters.group_run_path}}",
            },
            depends_on=[{"task_key": "build_metric_view"}],
        ),
        build_genie_agent,
        notebook_task(
            "audit_semantic_assets",
            f"{notebooks}/audit_semantic_workflow",
            {
                "run_id": "{{job.parameters.run_id}}",
                "group_run_path": "{{job.parameters.group_run_path}}",
            },
            depends_on=[{"task_key": "validate_metric_view"}, {"task_key": "build_genie_agent"}],
            run_if="ALL_DONE",
        ),
    ]

    repair_metric_view = placeholder_task(
        "repair_metric_view",
        f"{notebooks}/genie_task_not_configured",
        depends_on=[{"task_key": "prepare_metric_view_repair"}],
        timeout_seconds=3600,
    )
    repair_tasks = [
        notebook_task(
            "prepare_metric_view_repair",
            f"{notebooks}/prepare_metric_view_repair",
            {
                "run_id": "{{job.parameters.run_id}}",
                "group_id": "{{job.parameters.group_id}}",
                "group_run_path": "{{job.parameters.group_run_path}}",
                "attempt": "{{job.parameters.attempt}}",
                "max_attempts": "{{job.parameters.max_attempts}}",
            },
        ),
        repair_metric_view,
        notebook_task(
            "validate_repaired_metric_view",
            f"{notebooks}/validate_metric_view",
            {
                "run_id": "{{job.parameters.run_id}}",
                "group_run_path": "{{job.parameters.group_run_path}}",
                "fail_on_error": "false",
            },
            depends_on=[{"task_key": "repair_metric_view"}],
            run_if="ALL_DONE",
        ),
        notebook_task(
            "evaluate_repaired_metric_view",
            f"{notebooks}/evaluate_metric_view",
            {
                "run_id": "{{job.parameters.run_id}}",
                "group_run_path": "{{job.parameters.group_run_path}}",
                "attempt": "{{job.parameters.attempt}}",
            },
            depends_on=[{"task_key": "validate_repaired_metric_view"}],
            run_if="ALL_DONE",
        ),
        notebook_task(
            "finalize_metric_view_repair",
            f"{notebooks}/finalize_metric_view_repair",
            {
                "run_id": "{{job.parameters.run_id}}",
                "group_id": "{{job.parameters.group_id}}",
                "group_run_path": "{{job.parameters.group_run_path}}",
                "requested_by": "{{job.parameters.requested_by}}",
                "attempt": "{{job.parameters.attempt}}",
                "max_attempts": "{{job.parameters.max_attempts}}",
                "repair_job_id": "{{job.parameters.repair_job_id}}",
            },
            depends_on=[{"task_key": "evaluate_repaired_metric_view"}],
            run_if="ALL_DONE",
        ),
    ]

    if args.component in {"all", "jobs"}:
        dashboard_job_id = deploy_job(
            args.profile,
            dashboard_name,
            dashboard_tasks,
            [dashboard_tasks[0], dashboard_tasks[2]],
            dashboard_existing,
            args.dry_run,
        )
        semantic_job_id = deploy_job(
            args.profile,
            semantic_name,
            semantic_tasks,
            [semantic_tasks[0], semantic_tasks[2], semantic_tasks[4]],
            semantic_existing,
            args.dry_run,
            ["tasks/audit_semantic_assets/depends_on"],
        )
        repair_job_id = deploy_job(
            args.profile,
            repair_name,
            repair_tasks,
            [repair_tasks[0], repair_tasks[2], repair_tasks[3], repair_tasks[4]],
            repair_existing,
            args.dry_run,
            parameters=REPAIR_JOB_PARAMETERS,
        )
        if not args.dry_run:
            repair_parameters = [
                parameter | ({"default": str(repair_job_id)} if parameter["name"] == "repair_job_id" else {})
                for parameter in REPAIR_JOB_PARAMETERS
            ]
            run_cli(
                args.profile,
                "jobs",
                "update",
                "--json",
                json.dumps({"job_id": repair_job_id, "new_settings": {"parameters": repair_parameters}}),
            )
    else:
        if not dashboard_existing or not semantic_existing or not repair_existing:
            raise RuntimeError("Deploy the Jobs before deploying the App in a new workspace.")
        dashboard_job_id = int(dashboard_existing["job_id"])
        semantic_job_id = int(semantic_existing["job_id"])
        repair_job_id = int(repair_existing["job_id"])
    if args.dry_run:
        if args.component == "app":
            print(
                json.dumps(
                    {
                        "operation": "DEPLOY_APP",
                        "app_name": args.app_name,
                        "dashboard_import_job_id": dashboard_job_id,
                        "semantic_build_job_id": semantic_job_id,
                        "metric_view_repair_job_id": repair_job_id,
                        "datasource_semantic_proposal_job_id": int(args.datasource_semantic_proposal_job_id),
                        "datasource_semantic_migration_job_id": int(args.datasource_semantic_migration_job_id),
                        "datasource_semantic_volume_full_name": args.datasource_semantic_volume_full_name,
                    },
                    indent=2,
                )
            )
        return

    deployed = {
        "dashboard_import_job_id": dashboard_job_id,
        "semantic_build_job_id": semantic_job_id,
        "metric_view_repair_job_id": repair_job_id,
        "datasource_semantic_proposal_job_id": int(args.datasource_semantic_proposal_job_id),
        "datasource_semantic_migration_job_id": int(args.datasource_semantic_migration_job_id),
        "datasource_semantic_volume_full_name": args.datasource_semantic_volume_full_name,
    }
    if args.component == "jobs":
        print(json.dumps(deployed, indent=2))
        return

    # Remember the Job IDs too, so plain `databricks bundle` commands resolve every variable.
    from install_settings import write_overrides

    write_overrides(
        ROOT,
        args.target,
        {
            "dashboard_import_job_id": str(dashboard_job_id),
            "semantic_build_job_id": str(semantic_job_id),
            "metric_view_repair_job_id": str(repair_job_id),
            "datasource_semantic_proposal_job_id": str(args.datasource_semantic_proposal_job_id),
            "datasource_semantic_migration_job_id": str(args.datasource_semantic_migration_job_id),
        },
    )
    run_cli(
        args.profile,
        "bundle",
        "deploy",
        "-t",
        args.target,
        "--var",
        f"dashboard_import_job_id={dashboard_job_id}",
        "--var",
        f"semantic_build_job_id={semantic_job_id}",
        "--var",
        f"metric_view_repair_job_id={repair_job_id}",
        "--var",
        f"datasource_semantic_proposal_job_id={args.datasource_semantic_proposal_job_id}",
        "--var",
        f"datasource_semantic_migration_job_id={args.datasource_semantic_migration_job_id}",
        "--var",
        f"datasource_semantic_volume_full_name={args.datasource_semantic_volume_full_name}",
        *(["--var", f"volume_full_name={args.upload_volume_full_name}"] if args.upload_volume_full_name else []),
    )
    run_cli(
        args.profile,
        "apps",
        "deploy",
        args.app_name,
        "--source-code-path",
        f"{bundle_root}/app/bi-migration-review",
    )
    print(json.dumps(deployed, indent=2))


if __name__ == "__main__":
    main()
