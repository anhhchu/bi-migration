# Databricks notebook source
import json
from pathlib import Path


for name in ("run_id", "group_run_path"):
    dbutils.widgets.text(name, "")
run_id = dbutils.widgets.get("run_id").strip()
group_run_path = Path(dbutils.widgets.get("group_run_path").rstrip("/"))
session_dir = group_run_path / "session-1"
required = [session_dir / "importbi-result.json", session_dir / "dashboard-config.json"]
missing = [str(path) for path in required if not path.exists()]
dashboard_count = 0
if not missing:
    dashboard_count = len(json.loads(required[1].read_text(encoding="utf-8")).get("dashboards", []))
summary = {
    "run_id": run_id,
    "status": "COMPLETE" if not missing and dashboard_count else "INCOMPLETE",
    "dashboard_count": dashboard_count,
    "artifacts": [str(path) for path in required if path.exists()],
    "missing": missing,
}
(session_dir / "dashboard-import-audit.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
if summary["status"] != "COMPLETE":
    raise RuntimeError("Dashboard import incomplete: " + "; ".join(missing or ["no dashboards created"]))
dbutils.notebook.exit(json.dumps(summary))
