# Databricks notebook source
import hashlib
import json
from pathlib import Path


for name in ("run_id", "group_id", "group_run_path", "requested_by"):
    dbutils.widgets.text(name, "")

run_id = dbutils.widgets.get("run_id").strip()
group_id = dbutils.widgets.get("group_id").strip()
group_run_path = dbutils.widgets.get("group_run_path").rstrip("/")
requested_by = dbutils.widgets.get("requested_by").strip()
if not all((run_id, group_id, group_run_path)):
    raise ValueError("run_id, group_id, and group_run_path are required")

manifest_path = Path(group_run_path) / "group-migration-manifest.json"
if not manifest_path.exists():
    raise FileNotFoundError(f"Group migration manifest not found: {manifest_path}")

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
for key in ("approved_mapping_path", "workbook_paths", "prompts"):
    if not manifest.get(key):
        raise ValueError(f"Manifest is missing {key}")
for workbook_path in manifest["workbook_paths"]:
    if not Path(workbook_path).exists():
        raise FileNotFoundError(f"Workbook not found: {workbook_path}")
for prompt in manifest["prompts"].values():
    prompt_path = Path(prompt["path"])
    text = prompt_path.read_text(encoding="utf-8")
    if hashlib.sha256(text.encode()).hexdigest() != prompt["sha256"]:
        raise ValueError(f"Prompt hash mismatch: {prompt_path}")

runtime_manifest = {
    **manifest,
    "workflow_run_id": run_id,
    "requested_by": requested_by,
    "status": "FROZEN",
}
(Path(group_run_path) / "workflow-run-manifest.json").write_text(
    json.dumps(runtime_manifest, indent=2), encoding="utf-8"
)
workbooks = []
for workbook in manifest.get("workbooks", []):
    dashboard_tag = f"[bi-migration:{run_id}:{Path(group_run_path).name}:{workbook['workbook_id']}]"
    workbooks.append({
        **workbook,
        "approved_mapping_path": manifest["approved_mapping_path"],
        "dashboard_tag": dashboard_tag,
        "migration_run_id": run_id,
        "semantic_group": group_id,
    })
if not workbooks:
    raise ValueError("Manifest contains no workbook fan-out items")
dbutils.jobs.taskValues.set(key="workbooks", value=workbooks)
dbutils.notebook.exit(json.dumps({"status": "SUCCESS", "run_id": run_id, "workbook_count": len(workbooks)}))
