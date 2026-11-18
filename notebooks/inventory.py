# Databricks notebook source
from bi_migration.pipeline import run_backend_pipeline


for parameter_name in (
    "input_path",
    "mapping_docs_path",
    "target_metadata_path",
    "output_path",
    "run_id",
    "source_base_uri",
):
    dbutils.widgets.text(parameter_name, "")


result = run_backend_pipeline(
    input_path=dbutils.widgets.get("input_path"),
    mapping_documents_path=dbutils.widgets.get("mapping_docs_path"),
    target_metadata_path=dbutils.widgets.get("target_metadata_path"),
    domain="uploaded",
    output_path=dbutils.widgets.get("output_path"),
    run_id=dbutils.widgets.get("run_id"),
    source_base_uri=dbutils.widgets.get("source_base_uri"),
)

display(result)
