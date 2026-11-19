# Databricks notebook source
import json
from datetime import datetime, timezone
from pathlib import Path

from databricks.sdk import WorkspaceClient


for name in ("run_id", "group_run_path"):
    dbutils.widgets.text(name, "")

run_id = dbutils.widgets.get("run_id").strip()
group_run_path = Path(dbutils.widgets.get("group_run_path").rstrip("/"))
manifest_path = group_run_path / "group-migration-manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
workbooks = manifest.get("workbooks", [])
if not workbooks:
    raise ValueError("Import manifest contains no workbooks")

client = WorkspaceClient()
dashboards = list(client.lakeview.list())
results = []
missing = []

for workbook in workbooks:
    run_tag = f"[bi-migration:{run_id}:{group_run_path.name}:{workbook['workbook_id']}]"
    candidate_tags = list(dict.fromkeys([run_tag, workbook.get("dashboard_tag", "")]))
    candidate_tags = [tag for tag in candidate_tags if tag]
    matched_by_id = {
        dashboard.dashboard_id: dashboard
        for dashboard in dashboards
        if any(tag in (dashboard.display_name or "") for tag in candidate_tags)
    }
    matches = list(matched_by_id.values())
    output_path = Path(workbook["output_path"])
    output_path.mkdir(parents=True, exist_ok=True)
    if len(matches) != 1:
        missing.append({
            "workbook_id": workbook["workbook_id"],
            "workbook_name": workbook["workbook_name"],
            "dashboard_tags": candidate_tags,
            "match_count": len(matches),
        })
        continue

    dashboard = client.lakeview.get(matches[0].dashboard_id)
    tag = next(tag for tag in candidate_tags if tag in (dashboard.display_name or ""))
    serialized = dashboard.serialized_dashboard or "{}"
    definition = json.loads(serialized)
    config_path = output_path / "dashboard-config.json"
    config_path.write_text(serialized, encoding="utf-8")
    result = {
        "workbook_id": workbook["workbook_id"],
        "workbook_name": workbook["workbook_name"],
        "workbook_path": workbook["workbook_path"],
        "dashboard_id": dashboard.dashboard_id,
        "display_name": dashboard.display_name,
        "dashboard_tag": tag,
        "config_path": str(config_path),
        "dataset_count": len(definition.get("datasets", [])),
        "page_count": len(definition.get("pages", [])),
        "status": "VALID" if definition.get("datasets") and definition.get("pages") else "INVALID",
        "reconciled_at": datetime.now(timezone.utc).isoformat(),
    }
    findings_path = output_path / "migration-findings.json"
    findings_document = json.loads(findings_path.read_text(encoding="utf-8")) if findings_path.exists() else {}
    result["findings"] = findings_document.get("findings", [])
    (output_path / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    results.append(result)

summary = {
    "run_id": run_id,
    "status": "SUCCESS" if len(results) == len(workbooks) and all(item["status"] == "VALID" for item in results) else "PARTIAL",
    "expected_workbooks": len(workbooks),
    "validated_dashboards": len(results),
    "dashboards": results,
    "findings": [
        {**finding, "stage": "dashboard_import", "workbook_name": result["workbook_name"]}
        for result in results
        for finding in result.get("findings", [])
    ],
    "missing_or_ambiguous": missing,
    "reconciled_at": datetime.now(timezone.utc).isoformat(),
}
summary_path = group_run_path / "import" / "summary.json"
summary_path.parent.mkdir(parents=True, exist_ok=True)
summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

if summary["status"] != "SUCCESS":
    raise RuntimeError(f"Dashboard reconciliation incomplete: {len(results)}/{len(workbooks)} validated")

dbutils.notebook.exit(json.dumps(summary))
