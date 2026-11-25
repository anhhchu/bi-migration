# Databricks notebook source
import json
from pathlib import Path


for name in ("run_id", "group_id", "group_run_path", "attempt", "max_attempts"):
    dbutils.widgets.text(name, "")

run_id = dbutils.widgets.get("run_id").strip()
group_id = dbutils.widgets.get("group_id").strip()
group_run_path = Path(dbutils.widgets.get("group_run_path").rstrip("/"))
attempt = int(dbutils.widgets.get("attempt") or "1")
max_attempts = int(dbutils.widgets.get("max_attempts") or "5")
semantic_dir = group_run_path / "semantic"
repair_dir = semantic_dir / "repair" / f"attempt-{attempt:02d}"
repair_dir.mkdir(parents=True, exist_ok=True)

manifest = json.loads((group_run_path / "group-migration-manifest.json").read_text(encoding="utf-8"))
validation_path = semantic_dir / "metric-view-validation.json"
evaluation_path = semantic_dir / "evaluation" / "evaluation-summary.json"
exceptions_path = semantic_dir / "metric-view-exceptions.json"

validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else {}
evaluation = json.loads(evaluation_path.read_text(encoding="utf-8")) if evaluation_path.exists() else {}
exceptions = json.loads(exceptions_path.read_text(encoding="utf-8")) if exceptions_path.exists() else {}
blocking_findings = evaluation.get("blocking_findings") or validation.get("errors") or exceptions.get("exceptions") or []
already_passed = validation.get("status") == "PASS" and not blocking_findings

prompt = "\n".join(
    [
        "# Genie Code — Automatically repair candidate Metric View",
        "",
        f"Run ID: `{run_id}`",
        f"Semantic group: `{group_id}`",
        f"Repair attempt: `{attempt}` of `{max_attempts}`",
        f"Candidate Metric View: `{manifest['candidate_metric_view_fqn']}`",
        f"Approved mapping: `{manifest['approved_mapping_path']}`",
        f"Validation evidence: `{validation_path}`",
        f"Evaluation evidence: `{evaluation_path}`",
        f"Existing exceptions: `{exceptions_path}`",
        "",
        "If the latest deterministic evaluation has no blocking findings, make no changes and record NOOP.",
        "Otherwise update the existing candidate Metric View in place. Do not create another Metric View,",
        "change approved business definitions, modify promoted assets, or rerun `/importBI`.",
        "Apply only repairs supported by the deterministic evidence. Preserve previously passing metrics.",
        "Write repair-result.json in this attempt directory with changed definitions, remaining findings,",
        "and status APPLIED, NOOP, or UNRESOLVABLE. The deterministic tasks decide whether the repair passed.",
        "",
        "Blocking findings:",
        json.dumps(blocking_findings, indent=2),
    ]
)
(repair_dir / "repair-prompt.md").write_text(prompt, encoding="utf-8")
state = {
    "run_id": run_id,
    "group_id": group_id,
    "attempt": attempt,
    "max_attempts": max_attempts,
    "status": "NOOP" if already_passed else "READY",
    "candidate_metric_view_fqn": manifest["candidate_metric_view_fqn"],
    "prompt_path": str(repair_dir / "repair-prompt.md"),
    "repair_result_path": str(repair_dir / "repair-result.json"),
    "blocking_findings": blocking_findings,
}
(repair_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
print("\n=== Metric View Repair Preparation ===")
print(f"Status: {state['status']}")
print(f"Attempt: {attempt}/{max_attempts}")
print(f"Metric View: {state['candidate_metric_view_fqn']}")
print(f"Blocking findings: {len(blocking_findings)}")
for finding in blocking_findings:
    if isinstance(finding, dict):
        print(f"- {finding.get('id') or finding.get('type') or 'finding'}: {finding.get('detail') or finding}")
    else:
        print(f"- {finding}")
print(f"Generated prompt: {state['prompt_path']}")
dbutils.jobs.taskValues.set(key="repair_prompt_path", value=state["prompt_path"])
dbutils.jobs.taskValues.set(key="repair_attempt_dir", value=str(repair_dir))
dbutils.notebook.exit(json.dumps(state))
