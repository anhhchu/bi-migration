from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lark import Lark, Token

from . import __version__
from .discovery import sha256_file
from .tableau_parser import write_json_artifact


FORMULA_LEXER = Lark(
    r"""
    start: token*
    ?token: FIELD_REF | STRING | NUMBER | WORD | SYMBOL
    FIELD_REF.4: /\[[^\]\r\n]+\]/
    COMMENT.4: /\/\/[^\r\n]*/
    STRING.3: /"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/
    NUMBER.2: /(?:\d+(?:\.\d*)?|\.\d+)/
    WORD.2: /[A-Za-z_][A-Za-z0-9_]*/
    SYMBOL.1: /./s
    %ignore COMMENT
    %ignore /[ \t\f\r\n]+/
    """,
    parser="lalr",
    lexer="basic",
)

AGGREGATE_FUNCTIONS = {
    "AVG",
    "COUNT",
    "COUNTD",
    "MAX",
    "MEDIAN",
    "MIN",
    "PERCENTILE",
    "STDEV",
    "STDEVP",
    "SUM",
    "VAR",
    "VARP",
}
TABLE_CALCULATION_FUNCTIONS = {
    "FIRST",
    "INDEX",
    "LAST",
    "LOOKUP",
    "PREVIOUS_VALUE",
    "RANK",
    "RANK_DENSE",
    "RANK_MODIFIED",
    "RANK_PERCENTILE",
    "RANK_UNIQUE",
    "RUNNING_AVG",
    "RUNNING_COUNT",
    "RUNNING_MAX",
    "RUNNING_MIN",
    "RUNNING_SUM",
    "SIZE",
    "TOTAL",
    "WINDOW_AVG",
    "WINDOW_CORR",
    "WINDOW_COUNT",
    "WINDOW_COVAR",
    "WINDOW_COVARP",
    "WINDOW_MAX",
    "WINDOW_MEDIAN",
    "WINDOW_MIN",
    "WINDOW_PERCENTILE",
    "WINDOW_STDEV",
    "WINDOW_STDEVP",
    "WINDOW_SUM",
    "WINDOW_VAR",
    "WINDOW_VARP",
}
NUMERIC_TYPES = {"decimal", "integer", "number", "real"}
MEASURE_AGGREGATIONS = {
    "average": "AVG",
    "avg": "AVG",
    "count": "COUNT",
    "countd": "COUNT_DISTINCT",
    "max": "MAX",
    "min": "MIN",
    "sum": "SUM",
}


@dataclass(frozen=True)
class FormulaReference:
    raw: str
    field_name: str
    qualifier: str | None


def _clean_name(value: str) -> str:
    if value.startswith("[") and value.endswith("]"):
        return value[1:-1]
    return value


def _lookup_key(value: str | None) -> str:
    return _clean_name(value or "").casefold()


def tokenize_formula(formula: str) -> list[Token]:
    return list(FORMULA_LEXER.lex(formula or ""))


def formula_references(formula: str) -> list[FormulaReference]:
    tokens = tokenize_formula(formula)
    references: list[FormulaReference] = []
    position = 0
    while position < len(tokens):
        token = tokens[position]
        if token.type != "FIELD_REF":
            position += 1
            continue
        qualifier = None
        field_token = token
        if (
            position + 2 < len(tokens)
            and tokens[position + 1].type == "SYMBOL"
            and str(tokens[position + 1]) == "."
            and tokens[position + 2].type == "FIELD_REF"
        ):
            qualifier = _clean_name(str(token))
            field_token = tokens[position + 2]
            position += 2
        references.append(
            FormulaReference(
                raw=(f"{token}.{field_token}" if qualifier else str(field_token)),
                field_name=_clean_name(str(field_token)),
                qualifier=qualifier,
            )
        )
        position += 1
    return references


def formula_functions(formula: str) -> list[str]:
    tokens = tokenize_formula(formula)
    functions = []
    for position, token in enumerate(tokens[:-1]):
        if token.type != "WORD" or tokens[position + 1].type != "SYMBOL" or str(tokens[position + 1]) != "(":
            continue
        name = str(token).upper()
        if name not in functions:
            functions.append(name)
    return functions


def classify_formula(formula: str) -> dict[str, Any]:
    functions = formula_functions(formula)
    table_functions = [name for name in functions if name in TABLE_CALCULATION_FUNCTIONS]
    aggregate_functions = [name for name in functions if name in AGGREGATE_FUNCTIONS]
    lod_match = re.search(r"\{\s*(FIXED|INCLUDE|EXCLUDE)\b", formula or "", flags=re.IGNORECASE)
    if table_functions:
        semantic_type = "TABLE_CALCULATION"
    elif lod_match:
        semantic_type = f"LOD_{lod_match.group(1).upper()}"
    elif aggregate_functions:
        semantic_type = "AGGREGATE"
    else:
        semantic_type = "ROW_LEVEL"
    return {
        "semantic_type": semantic_type,
        "functions": functions,
        "aggregate_functions": aggregate_functions,
        "table_calculation_functions": table_functions,
        "lod_type": lod_match.group(1).upper() if lod_match else None,
    }


def _name_map(items: list[dict[str, Any]], id_key: str) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for item in items:
        for value in (item.get(id_key), item.get("name")):
            if value:
                lookup[_lookup_key(value)] = item
    return lookup


def resolve_formula_dependencies(datasource_ir: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    calculations = datasource_ir["calculations"]
    calculation_lookup = _name_map(calculations, "calculation_id")
    field_lookup = _name_map(datasource_ir["fields"], "field_id")
    parameter_lookup = _name_map(datasource_ir["parameters"], "parameter_id")
    relation_names = {
        _lookup_key(relation.get("name")) for relation in datasource_ir["relations"] if relation.get("name")
    }
    resolved: dict[str, list[dict[str, Any]]] = {}
    for calculation in calculations:
        dependencies = []
        seen = set()
        for reference in formula_references(calculation.get("formula") or ""):
            reference_key = _lookup_key(reference.field_name)
            qualifier_key = _lookup_key(reference.qualifier)
            if qualifier_key == "parameters":
                target = parameter_lookup.get(reference_key)
                kind = "parameter" if target else "unresolved"
                target_id = target.get("parameter_id") if target else reference.field_name
            elif reference.qualifier and qualifier_key not in relation_names:
                kind = "external_field"
                target_id = reference.field_name
            elif reference_key in calculation_lookup:
                kind = "calculation"
                target_id = calculation_lookup[reference_key]["calculation_id"]
            elif reference_key in parameter_lookup:
                kind = "parameter"
                target_id = parameter_lookup[reference_key]["parameter_id"]
            elif reference_key in field_lookup:
                kind = "field"
                target_id = field_lookup[reference_key]["field_id"]
            else:
                kind = "unresolved"
                target_id = reference.field_name
            identity = (kind, target_id, reference.qualifier)
            if identity in seen:
                continue
            seen.add(identity)
            dependencies.append(
                {
                    "kind": kind,
                    "target_id": target_id,
                    "target_name": (
                        calculation_lookup[reference_key].get("name")
                        if kind == "calculation"
                        else reference.field_name
                    ),
                    "qualifier": reference.qualifier,
                    "source_reference": reference.raw,
                }
            )
        resolved[calculation["calculation_id"]] = dependencies
    return resolved


def _calculation_graph(
    calculations: list[dict[str, Any]],
    dependencies: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    calculation_ids = {item["calculation_id"] for item in calculations}
    names = {item["calculation_id"]: item.get("name") or item["calculation_id"] for item in calculations}
    direct_dependencies = {
        calculation_id: {
            dependency["target_id"]
            for dependency in dependencies[calculation_id]
            if dependency["kind"] == "calculation" and dependency["target_id"] in calculation_ids
        }
        for calculation_id in calculation_ids
    }
    dependents: dict[str, set[str]] = defaultdict(set)
    indegree = {calculation_id: len(items) for calculation_id, items in direct_dependencies.items()}
    for calculation_id, items in direct_dependencies.items():
        for dependency in items:
            dependents[dependency].add(calculation_id)
    ready = sorted((item for item, count in indegree.items() if count == 0), key=lambda item: names[item].casefold())
    order = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for dependent in sorted(dependents[current], key=lambda item: names[item].casefold()):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort(key=lambda item: names[item].casefold())
    cyclic_nodes = sorted((item for item in calculation_ids if item not in order), key=lambda item: names[item].casefold())
    return {
        "nodes": [
            {"calculation_id": item["calculation_id"], "name": item.get("name")}
            for item in sorted(calculations, key=lambda item: (item.get("name") or "").casefold())
        ],
        "edges": [
            {"from": calculation_id, "to": dependency}
            for calculation_id in sorted(direct_dependencies, key=lambda item: names[item].casefold())
            for dependency in sorted(direct_dependencies[calculation_id], key=lambda item: names[item].casefold())
        ],
        "topological_order": order,
        "cyclic_nodes": cyclic_nodes,
    }


def _stable_id(prefix: str, datasource_id: str, source_id: str) -> str:
    digest = hashlib.sha256(f"{datasource_id}\0{prefix}\0{source_id}".encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:20]}"


def _unit_from_format(format_value: str | None) -> str | None:
    if not format_value:
        return None
    normalized = format_value.casefold()
    if normalized.startswith("p") or "%" in normalized:
        return "percentage"
    if normalized.startswith("c") or "$" in normalized:
        return "currency"
    return "number"


def _base_field_is_measure(field: dict[str, Any]) -> bool:
    if field.get("role") == "dimension":
        return False
    if field.get("role") == "measure":
        return True
    return (
        (field.get("datatype") or "").casefold() in NUMERIC_TYPES
        and (field.get("default_aggregation") or "").casefold() in MEASURE_AGGREGATIONS
    )


def _calculation_status(
    classification: dict[str, Any],
    dependencies: list[dict[str, Any]],
    graph: dict[str, Any],
    calculation_id: str,
    role: str | None,
) -> tuple[str, list[dict[str, Any]]]:
    findings = []
    dependency_kinds = {item["kind"] for item in dependencies}
    if calculation_id in graph["cyclic_nodes"]:
        findings.append({"code": "CALCULATION_CYCLE", "severity": "ERROR"})
        return "BLOCKED_CYCLE", findings
    if "unresolved" in dependency_kinds:
        findings.append({"code": "UNRESOLVED_REFERENCE", "severity": "ERROR"})
        return "UNRESOLVED_DEPENDENCY", findings
    if "external_field" in dependency_kinds:
        findings.append({"code": "EXTERNAL_DATASOURCE_REFERENCE", "severity": "ERROR"})
        return "NEEDS_MAPPING", findings
    if classification["semantic_type"] == "TABLE_CALCULATION":
        findings.append({"code": "TABLE_CALCULATION_UNSUPPORTED", "severity": "WARNING"})
        return "UNSUPPORTED", findings
    if role == "measure" and classification["semantic_type"] == "ROW_LEVEL":
        findings.append({"code": "AGGREGATION_REQUIRES_COMPILATION", "severity": "WARNING"})
        return "NEEDS_AGGREGATION_COMPILATION", findings
    if "parameter" in dependency_kinds:
        return "PARAMETERIZED", findings
    return "READY", findings


def compile_metric_ir(datasource_ir: dict[str, Any]) -> dict[str, Any]:
    dependencies = resolve_formula_dependencies(datasource_ir)
    graph = _calculation_graph(datasource_ir["calculations"], dependencies)
    dimensions = []
    measures = []
    findings = []

    for field in datasource_ir["fields"]:
        if _base_field_is_measure(field):
            aggregation = MEASURE_AGGREGATIONS.get((field.get("default_aggregation") or "sum").casefold(), "SUM")
            measures.append(
                {
                    "measure_id": _stable_id("measure", datasource_ir["datasource_id"], field["field_id"]),
                    "display_name": field["name"],
                    "source_kind": "field",
                    "source_id": field["field_id"],
                    "datatype": field.get("datatype"),
                    "expression": {"kind": "field_aggregate", "field_id": field["field_id"]},
                    "aggregation": aggregation,
                    "grain": field.get("relation_name") or "SOURCE_ROW",
                    "dependencies": [],
                    "unit": _unit_from_format(field.get("format")),
                    "format": field.get("format"),
                    "status": "READY",
                }
            )
        else:
            dimensions.append(
                {
                    "dimension_id": _stable_id("dimension", datasource_ir["datasource_id"], field["field_id"]),
                    "display_name": field["name"],
                    "source_kind": "field",
                    "source_id": field["field_id"],
                    "datatype": field.get("datatype"),
                    "expression": {"kind": "field", "field_id": field["field_id"]},
                    "relation_name": field.get("relation_name"),
                    "semantic_role": field.get("semantic_role"),
                    "format": field.get("format"),
                    "hidden": field.get("hidden"),
                    "status": "READY",
                }
            )

    for calculation in datasource_ir["calculations"]:
        calculation_id = calculation["calculation_id"]
        classification = classify_formula(calculation.get("formula") or "")
        calculation_dependencies = dependencies[calculation_id]
        status, calculation_findings = _calculation_status(
            classification,
            calculation_dependencies,
            graph,
            calculation_id,
            calculation.get("role"),
        )
        for finding in calculation_findings:
            findings.append(
                {
                    **finding,
                    "calculation_id": calculation_id,
                    "calculation_name": calculation.get("name"),
                    "message": {
                        "CALCULATION_CYCLE": "Calculation participates in a dependency cycle",
                        "UNRESOLVED_REFERENCE": "Formula contains an unresolved field or calculation reference",
                        "EXTERNAL_DATASOURCE_REFERENCE": "Formula references a field from another datasource",
                        "TABLE_CALCULATION_UNSUPPORTED": "Table calculations require visualization partition semantics",
                        "AGGREGATION_REQUIRES_COMPILATION": "Row-level measure requires an explicit target aggregation",
                    }[finding["code"]],
                }
            )
        expression = {
            "kind": "tableau_calculation",
            "formula": calculation.get("formula"),
            "classification": classification,
        }
        if calculation.get("role") == "dimension":
            dimensions.append(
                {
                    "dimension_id": _stable_id("dimension", datasource_ir["datasource_id"], calculation_id),
                    "display_name": calculation.get("name"),
                    "source_kind": "calculation",
                    "source_id": calculation_id,
                    "datatype": calculation.get("datatype"),
                    "expression": expression,
                    "dependencies": calculation_dependencies,
                    "semantic_role": calculation.get("semantic_role"),
                    "format": calculation.get("format"),
                    "hidden": calculation.get("hidden"),
                    "status": status,
                }
            )
        else:
            semantic_type = classification["semantic_type"]
            if semantic_type == "TABLE_CALCULATION":
                aggregation = "TABLE_CALCULATION"
                grain = "VISUAL_PARTITION"
            elif semantic_type.startswith("LOD_"):
                aggregation = semantic_type
                grain = semantic_type
            elif semantic_type == "AGGREGATE":
                aggregation = "FORMULA"
                grain = "QUERY_GRAIN"
            else:
                aggregation = "SOURCE_DEFAULT"
                grain = "SOURCE_ROW"
            measures.append(
                {
                    "measure_id": _stable_id("measure", datasource_ir["datasource_id"], calculation_id),
                    "display_name": calculation.get("name"),
                    "source_kind": "calculation",
                    "source_id": calculation_id,
                    "datatype": calculation.get("datatype"),
                    "expression": expression,
                    "aggregation": aggregation,
                    "grain": grain,
                    "dependencies": calculation_dependencies,
                    "unit": _unit_from_format(calculation.get("format")),
                    "format": calculation.get("format"),
                    "status": status,
                }
            )

    dimensions.sort(key=lambda item: (item["display_name"] or "").casefold())
    measures.sort(key=lambda item: (item["display_name"] or "").casefold())
    findings.sort(key=lambda item: ((item.get("calculation_name") or "").casefold(), item["code"]))
    return {
        "schema_version": "1.0",
        "workflow_run_id": datasource_ir["workflow_run_id"],
        "datasource_id": datasource_ir["datasource_id"],
        "datasource_name": datasource_ir["datasource_name"],
        "source_path": datasource_ir["source_path"],
        "document_path": datasource_ir["document_path"],
        "dimensions": dimensions,
        "measures": measures,
        "parameters": datasource_ir["parameters"],
        "calculation_graph": graph,
        "findings": findings,
        "provenance": {
            "generator": {"name": "datasource-semantic-migration", "version": __version__},
            "source_ir_sha256": None,
            "source_package_hash": datasource_ir["package_hash"],
        },
    }


def write_metric_ir_result(
    *,
    datasource_ir_index: dict[str, Any],
    datasource_index: int,
    metric_ir_root: str | Path,
) -> dict[str, Any]:
    try:
        datasource_entry = datasource_ir_index["datasources"][datasource_index]
    except (IndexError, TypeError) as error:
        raise ValueError(f"Datasource index is outside the IR index: {datasource_index}") from error
    result = write_metric_ir_for_datasource_entry(
        datasource_entry=datasource_entry,
        metric_ir_root=metric_ir_root,
    )
    result["datasource_index"] = datasource_index
    write_json_artifact(
        result,
        Path(metric_ir_root) / "assets" / result["datasource_id"] / "compile-result.json",
    )
    return result


def write_metric_ir_for_datasource_entry(
    *,
    datasource_entry: dict[str, Any],
    metric_ir_root: str | Path,
) -> dict[str, Any]:
    source_ir_path = Path(datasource_entry["output_path"])
    if not source_ir_path.is_file():
        raise FileNotFoundError(f"Datasource IR does not exist: {source_ir_path}")
    datasource_ir = json.loads(source_ir_path.read_text(encoding="utf-8"))
    metric_ir = compile_metric_ir(datasource_ir)
    metric_ir["provenance"]["source_ir_sha256"] = sha256_file(source_ir_path)
    output_path = write_json_artifact(
        metric_ir,
        Path(metric_ir_root) / "assets" / metric_ir["datasource_id"] / "metric-ir.json",
    )
    status_counts: dict[str, int] = defaultdict(int)
    for item in [*metric_ir["dimensions"], *metric_ir["measures"]]:
        status_counts[item["status"]] += 1
    result = {
        "schema_version": "1.0",
        "workflow_run_id": metric_ir["workflow_run_id"],
        "datasource_id": metric_ir["datasource_id"],
        "datasource_name": metric_ir["datasource_name"],
        "output_path": output_path.as_posix(),
        "metric_ir_sha256": sha256_file(output_path),
        "dimension_count": len(metric_ir["dimensions"]),
        "measure_count": len(metric_ir["measures"]),
        "parameter_count": len(metric_ir["parameters"]),
        "finding_count": len(metric_ir["findings"]),
        "status_counts": dict(sorted(status_counts.items())),
    }
    write_json_artifact(result, Path(metric_ir_root) / "assets" / metric_ir["datasource_id"] / "compile-result.json")
    return result


def consolidate_metric_ir_index(
    *,
    datasource_ir_index: dict[str, Any],
    datasource_ir_index_path: str,
    metric_ir_root: str | Path,
) -> dict[str, Any]:
    entries = []
    compile_results = []
    for datasource in datasource_ir_index["datasources"]:
        result_path = Path(metric_ir_root) / "assets" / datasource["datasource_id"] / "compile-result.json"
        if not result_path.is_file():
            raise FileNotFoundError(f"Metric IR compile result does not exist: {result_path}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        entries.append(result)
        compile_results.append(result_path.as_posix())
    entries.sort(key=lambda item: (item["datasource_name"] or "").casefold())
    combined_status_counts: dict[str, int] = defaultdict(int)
    for entry in entries:
        for status, count in entry["status_counts"].items():
            combined_status_counts[status] += count
    return {
        "schema_version": "1.0",
        "workflow_run_id": datasource_ir_index["workflow_run_id"],
        "created_at": datasource_ir_index["created_at"],
        "datasource_ir_index_path": datasource_ir_index_path,
        "metric_ir_root": Path(metric_ir_root).as_posix(),
        "status": "COMPLETE",
        "summary": {
            "datasource_count": len(entries),
            "dimension_count": sum(item["dimension_count"] for item in entries),
            "measure_count": sum(item["measure_count"] for item in entries),
            "parameter_count": sum(item["parameter_count"] for item in entries),
            "finding_count": sum(item["finding_count"] for item in entries),
            "status_counts": dict(sorted(combined_status_counts.items())),
        },
        "datasources": entries,
        "compile_results": compile_results,
        "provenance": {
            "generator": {"name": "datasource-semantic-migration", "version": __version__}
        },
    }
