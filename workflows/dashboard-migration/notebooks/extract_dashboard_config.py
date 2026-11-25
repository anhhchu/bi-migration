# Databricks notebook source
import json
from datetime import datetime, timezone
from pathlib import Path

from databricks.sdk import WorkspaceClient


for name in ("run_id", "group_run_path"):
    dbutils.widgets.text(name, "")
run_id = dbutils.widgets.get("run_id").strip()
group_run_path = Path(dbutils.widgets.get("group_run_path").rstrip("/"))
result_path = group_run_path / "session-1" / "importbi-result.json"
if not result_path.exists():
    raise FileNotFoundError(f"Session 1 result not found: {result_path}")

result = json.loads(result_path.read_text(encoding="utf-8"))
dashboards = result.get("dashboards") or [
    {"dashboard_id": dashboard_id} for dashboard_id in result.get("dashboard_ids", [])
]
if not dashboards:
    raise ValueError("Session 1 created no dashboards")

w = WorkspaceClient()
config_directory = group_run_path / "session-1" / "dashboard-configs"
config_directory.mkdir(parents=True, exist_ok=True)
normalized = []
for dashboard in dashboards:
    dashboard_id = dashboard.get("dashboard_id") or dashboard.get("id")
    if not dashboard_id:
        raise ValueError(f"Dashboard entry has no ID: {dashboard}")
    payload = w.api_client.do("GET", f"/api/2.0/lakeview/dashboards/{dashboard_id}")
    serialized = payload.get("serialized_dashboard") or "{}"
    raw_path = config_directory / f"{dashboard_id}.serialized.json"
    raw_path.write_text(serialized, encoding="utf-8")
    definition = json.loads(serialized)
    normalized.append({
        "dashboard_id": dashboard_id,
        "display_name": payload.get("display_name") or dashboard.get("display_name"),
        "raw_config_path": str(raw_path),
        "datasets": definition.get("datasets", []),
        "pages": definition.get("pages", []),
        "parameters": definition.get("parameters", []),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    })

output = {"run_id": run_id, "dashboards": normalized}
(group_run_path / "session-1" / "dashboard-config.json").write_text(
    json.dumps(output, indent=2), encoding="utf-8"
)
dbutils.notebook.exit(json.dumps({"status": "SUCCESS", "dashboard_count": len(normalized)}))
