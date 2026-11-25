# Databricks notebook source
import json
import re
from pathlib import Path

import yaml

from datasource_semantic_migration.metric_repair import disallowed_tables, target_lineage
from datasource_semantic_migration.notebook_results import format_notebook_result, render_volume_links_html
from datasource_semantic_migration.artifacts import write_json_artifact


for widget_name in ("group_manifest_path", "target_profile_path", "importbi_result_path", "warehouse_id"):
    dbutils.widgets.text(widget_name, "")


def metric_yaml_from_definition(definition):
    match = re.search(r"\$\$(.*?)\$\$", definition, flags=re.DOTALL)
    return match.group(1).strip() + "\n" if match else None


group_manifest_path = Path(dbutils.widgets.get("group_manifest_path"))
group_manifest = json.loads(group_manifest_path.read_text(encoding="utf-8"))
target_profile = json.loads(Path(dbutils.widgets.get("target_profile_path")).read_text(encoding="utf-8"))
candidate_fqn = group_manifest["candidate_metric_view_fqn"]
quoted_fqn = ".".join(f"`{part}`" for part in candidate_fqn.split("."))
result_path = Path(dbutils.widgets.get("importbi_result_path"))
agent_result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else None
findings = []
definition = None
repair_attempts = 0
candidate_exists = spark.catalog.tableExists(candidate_fqn)

if candidate_exists:
    try:
        rows = spark.sql(f"SHOW CREATE TABLE {quoted_fqn}").collect()
        definition = "\n".join(str(row[0]) for row in rows)
        spark.sql(f"DESCRIBE TABLE EXTENDED {quoted_fqn}").limit(1).collect()
    except Exception as error:
        findings.append({"code": "CANDIDATE_NOT_QUERYABLE", "severity": "ERROR", "message": str(error)})
else:
    findings.append({"code": "CANDIDATE_NOT_FOUND", "severity": "ERROR", "message": candidate_fqn})

metric_document = None
if definition:
    group_path = Path(group_manifest["group_path"])
    (group_path / "metric-view.sql").write_text(definition + "\n", encoding="utf-8")
    metric_yaml = metric_yaml_from_definition(definition)
    if metric_yaml:
        (group_path / "metric-view.yaml").write_text(metric_yaml, encoding="utf-8")
        try:
            metric_document = yaml.safe_load(metric_yaml)
        except yaml.YAMLError as error:
            findings.append({"code": "METRIC_YAML_INVALID", "severity": "ERROR", "message": str(error)})
    else:
        findings.append(
            {"code": "METRIC_YAML_UNAVAILABLE", "severity": "WARNING", "message": "SHOW CREATE output has no YAML body"}
        )
    # Exact table names from the deployed YAML (source and every join), not a text search.
    # Without parsed YAML, fall back to the table names that appear in the definition text.
    lineage_document = metric_document if metric_document else {"source": definition}
    read_tables = {table.casefold() for table in target_lineage(lineage_document)}
    allowed_lineage = [table for table in group_manifest["target_tables"] if table.casefold() in read_tables]
    if not allowed_lineage:
        findings.append(
            {
                "code": "APPROVED_LINEAGE_NOT_FOUND",
                "severity": "ERROR",
                "allowed_tables": group_manifest["target_tables"],
            }
        )
    unexpected_tables = sorted(
        set(disallowed_tables(metric_document or {}, group_manifest["target_tables"]) if metric_document else [])
        | {
            table
            for table in (agent_result or {}).get("source_tables_used", [])
            if table.casefold() not in {item.casefold() for item in group_manifest["target_tables"]}
        }
    )
    if unexpected_tables:
        findings.append({"code": "DISALLOWED_LINEAGE", "severity": "ERROR", "tables": unexpected_tables})
    if agent_result is None:
        dimensions = (metric_document or {}).get("dimensions", [])
        measures = (metric_document or {}).get("measures", [])
        agent_result = {
            "metric_view_fqn": candidate_fqn,
            "status": "RECOVERED_FROM_CATALOG",
            "dimensions_created": [str(item["name"]) for item in dimensions if item.get("name")],
            "measures_created": [str(item["name"]) for item in measures if item.get("name")],
            "items_not_translated": [],
            "source_tables_used": allowed_lineage,
            "notes": ["The Genie task did not write its result artifact; reconciliation rebuilt it from Unity Catalog."],
        }
        write_json_artifact(agent_result, result_path)
        repair_attempts = 1
        findings.append(
            {
                "code": "IMPORT_RESULT_RECONSTRUCTED",
                "severity": "WARNING",
                "message": "Reconstructed missing import result from the catalog definition",
            }
        )

for relationship in target_profile.get("relationships", []):
    if relationship["status"] == "BLOCKED":
        findings.append(
            {
                "code": "RELATIONSHIP_PROFILE_BLOCKED",
                "severity": "ERROR",
                "relationship": relationship["name"],
            }
        )
for datasource in group_manifest["datasources"]:
    metric_ir = json.loads(Path(datasource["metric_ir_path"]).read_text(encoding="utf-8"))
    findings.extend(metric_ir["findings"])

blocking = [item for item in findings if item.get("severity") == "ERROR"]
if not candidate_exists:
    status = "FAILED"
elif blocking or (agent_result and agent_result.get("status") in {"PARTIAL", "FAILED"}):
    status = "PARTIAL"
else:
    status = "PASS_SEMANTIC_ONLY"
evaluation = {
    "schema_version": "1.0",
    "workflow_run_id": group_manifest["workflow_run_id"],
    "group_id": group_manifest["group_id"],
    "metric_view_fqn": candidate_fqn,
    "evidence_level": "SEMANTIC_ONLY",
    "status": status,
    "agent_result": agent_result,
    "target_profile_path": dbutils.widgets.get("target_profile_path"),
    "findings": findings,
    "repair_attempts": repair_attempts,
}
group_path = Path(group_manifest["group_path"])
group_internal_path = Path(group_manifest["internal_path"])
evaluation_path = write_json_artifact(evaluation, group_internal_path / "evaluation.json")
final_result = {
    "schema_version": "1.0",
    "workflow_run_id": group_manifest["workflow_run_id"],
    "group_id": group_manifest["group_id"],
    "status": status,
    "metric_view_fqn": candidate_fqn if candidate_exists else None,
    "evaluation_path": str(evaluation_path),
    "finding_count": len(findings),
    "blocking_finding_count": len(blocking),
    "repair_attempts": repair_attempts,
}
final_result_path = write_json_artifact(final_result, group_internal_path / "final-result.json")
result = {**final_result, "final_result_path": str(final_result_path)}
print("\n=== Reconcile, Evaluate, Repair ===")
print(format_notebook_result(result))
displayHTML(render_volume_links_html(result))
if status == "FAILED":
    raise RuntimeError(f"Semantic group migration failed: {final_result_path}")
dbutils.notebook.exit(format_notebook_result(result))
