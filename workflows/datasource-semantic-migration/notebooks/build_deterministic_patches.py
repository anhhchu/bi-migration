# Databricks notebook source
import json
from pathlib import Path

import yaml

from datasource_semantic_migration.metric_repair import apply_metric_patch, build_deterministic_patch, document_hash
from datasource_semantic_migration.notebook_results import format_notebook_result, render_volume_links_html
from datasource_semantic_migration.artifacts import write_json_artifact


dbutils.widgets.text("attempt_dir", "")
attempt_dir = Path(dbutils.widgets.get("attempt_dir"))
evaluation = json.loads((attempt_dir / "evaluation-summary.json").read_text(encoding="utf-8"))
candidate = yaml.safe_load((attempt_dir / "candidate-before.yaml").read_text(encoding="utf-8")) or {}
patch = build_deterministic_patch(evaluation, candidate)
patched_candidate = apply_metric_patch(candidate, patch)
write_json_artifact(patch, attempt_dir / "deterministic-patch.json")
(attempt_dir / "candidate-deterministic.yaml").write_text(
    yaml.safe_dump(patched_candidate, sort_keys=False, width=120), encoding="utf-8"
)
genie_request = {
    "schema_version": "1.0",
    "metric_view_fqn": evaluation["metric_view_fqn"],
    "candidate_before_path": str(attempt_dir / "candidate-before.yaml"),
    "deterministic_candidate_path": str(attempt_dir / "candidate-deterministic.yaml"),
    "scorecards_path": str(attempt_dir / "metric-scorecards.json"),
    "evaluation_path": str(attempt_dir / "evaluation-summary.json"),
    "genie_patch_path": str(attempt_dir / "genie-patch.json"),
    "genie_candidate_path": str(attempt_dir / "candidate-genie.yaml"),
    "findings": [
        item for item in evaluation["blocking_findings"] if item.get("repair_route") == "GENIE_PATCH"
    ],
    # Why each finding was sent to Genie instead of the deterministic patch.
    "decision": evaluation.get("genie_decision"),
}
write_json_artifact(genie_request, attempt_dir / "genie-request.json")
changed = document_hash(candidate) != document_hash(patched_candidate)
for key, value in {
    "repair_series_id": evaluation["repair_series_id"],
    "needs_genie": "true" if evaluation["needs_genie"] else "false",
    "genie_reason": (evaluation.get("genie_decision") or {}).get("summary", ""),
    "genie_request_path": str(attempt_dir / "genie-request.json"),
    "genie_patch_path": str(attempt_dir / "genie-patch.json"),
    "genie_candidate_path": str(attempt_dir / "candidate-genie.yaml"),
}.items():
    dbutils.jobs.taskValues.set(key=key, value=value)
decision = evaluation.get("genie_decision") or {}
result = {
    "readiness": evaluation["readiness"],
    "operation_count": len(patch["operations"]),
    "candidate_changed": changed,
    "needs_genie": evaluation["needs_genie"],
    "genie_decision": decision.get("summary"),
    "sent_to_genie": [f"{item['measure']}: {item['why']}" for item in decision.get("genie_items", [])],
    "fixed_by_code": [f"{item['measure']}: {item['why']}" for item in decision.get("deterministic_items", [])],
    "patch_path": str(attempt_dir / "deterministic-patch.json"),
}
print("\n=== Build Deterministic Patches ===")
print(format_notebook_result(result))
displayHTML(render_volume_links_html(result))
dbutils.notebook.exit(format_notebook_result(result))
