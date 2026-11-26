# Databricks notebook source
# Compare one migrated group's candidate Metric View with reference values computed on the Tableau extract.
# The candidate itself is not changed. Writes groups/<group>/_internal/parity/parity-results.json, a cached
# extract table and a temporary shadow Metric View in the staging schema, and refreshes the group's report.
import json
import shutil
import tempfile
from html import escape
from datetime import datetime, timezone
from pathlib import Path

import yaml

from datasource_semantic_migration.artifacts import write_json_artifact
from datasource_semantic_migration.metric_repair import create_metric_view_sql
from datasource_semantic_migration.notebook_results import format_notebook_result, render_volume_links_html
from datasource_semantic_migration.parity import (
    bind_columns,
    candidate_dimensions,
    safe_column_names,
    choose_dimensions,
    compare_results,
    comparison_queries,
    measure_outcomes,
    parity_summary,
    plan_measures,
    quote,
    shadow_metric_view,
    shadow_source_sql,
)
from datasource_semantic_migration.reporting import build_group_review, build_workflow_review, render_workflow_html
from datasource_semantic_migration.source_systems import source_system_of
from datasource_semantic_migration.sources.tableau.extracts import (
    copy_extract,
    datasource_extracts,
    export_parquet,
    main_table,
)
from datasource_semantic_migration.sources.tableau.formula_sql import FormulaTranslator

WORKSPACE_URL = "https://" + spark.conf.get("spark.databricks.workspaceUrl").removeprefix("https://").rstrip("/")

for widget_name in ("group_path", "catalog", "staging_schema"):
    dbutils.widgets.text(widget_name, "")
group_path = Path(dbutils.widgets.get("group_path").rstrip("/"))
catalog = dbutils.widgets.get("catalog").strip()
staging_schema = dbutils.widgets.get("staging_schema").strip()
internal_path = group_path / "_internal"
manifest = json.loads((internal_path / "group-manifest.json").read_text(encoding="utf-8"))
run_root = group_path.parents[1]
inventory = json.loads((run_root / "_internal" / "inventory" / "input-inventory.json").read_text(encoding="utf-8"))
metric_view = yaml.safe_load((group_path / "metric-view.yaml").read_text(encoding="utf-8")) or {}
group_mapping = yaml.safe_load((group_path / "mapping.yaml").read_text(encoding="utf-8")) or {}
# Optional column mappings: table entries may carry `columns: {Tableau field: Databricks column}`.
column_mappings = {
    str(tableau): str(databricks)
    for entry in group_mapping.get("table_mappings", [])
    for tableau, databricks in (entry.get("columns") or {}).items()
}
parity_path = internal_path / "parity"
started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
staging = f"{quote(catalog)}.{quote(staging_schema)}"
result = {
    "schema_version": "1.0",
    "group_id": manifest["group_id"],
    "group_name": manifest.get("display_name"),
    "metric_view_fqn": manifest["candidate_metric_view_fqn"],
    "started_at": started_at,
    "outcomes": [],
}
print("=== Datasource number check ===")
print(f"Group:        {manifest.get('display_name') or manifest['group_id']} ({manifest['group_id']})")
print(f"Metric View:  {manifest['candidate_metric_view_fqn']}")
print(f"Definition:   {group_path / 'metric-view.yaml'}")


def finish(summary_reason=None):
    outcomes = result["outcomes"]
    result["summary"] = parity_summary(outcomes, available=bool(outcomes), reason=summary_reason)
    result["finished_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    write_json_artifact(result, parity_path / "parity-results.json")


# 1. The datasource with an extract (the first one; its measures are the ones compared).
chosen = None
for datasource in manifest["datasources"]:
    datasource_ir = json.loads(Path(datasource["datasource_ir_path"]).read_text(encoding="utf-8"))
    extracts = datasource_extracts(inventory, datasource_ir)
    if extracts:
        chosen = (datasource, datasource_ir, extracts[0])
        break
if chosen is None:
    finish("no datasource in this group has an extract in the upload (TDS and TWB files contain no data)")
else:
    datasource, datasource_ir, extract = chosen
    result["datasource"] = datasource["datasource_name"]
    result["extract"] = {key: extract[key] for key in ("package_path", "member_path", "byte_size", "key")}
    print(f"Datasource:   {datasource['datasource_name']}")
    print(f"Extract:      {extract['member_path']} in {Path(extract['package_path']).name}")
    extract_table = f"{staging}.{quote('bim_x_' + extract['key'])}"
    shadow_view = f"{staging}.{quote('bim_shadow_' + manifest['group_id'].replace('-', '_')[:40] + '_' + extract['key'][:8])}"
    # 2. Load the extract once; later checks of the same extract reuse the table.
    if not spark.catalog.tableExists(f"{catalog}.{staging_schema}.bim_x_{extract['key']}"):
        work = Path(tempfile.mkdtemp(prefix="extract-"))
        try:
            local_hyper = work / "extract.hyper"
            copy_extract(extract["package_path"], extract["member_path"], local_hyper)
            tables = export_parquet(local_hyper, run_root / "_internal" / "extracts" / extract["key"], work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        table = main_table(tables)
        result["extract"]["tables"] = [{key: item[key] for key in ("table", "rows")} for item in tables]
        # Tableau names (Business Unit) become Delta-safe names (business_unit); comments keep the original.
        safe_names = safe_column_names(table["columns"])
        select_list = ", ".join(f"{quote(original)} AS {quote(safe)}" for original, safe in safe_names.items())
        spark.sql(
            f"CREATE TABLE IF NOT EXISTS {extract_table} "
            f"AS SELECT {select_list} FROM parquet.`{table['parquet_path']}`"
        )
        spark.sql(
            f"COMMENT ON TABLE {extract_table} IS "
            + json.dumps(f"Tableau extract {extract['member_path']} from {Path(extract['package_path']).name}; for number checks")
        )
        for original, safe in safe_names.items():
            spark.sql(f"ALTER TABLE {extract_table} ALTER COLUMN {quote(safe)} COMMENT " + json.dumps(f"Tableau field: {original}"))
        result["extract"]["column_names"] = safe_names
    extract_columns = spark.table(extract_table).columns
    result["extract_table"] = extract_table.replace("`", "")
    result["shadow_metric_view"] = shadow_view.replace("`", "")
    print(f"Extract table: {result['extract_table']} (cached)")
    print(f"Shadow view:  {result['shadow_metric_view']} (temporary; dropped at the end)")
    # 3. The candidate source's output columns, and which extract column feeds each.
    source = str(metric_view.get("source") or "").strip()
    is_query = source.split(None, 1)[0].upper() in {"SELECT", "WITH"} if source else False
    described = spark.sql(f"DESCRIBE QUERY {source}" if is_query else f"DESCRIBE TABLE {source}").collect()
    output_columns = [
        (row["col_name"], row["data_type"]) for row in described if row["col_name"] and not row["col_name"].startswith("#")
    ]
    binding = bind_columns(output_columns, extract_columns, metric_view=metric_view, column_mappings=column_mappings)
    result["binding"] = binding
    # Measures from every datasource in the group, the one with the extract first; each is translated with
    # its own definition, over this extract's columns (the datasources share the same fields).
    ordered = [datasource] + [item for item in manifest["datasources"] if item is not datasource]
    source_measures, translators = [], []
    for position, item in enumerate(ordered):
        item_ir = datasource_ir if item is datasource else json.loads(Path(item["datasource_ir_path"]).read_text(encoding="utf-8"))
        translators.append(FormulaTranslator(item_ir, extract_columns))
        for measure in json.loads(Path(item["metric_ir_path"]).read_text(encoding="utf-8"))["measures"]:
            source_measures.append({**measure, "_definition": position})
    plans = plan_measures(
        metric_view=metric_view,
        source_measures=source_measures,
        output_columns=output_columns,
        binding=binding,
        reference_for=lambda measure: translators[measure["_definition"]].measure_reference(measure),
    )
    try:
        # 4. The shadow Metric View: the candidate with its source replaced by the extract.
        shadow = shadow_metric_view(metric_view, shadow_source_sql(extract_table, output_columns, binding))
        spark.sql(create_metric_view_sql(shadow_view.replace("`", ""), shadow))
        dimensions = candidate_dimensions(metric_view, binding)
        distinct_counts = {}
        if dimensions:
            columns = sorted({item["extract_column"] for item in dimensions})
            counts_row = spark.sql(
                "SELECT " + ", ".join(f"COUNT(DISTINCT {quote(column)}) AS c{index}" for index, column in enumerate(columns))
                + f" FROM {extract_table}"
            ).collect()[0]
            distinct_counts = {column: counts_row[f"c{index}"] for index, column in enumerate(columns)}
        chosen_dimensions = choose_dimensions(dimensions, distinct_counts)
        result["dimensions"] = chosen_dimensions
        comparisons, query_errors = [], {}

        def run(plan_subset, dimension):
            queries = comparison_queries(shadow_view=shadow_view, extract_table=extract_table, plans=plan_subset, dimension=dimension)
            candidate_rows = [row.asDict() for row in spark.sql(queries["candidate"]).collect()]
            reference_rows = [row.asDict() for row in spark.sql(queries["reference"]).collect()]
            return compare_results(plan_subset, candidate_rows, reference_rows, grouped_by=dimension["dimension"] if dimension else None)

        comparable = [plan for plan in plans if plan["comparable"]]
        for dimension in [None, *chosen_dimensions]:
            try:
                comparisons.append(run(comparable, dimension))
            except Exception:
                # One failing measure must not hide the others: retry one measure at a time.
                merged = {}
                for plan in comparable:
                    try:
                        merged.update(run([plan], dimension))
                    except Exception as error:
                        query_errors.setdefault(plan["measure"], str(error)[:500])
                comparisons.append(merged)
        for plan in plans:
            if plan["measure"] in query_errors and plan["comparable"]:
                plan.update(comparable=False, reason=f"Comparison query failed: {query_errors[plan['measure']]}")
        result["plans"] = plans
        result["outcomes"] = measure_outcomes(plans, comparisons)
        finish()
    except Exception as error:
        result["plans"] = plans
        result["error"] = str(error)[:2000]
        finish(f"the shadow Metric View could not be created or queried: {str(error)[:300]}")
    finally:
        spark.sql(f"DROP VIEW IF EXISTS {shadow_view}")

# 5. Refresh this group's report and the run index with the number check.
group_report_path = Path(manifest.get("report_path") or run_root / "reports" / "groups" / manifest["group_id"])
evaluation_path = internal_path / "evaluation.json"
evaluation = json.loads(evaluation_path.read_text(encoding="utf-8")) if evaluation_path.is_file() else {}
final_result_path = internal_path / "final-result.json"
final_result = json.loads(final_result_path.read_text(encoding="utf-8")) if final_result_path.is_file() else {"status": "PARTIAL"}
scorecard_evaluation = None
attempt_dir = (evaluation.get("repair") or {}).get("attempt_dir")
if attempt_dir and (Path(attempt_dir) / "evaluation-after.json").is_file():
    scorecard_evaluation = json.loads((Path(attempt_dir) / "evaluation-after.json").read_text(encoding="utf-8"))
review = build_group_review(
    group={
        "group_id": manifest["group_id"],
        "display_name": manifest.get("display_name"),
        "source_system": source_system_of(manifest),
        "group_path": str(group_path),
        "internal_path": str(internal_path),
        "report_path": str(group_report_path),
        "source_summary_path": str(internal_path / "source-summary.json"),
    },
    final_result=final_result,
    evaluation=evaluation,
    metric_view=metric_view,
    scorecard_evaluation=scorecard_evaluation,
    group_mapping=group_mapping,
    parity=result,
)
write_json_artifact(review, group_report_path / "migration-review.json")
(group_report_path / "migration-review.html").write_text(
    render_workflow_html({"workspace_url": WORKSPACE_URL, **build_workflow_review(workflow_run_id=manifest["workflow_run_id"], groups=[review])}),
    encoding="utf-8",
)
group_reviews = [
    review if path.parent.name == manifest["group_id"] else json.loads(path.read_text(encoding="utf-8"))
    for path in sorted((run_root / "reports" / "groups").glob("*/migration-review.json"))
]
summary = build_workflow_review(workflow_run_id=manifest["workflow_run_id"], groups=group_reviews)
write_json_artifact(summary, run_root / "reports" / "index.json")
(run_root / "reports" / "index.html").write_text(render_workflow_html({"workspace_url": WORKSPACE_URL, **summary}), encoding="utf-8")

def _value(value):
    """A readable number: thousands separators, at most four decimals; anything else as text."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,.0f}" if number.is_integer() else f"{number:,.4f}".rstrip("0").rstrip(".")


rows = []
for outcome in result["outcomes"]:
    total = next((check for check in outcome.get("checks", []) if not check.get("grouped_by")), None)
    pair = (total or {}).get("values", [{}])[0] if total else {}
    checked = ", ".join(f"{check.get('grouped_by') or 'total'}: {check['status'].lower()}" for check in outcome.get("checks", []))
    rows.append((outcome["status"], outcome["measure"], _value(pair.get("candidate")), _value(pair.get("reference")),
                 checked or outcome.get("reason") or ""))
print(f"\nMetric View {result['metric_view_fqn']}: {result['summary']['status']} — "
      f"{result['summary']['compared_count']} of {result['summary']['measure_count']} measure(s) compared, "
      f"{result['summary']['FAILED_VALUE']} differ, {result['summary']['NOT_COMPARABLE']} not compared"
      + (f" ({result['summary']['reason']})" if result["summary"].get("reason") else ""))
print(f"{'Result':<20} {'Measure':<32} {'Metric View total':>20} {'Extract total':>20}  Checks / reason")
for status, measure, candidate, reference, detail in rows:
    print(f"{status:<20} {measure[:32]:<32} {candidate:>20} {reference:>20}  {detail[:140]}")
displayHTML(
    f"<h3>Number check: <code>{escape(result['metric_view_fqn'])}</code></h3>"
    f"<p>{escape(result['summary']['status'])}: {result['summary']['compared_count']} of {result['summary']['measure_count']} "
    "measure(s) compared with the Tableau extract.</p><table><tr><th>Result</th><th>Measure</th>"
    "<th>Metric View total</th><th>Extract total</th><th>Checks / reason</th></tr>"
    + "".join(f"<tr><td>{escape(a)}</td><td>{escape(b)}</td><td>{escape(c)}</td><td>{escape(d)}</td><td>{escape(e)}</td></tr>" for a, b, c, d, e in rows)
    + "</table>"
)

output = {
    "group_id": manifest["group_id"],
    "metric_view_fqn": result["metric_view_fqn"],
    "parity": result["summary"],
    "parity_results_path": str(parity_path / "parity-results.json"),
    "report_path": str(group_report_path / "migration-review.html"),
}
print(format_notebook_result(output))
displayHTML(render_volume_links_html(output))
dbutils.notebook.exit(format_notebook_result(output))
