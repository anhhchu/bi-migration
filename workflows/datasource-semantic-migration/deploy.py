#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
AUTOMATION_ENDPOINT = "/api/2.0/alerts-internal/scheduled-insights"
AUTOMATIONS = {
    "semantic_grouping": "group_semantic_datasources.md",
    "import_metric_view": "import_metric_view.md",
    "repair_metric_view": "repair_metric_view.md",
}


def run_cli(arguments: list[str], *, profile: str, target: str | None = None) -> Any:
    command = ["databricks", *arguments, "--profile", profile]
    if target:
        command.extend(["--target", target])
    completed = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    output = completed.stdout.strip()
    return json.loads(output) if output else None


def resource_id(summary: dict[str, Any], resource_key: str) -> int:
    resources = summary.get("resources", {}).get("jobs", {})
    entry = resources.get(resource_key, {})
    for key in ("id", "job_id"):
        if entry.get(key):
            return int(entry[key])
    state_path = ROOT / ".databricks" / "bundle" / summary.get("target", "dev") / "resources.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))["state"]
        key = f"resources.jobs.{resource_key}"
        if key in state:
            return int(state[key]["__id__"])
    raise RuntimeError(f"Could not resolve deployed Job ID for {resource_key}")


def create_automation(*, profile: str, prompt: str, user_id: str) -> str:
    body = {
        "parent_asset_name": f"users/{user_id}",
        "scheduled_insight": {"insight_type": "GENIE_CODE", "user_prompt": prompt},
    }
    response = run_cli(
        ["api", "post", AUTOMATION_ENDPOINT, "--json", json.dumps(body), "--output", "json"],
        profile=profile,
    )
    return str(response["name"])


def automation_id(*, profile: str, target: str, automation_name: str, recreate: bool) -> str:
    state_path = ROOT / ".databricks" / f"genie-code-{target}.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    if state.get("configuration_id") and "import_metric_view" not in state:
        state["import_metric_view"] = state.pop("configuration_id")
    if state.get(automation_name) and not recreate:
        return str(state[automation_name])
    current_user = run_cli(["current-user", "me", "--output", "json"], profile=profile)
    prompt = (ROOT / "prompts" / AUTOMATIONS[automation_name]).read_text(encoding="utf-8")
    configuration_id = create_automation(profile=profile, prompt=prompt, user_id=str(current_user["id"]))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state[automation_name] = configuration_id
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return configuration_id


def configure_genie_task(
    *,
    profile: str,
    job_id: int,
    task_key: str,
    configuration_id: str,
    parameters: dict[str, str],
) -> None:
    job = run_cli(["jobs", "get", str(job_id), "--output", "json"], profile=profile)
    settings = job["settings"]
    tasks = settings.get("tasks", [])
    matching_tasks = [task for task in tasks if task.get("task_key") == task_key]
    if len(matching_tasks) != 1:
        raise RuntimeError(f"Expected exactly one {task_key} task, found {len(matching_tasks)}")
    task = matching_tasks[0]
    task.pop("notebook_task", None)
    task.pop("environment_key", None)
    task["genie_task"] = {
        "configuration_id": configuration_id,
        "parameters": parameters,
    }
    for read_only_key in ("deployment", "edit_mode", "format"):
        settings.pop(read_only_key, None)
    payload = {"job_id": job_id, "new_settings": settings}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.flush()
        run_cli(
            ["api", "post", "/api/2.1/jobs/reset", "--json", f"@{handle.name}", "--output", "json"],
            profile=profile,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy the datasource semantic migration workflow")
    parser.add_argument("--profile", default="DEFAULT")
    parser.add_argument("--target", default="dev")
    parser.add_argument("--recreate-automation", action="store_true")
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    run_cli(["bundle", "validate", "--strict", "--output", "json"], profile=arguments.profile, target=arguments.target)
    run_cli(["bundle", "deploy", "--output", "json"], profile=arguments.profile, target=arguments.target)
    summary = run_cli(["bundle", "summary", "--output", "json"], profile=arguments.profile, target=arguments.target)
    summary["target"] = arguments.target
    proposal_job_id = resource_id(summary, "datasource_semantic_orchestrator")
    migration_job_id = resource_id(summary, "datasource_semantic_migration")
    child_job_id = resource_id(summary, "datasource_semantic_group")
    repair_job_id = resource_id(summary, "datasource_semantic_repair")
    grouping_configuration_id = automation_id(
        profile=arguments.profile,
        target=arguments.target,
        automation_name="semantic_grouping",
        recreate=arguments.recreate_automation,
    )
    configure_genie_task(
        profile=arguments.profile,
        job_id=proposal_job_id,
        task_key="propose_semantic_groups",
        configuration_id=grouping_configuration_id,
        parameters={
            "grouping_request_path": "{{tasks.prepare_semantic_grouping.values.grouping_request_path}}",
            "grouping_result_path": "{{tasks.prepare_semantic_grouping.values.grouping_result_path}}",
        },
    )
    import_configuration_id = automation_id(
        profile=arguments.profile,
        target=arguments.target,
        automation_name="import_metric_view",
        recreate=arguments.recreate_automation,
    )
    configure_genie_task(
        profile=arguments.profile,
        job_id=child_job_id,
        task_key="create_candidate_metric_view",
        configuration_id=import_configuration_id,
        parameters={
            "group_manifest_path": "{{tasks.prepare_candidate_context.values.group_manifest_path}}",
            "mapping_path": "{{tasks.prepare_candidate_context.values.mapping_path}}",
            "target_profile_path": "{{tasks.prepare_candidate_context.values.target_profile_path}}",
            "metric_view_fqn": "{{tasks.prepare_candidate_context.values.metric_view_fqn}}",
            "importbi_result_path": "{{tasks.prepare_candidate_context.values.importbi_result_path}}",
            "warehouse_id": "{{job.parameters.warehouse_id}}",
        },
    )
    repair_configuration_id = automation_id(
        profile=arguments.profile,
        target=arguments.target,
        automation_name="repair_metric_view",
        recreate=arguments.recreate_automation,
    )
    configure_genie_task(
        profile=arguments.profile,
        job_id=repair_job_id,
        task_key="genie_semantic_patch",
        configuration_id=repair_configuration_id,
        parameters={
            "genie_request_path": "{{tasks.build_deterministic_patches.values.genie_request_path}}",
            "genie_patch_path": "{{tasks.build_deterministic_patches.values.genie_patch_path}}",
            "genie_candidate_path": "{{tasks.build_deterministic_patches.values.genie_candidate_path}}",
        },
    )
    print(
        json.dumps(
            {
                "status": "DEPLOYED",
                "proposal_job_id": proposal_job_id,
                "migration_job_id": migration_job_id,
                "child_job_id": child_job_id,
                "repair_job_id": repair_job_id,
                "grouping_genie_configuration_id": grouping_configuration_id,
                "import_genie_configuration_id": import_configuration_id,
                "repair_genie_configuration_id": repair_configuration_id,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
