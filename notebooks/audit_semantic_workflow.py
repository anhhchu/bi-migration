# Databricks notebook source
import json
from pathlib import Path


for name in ("run_id", "group_run_path"):
    dbutils.widgets.text(name, "")
run_id = dbutils.widgets.get("run_id").strip()
group_run_path = Path(dbutils.widgets.get("group_run_path").rstrip("/"))
manifest = json.loads((group_run_path / "group-migration-manifest.json").read_text(encoding="utf-8"))
semantic_dir = group_run_path / "semantic"
required = [
    Path(manifest["dashboard_manifest_path"]),
    *[Path(workbook["output_path"]) / "dashboard-config.json" for workbook in manifest["workbooks"]],
    semantic_dir / "semantic-preflight.json",
    semantic_dir / "metric-view-result.json",
    semantic_dir / "genie-agent-result.json",
    semantic_dir / "metric-view-validation.json",
]
missing = [str(path) for path in required if not path.exists()]
summary = {
    "run_id": run_id,
    "status": "COMPLETE" if not missing else "INCOMPLETE",
    "artifacts": [str(path) for path in required if path.exists()],
    "missing": missing,
}
if not missing:
    agent = json.loads((semantic_dir / "genie-agent-result.json").read_text(encoding="utf-8"))
    benchmarks = agent.get("benchmarks") or agent.get("benchmark_questions") or []
    if len(benchmarks) < 12:
        summary["status"] = "INCOMPLETE"
        summary["missing"].append("Genie Agent configuration contains fewer than 12 benchmark questions")
(semantic_dir / "semantic-audit.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
if summary["status"] != "COMPLETE":
    raise RuntimeError("Semantic workflow incomplete: " + "; ".join(summary["missing"]))
dbutils.notebook.exit(json.dumps(summary))
