# Databricks notebook source
import json
from pathlib import Path

import yaml


for name in ("run_id", "group_run_path"):
    dbutils.widgets.text(name, "")
run_id = dbutils.widgets.get("run_id").strip()
group_run_path = Path(dbutils.widgets.get("group_run_path").rstrip("/"))
manifest = json.loads((group_run_path / "group-migration-manifest.json").read_text(encoding="utf-8"))
dashboard_config_path = group_run_path / "session-1" / "dashboard-config.json"
mapping_path = Path(manifest["approved_mapping_path"])
kpi_path = Path(manifest["kpi_inventory_path"])

errors = []
for required in (
    dashboard_config_path,
    mapping_path,
    kpi_path,
    Path(manifest["prompts"]["metric_view"]["path"]),
    Path(manifest["prompts"]["genie_agent"]["path"]),
):
    if not required.exists():
        errors.append(f"Missing required input: {required}")
mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {}
unresolved = [item for item in mapping.get("relationships", []) if item.get("status") not in {"approved", "proposed"}]
if unresolved:
    errors.append(f"{len(unresolved)} unresolved relationships remain")
dashboard_config = json.loads(dashboard_config_path.read_text(encoding="utf-8")) if dashboard_config_path.exists() else {}
if not dashboard_config.get("dashboards"):
    errors.append("Dashboard configuration contains no dashboards")

report = {
    "run_id": run_id,
    "status": "FAIL" if errors else "PASS",
    "dashboard_count": len(dashboard_config.get("dashboards", [])),
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
