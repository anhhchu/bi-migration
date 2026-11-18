# Databricks notebook source
import json
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient


for name in ("run_id", "group_run_path"):
    dbutils.widgets.text(name, "")
run_id = dbutils.widgets.get("run_id").strip()
group_run_path = Path(dbutils.widgets.get("group_run_path").rstrip("/"))
manifest = json.loads((group_run_path / "group-migration-manifest.json").read_text(encoding="utf-8"))
metric_view_fqn = manifest["candidate_metric_view_fqn"]
semantic_dir = group_run_path / "semantic"
errors = []
definition = {}
w = WorkspaceClient()

try:
    table = w.tables.get(metric_view_fqn)
    table_type = table.table_type.value if table.table_type else ""
    if table_type != "METRIC_VIEW":
        errors.append(f"{metric_view_fqn} is {table_type}, not METRIC_VIEW")
    text = table.view_definition or ""
    if "$$" in text:
        text = text.split("$$", 2)[1]
    definition = yaml.safe_load(text) or {}
except Exception as error:
    errors.append(f"Could not inspect Metric View: {error}")

measures = [item for item in definition.get("measures", []) if isinstance(item, dict)]
dimensions = [item for item in definition.get("dimensions", []) if isinstance(item, dict)]
if not measures:
    errors.append("Metric View defines no measures")
smoke_tests = []
quoted_view = ".".join(f"`{part}`" for part in metric_view_fqn.split("."))
for measure in measures:
    name = measure.get("name")
    try:
        spark.sql(f"SELECT MEASURE(`{name}`) FROM {quoted_view}").limit(1).collect()
        smoke_tests.append({"measure": name, "status": "PASS"})
    except Exception as error:
        smoke_tests.append({"measure": name, "status": "FAIL", "error": str(error)[:500]})
        errors.append(f"Measure failed: {name}")

report = {
    "run_id": run_id,
    "status": "FAIL" if errors else "PASS",
    "metric_view_fqn": metric_view_fqn,
    "dimension_count": len(dimensions),
    "measure_count": len(measures),
    "dimensions": [{"name": item.get("name"), "display_name": item.get("display_name")} for item in dimensions],
    "measures": [{"name": item.get("name"), "display_name": item.get("display_name")} for item in measures],
    "smoke_tests": smoke_tests,
    "errors": errors,
}
(semantic_dir / "metric-view-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
if errors:
    raise RuntimeError("Metric View validation failed: " + "; ".join(errors))
dbutils.notebook.exit(json.dumps(report))
