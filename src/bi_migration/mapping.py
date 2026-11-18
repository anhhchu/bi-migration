from __future__ import annotations

import csv
import copy
import re
from difflib import SequenceMatcher
from pathlib import Path

import yaml


class _MappingDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower().strip("[]"))


def _is_workbook_helper(source: dict) -> bool:
    return bool(
        re.fullmatch(r"clipboard_\d{8}t\d+", source.get("datasource", ""), re.IGNORECASE)
        or source.get("datasource") == "Parameters"
        or source.get("datatype") == "table"
        or source.get("workbook_object")
        or source.get("source_kind") in {"extract_replica", "dashboard_object", "workbook_helper"}
    )


def source_fields(assets: list[dict]) -> list[dict]:
    fields: dict[tuple[str, str], dict] = {}
    for asset in assets:
        for datasource in asset.get("datasources", []):
            for field in datasource.get("fields", []):
                name = field.get("caption") or field.get("name")
                if not name:
                    continue
                key = (datasource["id"], name)
                fields.setdefault(
                    key,
                    {
                        "datasource": datasource["id"],
                        "legacy": name,
                        "datatype": field.get("datatype", ""),
                        "calculation": field.get("calculation"),
                        "source_table": field.get("source_table", ""),
                        "workbook_object": field.get("workbook_object", False),
                        "source_kind": field.get("source_kind", "business_source"),
                        "assets": set(),
                    },
                )["assets"].add(asset["asset_id"])
    for field in fields.values():
        field["assets"] = sorted(field["assets"])
    return sorted(fields.values(), key=lambda item: (item["datasource"], item["legacy"]))


def _target_columns(target_metadata: dict) -> list[dict]:
    columns = []
    for table in target_metadata.get("tables", []):
        table_name = table["name"]
        for column in table.get("columns", []):
            columns.append({**column, "table": table_name, "grain": table.get("grain", "")})
    return columns


def _best_match(source: dict, targets: list[dict]) -> dict:
    source_name = _normalize(source["legacy"])
    ranked = []
    for target in targets:
        names = [target["name"], *target.get("synonyms", [])]
        score = max(SequenceMatcher(None, source_name, _normalize(name)).ratio() for name in names)
        evidence = []
        if any(source_name == _normalize(name) for name in names):
            score = 1.0
            evidence.append("normalized_name_match")
        if source.get("datatype") and target.get("type") and source["datatype"].lower() in target["type"].lower():
            score = min(1.0, score + 0.05)
            evidence.append("compatible_type")
        ranked.append((score, target, evidence))
    if not ranked:
        return {"confidence": 0.0, "status": "unresolved", "evidence": ["no_target_columns"]}
    score, target, evidence = max(ranked, key=lambda item: item[0])
    return {
        "target_table": target["table"],
        "target_expression": target["name"],
        "target_grain": target.get("grain", ""),
        "confidence": round(score, 3),
        "status": "proposed" if score >= 0.92 else "unresolved",
        "evidence": evidence or ["name_similarity"],
    }


def _table_key(value: str) -> str:
    return _normalize(value.split(".")[-1])


def _target_tables_for_source(source_table: str, fields: list[dict]) -> list[str]:
    key = _table_key(source_table)
    return sorted(
        {
            field["target_table"]
            for field in fields
            if field.get("target_table") and _table_key(field.get("source_table", "")) == key
        }
    )


def _translate_join_condition(condition: str, fields: list[dict]) -> str:
    translated = condition
    candidates = sorted(
        (
            (field.get("legacy", ""), field.get("target_expression", ""))
            for field in fields
            if field.get("legacy") and field.get("target_expression")
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for legacy, target in candidates:
        translated = re.sub(rf"\[{re.escape(legacy.strip('[]'))}\]", target, translated, flags=re.IGNORECASE)
    return translated


def refresh_relationship_proposals(mapping: dict) -> dict:
    fields = mapping.get("fields", [])
    for relationship in mapping.get("relationships", []):
        left_targets = _target_tables_for_source(relationship["source"]["left_table"], fields)
        right_targets = _target_tables_for_source(relationship["source"]["right_table"], fields)
        relationship["target"] = {
            "left_table_candidates": left_targets,
            "right_table_candidates": right_targets,
            "join_type": relationship["source"].get("join_type", "inner"),
            "condition": _translate_join_condition(relationship["source"].get("condition", ""), fields),
            "cardinality": relationship.get("target", {}).get("cardinality", "unknown"),
            "temporal_predicates": relationship.get("target", {}).get("temporal_predicates", []),
            "record_filters": relationship.get("target", {}).get("record_filters", []),
        }
        unambiguous = len(left_targets) == 1 and len(right_targets) == 1
        relationship["confidence"] = 0.9 if unambiguous else 0.0
        relationship["status"] = "proposed" if unambiguous else "unresolved"
        relationship["evidence"] = [
            "tableau_relationship",
            "field_mapping_table_lineage" if unambiguous else "target_tables_ambiguous",
        ]
    return mapping


def _source_relationships(assets: list[dict]) -> list[dict]:
    relationships: dict[tuple, dict] = {}
    for asset in assets:
        for datasource in asset.get("datasources", []):
            for source in datasource.get("relationships", []):
                key = (
                    datasource["id"],
                    source.get("left_table", ""),
                    source.get("right_table", ""),
                    source.get("join_type", ""),
                    source.get("condition", ""),
                )
                item = relationships.setdefault(
                    key,
                    {
                        "datasource": datasource["id"],
                        "source": source,
                        "assets": set(),
                        "target": {},
                    },
                )
                item["assets"].add(asset["asset_id"])
    result = []
    for item in relationships.values():
        item["assets"] = sorted(item["assets"])
        result.append(item)
    return result


def draft_mapping(assets: list[dict], target_metadata: dict, domain: str) -> tuple[dict, list[dict], list[dict]]:
    targets = _target_columns(target_metadata)
    proposals = []
    physical_fields: dict[tuple[str, str], dict] = {}
    calculation_catalog: dict[tuple[str, str], dict] = {}
    workbook_helpers: dict[tuple[str, str], dict] = {}
    for source in source_fields(assets):
        if _is_workbook_helper(source):
            helper_key = (_normalize(source["legacy"]), source.get("datatype", ""))
            helper = workbook_helpers.setdefault(
                helper_key,
                {
                    "name": source["legacy"],
                    "kind": "workbook_helper",
                    "assets": set(),
                    "datasources": set(),
                },
            )
            helper["assets"].update(source["assets"])
            helper["datasources"].add(source["datasource"])
            continue
        if source.get("calculation"):
            calculation_key = (re.sub(r"\s+", " ", source["calculation"].strip()), source.get("datatype", ""))
            existing = calculation_catalog.setdefault(
                calculation_key,
                {
                    "legacy_name": source["legacy"],
                    "legacy_expression": source["calculation"],
                    "assets": set(),
                    "aliases": set(),
                    "status": "candidate",
                },
            )
            existing["assets"].update(source["assets"])
            existing["aliases"].add(source["legacy"])
            continue
        field_key = (_normalize(source["legacy"]), source.get("datatype", ""))
        existing = physical_fields.setdefault(
            field_key,
            {**source, "assets": set(), "datasources": set(), "aliases": set()},
        )
        existing["assets"].update(source["assets"])
        existing["datasources"].add(source["datasource"])
        existing["aliases"].add(source["legacy"])
        if source.get("source_table") and not existing.get("source_table"):
            existing["source_table"] = source["source_table"]

    for source in physical_fields.values():
        source["assets"] = sorted(source["assets"])
        source["datasources"] = sorted(source["datasources"])
        source["aliases"] = sorted(source["aliases"])
        proposal = {**source, **_best_match(source, targets)}
        proposals.append(proposal)
    kpis = []
    for item in calculation_catalog.values():
        item["assets"] = sorted(item["assets"])
        item["aliases"] = sorted(item["aliases"])
        kpis.append(item)
    kpis.sort(key=lambda item: item["legacy_name"])
    helpers = []
    for item in workbook_helpers.values():
        item["assets"] = sorted(item["assets"])
        item["datasources"] = sorted(item["datasources"])
        helpers.append(item)
    helpers.sort(key=lambda item: item["name"])
    mapping = {
        "mapping_version": "0.2.0",
        "domain": domain,
        "status": "proposed",
        "sources": sorted({asset["asset_id"] for asset in assets}),
        "fields": proposals,
        "relationships": _source_relationships(assets),
        "kpis": kpis,
        "workbook_helpers": helpers,
    }
    refresh_relationship_proposals(mapping)
    unresolved = [proposal for proposal in proposals if proposal["status"] == "unresolved"]
    return mapping, unresolved, kpis


def apply_mapping_evidence(mapping: dict, evidence: list[dict]) -> tuple[dict, list[dict]]:
    compiled = copy.deepcopy(mapping)
    conflicts = []
    for field in compiled.get("fields", []):
        matches = [
            item
            for item in evidence
            if _normalize(item.get("legacy", "")) == _normalize(field.get("legacy", ""))
            and (
                not item.get("source_table")
                or _normalize(item["source_table"]) == _normalize(field.get("source_table", ""))
            )
            and (
                not item.get("datasource")
                or _normalize(item["datasource"]) == _normalize(field.get("datasource", ""))
                or any(
                    _normalize(item["datasource"]) == _normalize(datasource)
                    for datasource in field.get("datasources", [])
                )
            )
        ]
        if not matches:
            continue
        targets = {
            (item.get("target_table", ""), item.get("target_expression", ""))
            for item in matches
            if item.get("target_table") or item.get("target_expression")
        }
        if len(targets) > 1:
            field["status"] = "unresolved"
            field["confidence"] = 0.0
            field["evidence"] = ["conflicting_mapping_documents"]
            conflict = {
                "datasource": field.get("datasource"),
                "legacy": field.get("legacy"),
                "candidates": matches,
            }
            conflicts.append(conflict)
            continue
        selected = matches[0]
        field["mapping_document"] = {
            key: selected[key]
            for key in ("source_table", "source_grain", "target_grain", "conversion", "status", "notes")
            if selected.get(key)
        }
        document_evidence = [
            f"mapping_document:{item['provenance']['file']}:{item['provenance']['locator']}"
            for item in matches
        ]
        if not targets:
            field["status"] = "unresolved"
            field["confidence"] = 0.0
            field["evidence"] = document_evidence
            continue
        if selected.get("target_table"):
            field["target_table"] = selected["target_table"]
        if selected.get("target_expression"):
            field["target_expression"] = selected["target_expression"]
        field["conversion"] = selected.get("conversion", field.get("conversion", "documented"))
        field["source_grain"] = selected.get("source_grain", "")
        field["target_grain"] = selected.get("target_grain", "")
        field["confidence"] = 1.0
        field["status"] = "proposed"
        field["evidence"] = document_evidence
        if selected.get("status"):
            field["document_status"] = selected["status"]
    compiled = refresh_relationship_proposals(compiled)
    for item in (entry for entry in evidence if entry.get("evidence_type") == "relationship"):
        left_table = item.get("target_left_table")
        right_table = item.get("target_right_table")
        if not left_table or not right_table:
            continue
        source_key = item.get("source_key", "")
        target_key = item.get("target_key", "")
        left_key = next(
            (
                field.get("target_expression")
                for field in compiled.get("fields", [])
                if _normalize(field.get("legacy", "")) == _normalize(source_key)
                and field.get("target_table") == left_table
            ),
            source_key,
        )
        as_of_expression = next(
            (
                field.get("target_expression")
                for field in compiled.get("fields", [])
                if _normalize(field.get("legacy", "")) == _normalize(item.get("as_of", ""))
                and field.get("target_table") == left_table
            ),
            item.get("as_of", ""),
        )
        temporal_predicates = []
        if item.get("as_of") and item.get("temporal_mode") in {"bitemporal", "valid_time", "scd2"}:
            temporal_predicates = [
                f"{left_table}.{as_of_expression} >= {right_table}.business_valid_from",
                f"{left_table}.{as_of_expression} < {right_table}.business_valid_to",
            ]
        record_filters = (
            [f"{right_table}.system_recorded_to IS NULL"]
            if item.get("temporal_mode") == "bitemporal"
            else []
        )
        relationship = {
            "datasource": "mapping_document",
            "source": {
                "left_table": item.get("source_table", ""),
                "right_table": item.get("source_table", ""),
                "join_type": item.get("join_type", "left"),
                "condition": source_key,
                "source_kind": "target_decomposition",
            },
            "target": {
                "left_table_candidates": [left_table],
                "right_table_candidates": [right_table],
                "join_type": item.get("join_type", "left"),
                "condition": f"{left_table}.{left_key} = {right_table}.{target_key}",
                "cardinality": item.get("cardinality", "unknown"),
                "temporal_predicates": temporal_predicates,
                "record_filters": record_filters,
            },
            "assets": compiled.get("sources", []),
            "confidence": 1.0,
            "status": "proposed",
            "evidence": [
                f"mapping_document:{item['provenance']['file']}:{item['provenance']['locator']}"
            ],
        }
        duplicates = [
            existing
            for existing in compiled.get("relationships", [])
            if (
                existing.get("target", {}).get("left_table_candidates") == [left_table]
                and existing.get("target", {}).get("right_table_candidates") == [right_table]
            )
            or (
                _table_key(existing.get("source", {}).get("right_table", ""))
                == _table_key(item.get("source_table", ""))
            )
        ]
        if duplicates:
            for duplicate in duplicates:
                source = duplicate.get("source", relationship["source"])
                assets = duplicate.get("assets", relationship["assets"])
                duplicate.update(relationship)
                duplicate["source"] = source
                duplicate["assets"] = assets
                duplicate["evidence"] = [
                    "tableau_relationship",
                    *relationship["evidence"],
                ]
        else:
            compiled.setdefault("relationships", []).append(relationship)
    return compiled, conflicts


def write_mapping_outputs(mapping: dict, unresolved: list[dict], kpis: list[dict], output: Path) -> None:
    mapping_directory = output / "mappings" / "domains"
    report_directory = output / "reports"
    mapping_directory.mkdir(parents=True, exist_ok=True)
    report_directory.mkdir(parents=True, exist_ok=True)
    mapping_path = mapping_directory / f"{mapping['domain']}.yaml"
    mapping_path.write_text(yaml.dump(mapping, Dumper=_MappingDumper, sort_keys=False), encoding="utf-8")

    with (report_directory / "unresolved_mappings.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["datasource", "legacy", "assets", "confidence", "evidence"])
        writer.writeheader()
        for item in unresolved:
            writer.writerow({key: item.get(key) for key in writer.fieldnames})

    with (report_directory / "kpi_candidates.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["legacy_name", "legacy_expression", "assets", "aliases", "status"],
        )
        writer.writeheader()
        for item in kpis:
            writer.writerow(
                {
                    **item,
                    "assets": "|".join(item.get("assets", [])),
                    "aliases": "|".join(item.get("aliases", [])),
                }
            )
