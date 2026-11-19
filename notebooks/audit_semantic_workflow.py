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
    "warnings": [],
}
if not missing:
    agent = json.loads((semantic_dir / "genie-agent-result.json").read_text(encoding="utf-8"))
    benchmarks = (
        agent.get("benchmark_configuration")
        or agent.get("benchmarks")
        or agent.get("benchmark_questions")
        or []
    )
    benchmark_summary = agent.get("benchmark_summary") or {}
    summary["benchmark_count"] = len(benchmarks)
    summary["benchmark_results"] = benchmark_summary
    if not benchmarks:
        summary["status"] = "INCOMPLETE"
        summary["missing"].append("Genie Agent configuration contains no benchmark questions")
    elif agent.get("status") != "SUCCESS" or benchmark_summary.get("failures"):
        summary["status"] = "COMPLETE_WITH_WARNINGS"
        summary["warnings"].append(
            f"Benchmark evaluation: {benchmark_summary.get('num_correct', 0)}/{len(benchmarks)} correct"
        )
(semantic_dir / "semantic-audit.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
dbutils.notebook.exit(json.dumps(summary))
