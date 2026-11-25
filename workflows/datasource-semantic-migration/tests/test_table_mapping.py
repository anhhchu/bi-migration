import pytest

from datasource_semantic_migration.table_mapping import TableMappingError, load_table_mapping


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def pairs(document):
    return [(entry["source"]["table"], entry["target"]["table"]) for entry in document["table_mappings"]]


def test_full_format_works_with_or_without_version(tmp_path):
    for version_line in ("version: '1.0'\n", "version: 1.0\n", "version: 1\n", ""):
        path = write(
            tmp_path,
            "full.yaml",
            version_line + "table_mappings:\n  - source: {table: Orders}\n    target: {table: main.sales.orders, grain: order line}\n",
        )
        document = load_table_mapping(path)
        assert pairs(document) == [("Orders", "main.sales.orders")]
        assert document["table_mappings"][0]["target"]["grain"] == "order line"


def test_simple_yaml_map_and_flat_list(tmp_path):
    simple = write(tmp_path, "simple.yaml", "Orders: main.sales.orders\nReturns: main.sales.returns\n")
    flat = write(tmp_path, "flat.yml", "- tableau_table: Orders\n  databricks_table: main.sales.orders\n")

    assert pairs(load_table_mapping(simple)) == [("Orders", "main.sales.orders"), ("Returns", "main.sales.returns")]
    assert pairs(load_table_mapping(flat)) == [("Orders", "main.sales.orders")]


def test_csv_with_flexible_headers_and_extra_columns(tmp_path):
    path = write(
        tmp_path,
        "my tables.csv",
        "Source Table,Target Table,Datasource,Grain,Business Keys,Notes\n"
        "Orders,main.sales.orders,Superstore,one row per order line,Order ID;Product ID,ignored\n"
        ",,,,,\n",
    )
    entry = load_table_mapping(path)["table_mappings"][0]

    assert entry["source"] == {"table": "Orders", "datasource": "Superstore"}
    assert entry["target"]["table"] == "main.sales.orders"
    assert entry["target"]["business_keys"] == ["Order ID", "Product ID"]


def test_json_and_several_files_are_merged(tmp_path):
    first = write(tmp_path, "a.json", '{"mappings": [{"from": "Orders", "to": "main.sales.orders"}]}')
    second = write(tmp_path, "b.csv", "source,target\nPeople,main.sales.people\n")

    assert pairs(load_table_mapping([first, second])) == [("Orders", "main.sales.orders"), ("People", "main.sales.people")]


def test_clear_errors_name_what_to_fix(tmp_path):
    missing_target = write(tmp_path, "m.csv", "source_table,target_table\nOrders,\n")
    short_target = write(tmp_path, "s.yaml", "Orders: orders\n")
    empty = write(tmp_path, "e.yaml", "")

    with pytest.raises(TableMappingError, match="m.csv, row 2: missing the Databricks"):
        load_table_mapping(missing_target)
    with pytest.raises(TableMappingError, match="catalog.schema.table"):
        load_table_mapping(short_target)
    with pytest.raises(TableMappingError, match="No table mappings found"):
        load_table_mapping(empty)
