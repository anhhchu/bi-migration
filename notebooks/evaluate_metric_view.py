# Databricks notebook source
import hashlib
import json
from pathlib import Path


for name in ("run_id", "group_run_path", "attempt"):
    dbutils.widgets.text(name, "")

run_id = dbutils.widgets.get("run_id").strip()
group_run_path = Path(dbutils.widgets.get("group_run_path").rstrip("/"))
attempt = int(dbutils.widgets.get("attempt") or "0")
semantic_dir = group_run_path / "semantic"
evaluation_dir = semantic_dir / "evaluation"
evaluation_dir.mkdir(parents=True, exist_ok=True)

validation = json.loads((semantic_dir / "metric-view-validation.json").read_text(encoding="utf-8"))
exceptions_path = semantic_dir / "metric-view-exceptions.json"
exceptions_document = json.loads(exceptions_path.read_text(encoding="utf-8")) if exceptions_path.exists() else {}
exceptions = exceptions_document.get("exceptions", []) if isinstance(exceptions_document, dict) else []

blocking_findings = [
    {"type": "STRUCTURAL_VALIDATION", "detail": error}
    for error in validation.get("errors", [])
]
for item in exceptions:
    if not isinstance(item, dict):
        continue
    severity = str(item.get("severity", "medium")).lower()
    disposition = str(item.get("disposition") or item.get("status") or "unresolved").lower()
    if severity in {"critical", "high"} and disposition not in {
        "resolved",
        "accepted",
        "not_applicable",
        "excluded_unsupported",
    }:
        blocking_findings.append(item)

signature_payload = json.dumps(blocking_findings, sort_keys=True, separators=(",", ":"))
summary = {
    "run_id": run_id,
    "attempt": attempt,
    "status": "PASS" if not blocking_findings else "FAIL",
    "metric_view_fqn": validation.get("metric_view_fqn"),
    "structural_validation_status": validation.get("status"),
    "blocking_findings": blocking_findings,
    "warning_findings": [
        item for item in exceptions
        if isinstance(item, dict) and item not in blocking_findings
    ],
    "failure_signature": hashlib.sha256(signature_payload.encode("utf-8")).hexdigest(),
    "evaluation_scope": "structural validation plus declared Metric View exceptions",
}
(evaluation_dir / "evaluation-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
if attempt:
    attempt_dir = semantic_dir / "repair" / f"attempt-{attempt:02d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "evaluation-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("\n=== Metric View Evaluation ===")
print(f"Status: {summary['status']}")
print(f"Metric View: {summary['metric_view_fqn']}")
print(f"Scope: {summary['evaluation_scope']}")
print(f"Blocking findings: {len(blocking_findings)}")
for finding in blocking_findings:
    print(f"- {finding.get('id') or finding.get('type') or 'finding'}: {finding.get('detail') or finding}")
print(f"Warnings: {len(summary['warning_findings'])}")
print(f"Failure signature: {summary['failure_signature']}")
print(f"Artifact: {evaluation_dir / 'evaluation-summary.json'}")
dbutils.notebook.exit(json.dumps(summary))
