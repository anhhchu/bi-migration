# Databricks notebook source
import json
from pathlib import Path

from databricks.sdk import WorkspaceClient


for name in (
    "run_id",
    "group_id",
    "group_run_path",
    "requested_by",
    "attempt",
    "max_attempts",
    "repair_job_id",
):
    dbutils.widgets.text(name, "")

run_id = dbutils.widgets.get("run_id").strip()
group_id = dbutils.widgets.get("group_id").strip()
group_run_path = Path(dbutils.widgets.get("group_run_path").rstrip("/"))
requested_by = dbutils.widgets.get("requested_by").strip()
attempt = int(dbutils.widgets.get("attempt") or "1")
max_attempts = int(dbutils.widgets.get("max_attempts") or "5")
repair_job_id = int(dbutils.widgets.get("repair_job_id") or "0")
semantic_dir = group_run_path / "semantic"
repair_dir = semantic_dir / "repair" / f"attempt-{attempt:02d}"
validation = json.loads((semantic_dir / "metric-view-validation.json").read_text(encoding="utf-8"))
evaluation_path = semantic_dir / "evaluation" / "evaluation-summary.json"
evaluation = json.loads(evaluation_path.read_text(encoding="utf-8")) if evaluation_path.exists() else {}
blocking_findings = evaluation.get("blocking_findings") or validation.get("errors") or []
state = json.loads((repair_dir / "state.json").read_text(encoding="utf-8"))
repair_result_path = repair_dir / "repair-result.json"
repair_result = json.loads(repair_result_path.read_text(encoding="utf-8")) if repair_result_path.exists() else {}
if state.get("status") == "READY" and not repair_result:
    blocking_findings = [
        *blocking_findings,
        {"type": "REPAIR_RESULT_MISSING", "detail": f"Missing {repair_result_path}"},
    ]
if repair_result.get("status") == "UNRESOLVABLE":
    blocking_findings = [
        *blocking_findings,
        {"type": "AUTOMATIC_REPAIR_UNRESOLVABLE", "detail": repair_result.get("detail", "")},
    ]
passed = validation.get("status") == "PASS" and not blocking_findings
unresolvable = repair_result.get("status") == "UNRESOLVABLE"
previous_summary_path = semantic_dir / "repair" / f"attempt-{attempt - 1:02d}" / "summary.json"
previous_summary = (
    json.loads(previous_summary_path.read_text(encoding="utf-8"))
    if attempt > 1 and previous_summary_path.exists()
    else {}
)
no_progress = bool(
    blocking_findings
    and evaluation.get("failure_signature")
    and evaluation.get("failure_signature") == previous_summary.get("failure_signature")
)

summary = {
    "run_id": run_id,
    "group_id": group_id,
    "attempt": attempt,
    "max_attempts": max_attempts,
    "status": "EVALUATION_PASSED" if passed else "RETRY_REQUIRED",
    "validation_status": validation.get("status"),
    "blocking_findings": blocking_findings,
    "failure_signature": evaluation.get("failure_signature"),
    "no_progress": no_progress,
    "next_run_id": None,
}

if not passed and attempt < max_attempts and not no_progress and not unresolvable:
    if not repair_job_id:
        raise RuntimeError("repair_job_id is required for automatic retry")
    response = WorkspaceClient().jobs.run_now(
        job_id=repair_job_id,
        job_parameters={
            "run_id": run_id,
            "group_id": group_id,
            "group_run_path": str(group_run_path),
            "requested_by": requested_by,
            "attempt": str(attempt + 1),
            "max_attempts": str(max_attempts),
            "repair_job_id": str(repair_job_id),
        },
    )
    summary["next_run_id"] = response.response.run_id if response.response else None
elif not passed:
    if unresolvable:
        summary["status"] = "AUTOMATIC_REPAIR_UNRESOLVABLE"
    else:
        summary["status"] = "AUTOMATIC_REPAIR_NO_PROGRESS" if no_progress else "AUTOMATIC_REPAIR_EXHAUSTED"

(repair_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
(semantic_dir / "repair" / "latest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("\n=== Metric View Repair Finalization ===")
print(f"Status: {summary['status']}")
print(f"Attempt: {attempt}/{max_attempts}")
print(f"Validation: {summary['validation_status']}")
print(f"Blocking findings: {len(blocking_findings)}")
for finding in blocking_findings:
    print(f"- {finding.get('id') or finding.get('type') or 'finding'}: {finding.get('detail') or finding}")
print(f"No progress detected: {'yes' if no_progress else 'no'}")
print(f"Next repair run: {summary['next_run_id'] or 'none'}")
print(f"Attempt summary: {repair_dir / 'summary.json'}")
print(f"Latest summary: {semantic_dir / 'repair' / 'latest.json'}")
dbutils.notebook.exit(json.dumps(summary))
