# Databricks notebook source
import json
from pathlib import Path


for name in ("run_id", "group_run_path"):
    dbutils.widgets.text(name, "")
run_id = dbutils.widgets.get("run_id").strip()
semantic_dir = Path(dbutils.widgets.get("group_run_path").rstrip("/")) / "semantic"
benchmark_path = semantic_dir / "benchmark-set.json"
if not benchmark_path.exists():
    raise FileNotFoundError(f"Benchmark set not found: {benchmark_path}")
benchmarks = json.loads(benchmark_path.read_text(encoding="utf-8"))
items = benchmarks.get("questions", benchmarks) if isinstance(benchmarks, dict) else benchmarks
if not isinstance(items, list) or len(items) < 12:
    raise ValueError("Held-out benchmark set must contain at least 12 questions")
registration = {"run_id": run_id, "status": "REGISTERED", "count": len(items), "path": str(benchmark_path)}
(semantic_dir / "benchmark-registration.json").write_text(json.dumps(registration, indent=2), encoding="utf-8")
dbutils.notebook.exit(json.dumps(registration))
