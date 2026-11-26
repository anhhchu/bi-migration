# Databricks notebook source
# Diagnostic: can serverless compute read a Tableau .hyper extract from a Unity Catalog Volume?
# Input is either a .hyper file (hyper_path) or an extract inside an uploaded .tdsx/.twbx
# (package_path + member_path). Read-only for the input; writes only beneath output_path. Run once per workspace before relying on
# extract-based number checks. Each step records PASS or FAIL with the error, and the notebook never stops
# on a failed step, so one run answers every question.
import json
import os
import platform
import shutil
import tempfile
import time
import traceback
import zipfile
from pathlib import Path

for widget_name in ("hyper_path", "package_path", "member_path", "output_path"):
    dbutils.widgets.text(widget_name, "")
package_path = dbutils.widgets.get("package_path").strip()
member_path = dbutils.widgets.get("member_path").strip()
hyper_path = Path(dbutils.widgets.get("hyper_path")) if dbutils.widgets.get("hyper_path").strip() else None
output_path = Path(dbutils.widgets.get("output_path"))
output_path.mkdir(parents=True, exist_ok=True)
results = {
    "python": platform.python_version(),
    "machine": platform.machine(),
    "input": package_path + "!" + member_path if package_path else str(hyper_path),
    "local_disk_free_bytes": shutil.disk_usage(tempfile.gettempdir()).free,
    "memory_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"),
    "steps": {},
}


def step(name, action):
    started = time.time()
    try:
        value = action()
        results["steps"][name] = {"status": "PASS", "seconds": round(time.time() - started, 2), "value": value}
        return value
    except Exception as error:  # Every failure is recorded; later steps still run.
        results["steps"][name] = {
            "status": "FAIL",
            "seconds": round(time.time() - started, 2),
            "error": f"{type(error).__name__}: {error}"[:2000],
            "trace": traceback.format_exc()[-2000:],
        }
        return None


def import_api():
    import tableauhyperapi

    return tableauhyperapi.__version__ if hasattr(tableauhyperapi, "__version__") else "imported"


step("import_tableauhyperapi", import_api)
work = Path(tempfile.mkdtemp(prefix="hyper-check-"))


def tables(connection):
    return [
        str(table)
        for schema in connection.catalog.get_schema_names()
        for table in connection.catalog.get_table_names(schema)
    ]


def open_and_describe(path):
    from tableauhyperapi import Connection, CreateMode, HyperProcess, Telemetry

    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters={"log_dir": str(work)}) as hyper:
        with Connection(hyper.endpoint, str(path), CreateMode.NONE) as connection:
            return {
                table: {
                    "rows": connection.execute_scalar_query(f"SELECT COUNT(*) FROM {table}"),
                    "columns": [
                        f"{column.name} {column.type}"
                        for column in connection.catalog.get_table_definition(table).columns
                    ],
                }
                for table in tables(connection)
            }


local_copy = work / "extract.hyper"
if package_path:
    # 1. Stream only the extract out of the package to local disk (the package itself is not unzipped).
    def copy_member():
        with zipfile.ZipFile(package_path) as archive, archive.open(member_path) as source, local_copy.open("wb") as target:
            shutil.copyfileobj(source, target, length=8 * 1024 * 1024)
        return local_copy.stat().st_size

    step("copy_extract_out_of_package", copy_member)
else:
    # 1. Open the extract where it is, through the Volume path.
    step("open_directly_from_volume", lambda: open_and_describe(hyper_path))
    # 2. Copy to local disk (Hyper may need a local, lockable file).
    step("copy_to_local_disk", lambda: shutil.copyfile(hyper_path, local_copy) and local_copy.stat().st_size)
described = step("open_local_copy", lambda: open_and_describe(local_copy))


def export_parquet():
    from tableauhyperapi import Connection, CreateMode, HyperProcess, Telemetry

    exported = {}
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters={"log_dir": str(work)}) as hyper:
        with Connection(hyper.endpoint, str(local_copy), CreateMode.NONE) as connection:
            for position, table in enumerate(tables(connection)):
                target = work / f"table_{position}.parquet"
                connection.execute_command(f"COPY {table} TO '{target}' WITH (FORMAT PARQUET)")
                shutil.copyfile(target, output_path / target.name)
                exported[table] = str(output_path / target.name)
    return exported


# 3. Export each table to Parquet with Hyper's COPY, and copy it to the Volume.
exported = step("export_parquet_with_hyper_copy", export_parquet)


def read_with_spark():
    return {table: spark.read.parquet(path).count() for table, path in (exported or {}).items()}


# 4. Read the Parquet back with Spark; row counts must match step 2.
counts = step("read_parquet_with_spark", read_with_spark)
if described and counts:
    results["row_counts_match"] = all(described[table]["rows"] == counts.get(table) for table in described)

shutil.rmtree(work, ignore_errors=True)
(output_path / "results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
print(json.dumps(results, indent=2, default=str))
dbutils.notebook.exit(json.dumps({name: item["status"] for name, item in results["steps"].items()}))
