# Databricks notebook source
import json
from pathlib import Path

import yaml
from pyspark.sql import functions as F

from datasource_semantic_migration.notebook_results import format_notebook_result, render_volume_links_html
from datasource_semantic_migration.artifacts import write_json_artifact


for widget_name in ("semantic_groups_index_path", "group_selector", "warehouse_id"):
    dbutils.widgets.text(widget_name, "")


def current_records(dataframe, relationship, side):
    rule = relationship.get("current_record")
    if not rule or rule["side"] not in {side, "both"}:
        return dataframe
    column_name = rule["recorded_to_column"]
    field = next(item for item in dataframe.schema.fields if item.name == column_name)
    value = rule["current_value"]
    predicate = F.col(column_name).isNull() if value is None else F.col(column_name) == F.lit(value).cast(field.dataType)
    return dataframe.filter(predicate)


def profile_relationship(relationship):
    left_definition = relationship["left"]
    right_definition = relationship["right"]
    left = spark.table(left_definition["table"])
    right = spark.table(right_definition["table"])
    left_columns = {field.name for field in left.schema.fields}
    right_columns = {field.name for field in right.schema.fields}
    required_left = set(left_definition["columns"]) | set(left_definition.get("unique_key", []))
    required_right = set(right_definition["columns"]) | set(right_definition.get("unique_key", []))
    temporal = relationship.get("temporal")
    if temporal:
        required_left.add(temporal["event_column"])
        required_right.update((temporal["valid_from_column"], temporal["valid_to_column"]))
    current = relationship.get("current_record")
    if current:
        if current["side"] in {"left", "both"}:
            required_left.add(current["recorded_to_column"])
        if current["side"] in {"right", "both"}:
            required_right.add(current["recorded_to_column"])
    missing_left = sorted(required_left - left_columns)
    missing_right = sorted(required_right - right_columns)
    result = {
        "name": relationship["name"],
        "cardinality": relationship["cardinality"],
        "left_table": left_definition["table"],
        "right_table": right_definition["table"],
        "missing_left_columns": missing_left,
        "missing_right_columns": missing_right,
    }
    if missing_left or missing_right:
        return {**result, "status": "BLOCKED"}

    left = current_records(left, relationship, "left")
    right = current_records(right, relationship, "right")
    left_alias = left.alias("left")
    right_alias = right.alias("right")
    predicates = [
        F.col(f"left.{left_column}") == F.col(f"right.{right_column}")
        for left_column, right_column in zip(left_definition["columns"], right_definition["columns"], strict=True)
    ]
    if temporal:
        predicates.append(F.col(f"left.{temporal['event_column']}") >= F.col(f"right.{temporal['valid_from_column']}"))
        upper_operator = F.col(f"left.{temporal['event_column']}") <= F.col(f"right.{temporal['valid_to_column']}")
        if not temporal.get("valid_to_inclusive", False):
            upper_operator = F.col(f"left.{temporal['event_column']}") < F.col(f"right.{temporal['valid_to_column']}")
        predicates.append(upper_operator)
    condition = predicates[0]
    for predicate in predicates[1:]:
        condition = condition & predicate
    unique_key = left_definition.get("unique_key") or left_definition["columns"]
    right_marker = (right_definition.get("unique_key") or right_definition["columns"])[0]
    joined = left_alias.join(right_alias, condition, "left").select(
        *(F.col(f"left.{column}").alias(column) for column in unique_key),
        F.col(f"right.{right_marker}").alias("__right_match"),
    )
    matches = joined.groupBy(*unique_key).agg(F.count("__right_match").alias("match_count"))
    left_count = left.count()
    left_identity_count = left.select(*unique_key).distinct().count()
    statistics = matches.agg(
        F.max("match_count").alias("maximum_matches"),
        F.sum(F.when(F.col("match_count") == 0, 1).otherwise(0)).alias("orphan_count"),
        F.sum(F.when(F.col("match_count") > 1, 1).otherwise(0)).alias("fanout_count"),
    ).first()
    maximum_matches = int(statistics.maximum_matches or 0)
    fanout_count = int(statistics.fanout_count or 0)
    orphan_count = int(statistics.orphan_count or 0)
    return {
        **result,
        "status": "READY" if maximum_matches <= 1 and left_count == left_identity_count else "BLOCKED",
        "left_row_count": left_count,
        "left_identity_count": left_identity_count,
        "maximum_matches_per_left_row": maximum_matches,
        "fanout_row_count": fanout_count,
        "orphan_row_count": orphan_count,
        "orphan_rate": orphan_count / left_identity_count if left_identity_count else 0.0,
    }


groups_index_path = Path(dbutils.widgets.get("semantic_groups_index_path"))
groups_index = json.loads(groups_index_path.read_text(encoding="utf-8"))
group_selector = dbutils.widgets.get("group_selector")
group_index = int(group_selector.split("|", 1)[0])
group = groups_index["groups"][group_index]
group_manifest_path = Path(group["group_manifest_path"])
group_manifest = json.loads(group_manifest_path.read_text(encoding="utf-8"))
mapping = yaml.safe_load(Path(group_manifest["mapping_path"]).read_text(encoding="utf-8"))
group_internal_path = Path(group_manifest["internal_path"])

target_profiles = []
for target_table in group_manifest["target_tables"]:
    dataframe = spark.table(target_table)
    matching_mappings = [entry for entry in mapping["table_mappings"] if entry["target"]["table"] == target_table]
    business_keys = sorted({key for entry in matching_mappings for key in entry["target"].get("business_keys", [])})
    columns = {field.name: field.dataType.simpleString() for field in dataframe.schema.fields}
    missing_keys = [key for key in business_keys if key not in columns]
    target_profiles.append(
        {
            "table": target_table,
            "columns": columns,
            "business_keys": business_keys,
            "missing_business_keys": missing_keys,
            "temporal_models": sorted({entry["target"].get("temporal_model", "none") for entry in matching_mappings}),
            "row_count": dataframe.count(),
        }
    )

relationship_profiles = [profile_relationship(relationship) for relationship in mapping.get("relationships", [])]
profile_status = "READY"
if any(item["missing_business_keys"] for item in target_profiles) or any(
    item["status"] == "BLOCKED" for item in relationship_profiles
):
    profile_status = "BLOCKED"
profile = {
    "schema_version": "1.0",
    "workflow_run_id": groups_index["workflow_run_id"],
    "group_id": group["group_id"],
    "candidate_metric_view_fqn": group_manifest["candidate_metric_view_fqn"],
    "allowed_target_tables": group_manifest["target_tables"],
    "targets": target_profiles,
    "relationships": relationship_profiles,
    "status": profile_status,
}
profile_path = write_json_artifact(profile, group_internal_path / "target-profile.json")
result_path = group_internal_path / "importbi-result.json"
prompt_path = group_internal_path / "importbi-prompt.md"
prompt_path.write_text(
    f"""/importBI

Run unattended in semantic-only mode for the datasource group defined at:
`{group_manifest_path}`

Use the immutable table mapping:
`{group_manifest['mapping_path']}`

Use the deterministic target profile:
`{profile_path}`

Create or replace exactly this candidate Unity Catalog Metric View:
`{group_manifest['candidate_metric_view_fqn']}`

Do not create or modify dashboards or Genie Agents. Use only the exact physical Databricks tables declared in the mapping. Preserve supported calculations, relationships, filters, aggregations, LOD semantics, parameters, units, formats, comments, display names, and synonyms. Leave unsupported or ambiguous semantics out rather than approximating them.

Write a JSON result to `{result_path}` with these fields:

- metric_view_fqn: the Metric View created or replaced, or null if none was saved.
- status: SUCCESS, PARTIAL, or FAILED.
- dimensions_created, measures_created: lists of field names, not counts.
- items_not_translated: list of objects with name and reason for every Tableau field left out.
- source_tables_used: list of physical tables the Metric View reads.
- notes: list of strings.
- Optional: parameters_created (list of names) and approximations (objects with name and detail) for any translated item that is not an exact equivalent.

If no Metric View is saved, write FAILED and fail the task.
""",
    encoding="utf-8",
)
for key, value in {
    "group_path": group["group_path"],
    "group_manifest_path": str(group_manifest_path),
    "mapping_path": group_manifest["mapping_path"],
    "target_profile_path": str(profile_path),
    "prompt_path": str(prompt_path),
    "metric_view_fqn": group_manifest["candidate_metric_view_fqn"],
    "importbi_result_path": str(result_path),
}.items():
    dbutils.jobs.taskValues.set(key=key, value=value)
result = {
    "group_id": group["group_id"],
    "group_manifest_path": str(group_manifest_path),
    "target_profile_path": str(profile_path),
    "prompt_path": str(prompt_path),
    "metric_view_fqn": group_manifest["candidate_metric_view_fqn"],
    "status": profile["status"],
}
if profile["status"] != "READY":
    raise RuntimeError(f"Target profile blocked candidate creation: {result}")
print("\n=== Prepare Candidate Context ===")
print(format_notebook_result(result))
displayHTML(render_volume_links_html(result))
dbutils.notebook.exit(format_notebook_result(result))
