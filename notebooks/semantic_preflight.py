# Databricks notebook source
import json
from pathlib import Path

import yaml


for name in ("run_id", "group_run_path"):
    dbutils.widgets.text(name, "")
run_id = dbutils.widgets.get("run_id").strip()
group_run_path = Path(dbutils.widgets.get("group_run_path").rstrip("/"))
manifest = json.loads((group_run_path / "group-migration-manifest.json").read_text(encoding="utf-8"))
dashboard_summary_path = Path(manifest["dashboard_manifest_path"])
dashboard_config_directory = Path(manifest["dashboard_config_directory"])
dashboard_config_paths = [Path(workbook["output_path"]) / "dashboard-config.json" for workbook in manifest["workbooks"]]
mapping_path = Path(manifest["approved_mapping_path"])
kpi_path = Path(manifest["kpi_inventory_path"])

errors = []
for required in (
    dashboard_summary_path,
    mapping_path,
    kpi_path,
    Path(manifest["prompts"]["metric_view"]["path"]),
    Path(manifest["prompts"]["genie_agent"]["path"]),
):
    if not required.exists():
        errors.append(f"Missing required input: {required}")
for dashboard_config_path in dashboard_config_paths:
    if not dashboard_config_path.exists():
        errors.append(f"Missing dashboard configuration: {dashboard_config_path}")
mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {}
unresolved = [item for item in mapping.get("relationships", []) if item.get("status") not in {"approved", "proposed"}]
if unresolved:
    errors.append(f"{len(unresolved)} unresolved relationships remain")
dashboard_summary = json.loads(dashboard_summary_path.read_text(encoding="utf-8")) if dashboard_summary_path.exists() else {}
if dashboard_summary.get("status") != "SUCCESS":
    errors.append(f"Dashboard reconciliation status is {dashboard_summary.get('status', 'MISSING')}, not SUCCESS")
expected_workbooks = len(manifest.get("workbooks", []))
validated_dashboards = int(dashboard_summary.get("validated_dashboards", 0))
if validated_dashboards != expected_workbooks:
    errors.append(f"Dashboard reconciliation validated {validated_dashboards}/{expected_workbooks} workbooks")

report = {
    "run_id": run_id,
    "status": "FAIL" if errors else "PASS",
    "dashboard_count": validated_dashboards,
    "dashboard_summary_path": str(dashboard_summary_path),
    "dashboard_config_directory": str(dashboard_config_directory),
    "mapping_path": str(mapping_path),
    "kpi_inventory_path": str(kpi_path),
    "candidate_metric_view_fqn": manifest.get("candidate_metric_view_fqn"),
    "errors": errors,
}
semantic_dir = group_run_path / "semantic"
semantic_dir.mkdir(parents=True, exist_ok=True)
(semantic_dir / "semantic-preflight.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
if errors:
    raise RuntimeError("Semantic preflight failed: " + "; ".join(errors))
dbutils.notebook.exit(json.dumps(report))
