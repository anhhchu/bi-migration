from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .tableau_parser import write_json_artifact


FEATURE_WEIGHTS = {
    "relations": 0.35,
    "calculations": 0.30,
    "fields": 0.20,
    "connections": 0.10,
    "metadata": 0.05,
}


def _normalized(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _relation_name(value: str | None) -> str:
    normalized = (value or "").strip().strip("'\"")
    bracketed_parts = re.findall(r"\[([^\]]+)\]", normalized)
    if bracketed_parts:
        normalized = bracketed_parts[-1]
    else:
        file_suffixes = (".csv", ".hyper", ".json", ".parquet", ".tde", ".txt", ".xls", ".xlsx")
        if "." in normalized and not normalized.casefold().endswith(file_suffixes):
            normalized = normalized.split(".")[-1]
    normalized = re.sub(r"#(csv|txt|xls|xlsx)$", r".\1", normalized, flags=re.IGNORECASE)
    if normalized.endswith("$"):
        normalized = normalized[:-1]
    return _normalized(normalized)


def _slug(value: str, maximum_length: int = 36) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:maximum_length].rstrip("-") or "semantic-group"


def load_table_mapping(path: str | Path) -> dict[str, Any]:
    mapping_path = Path(path)
    if not mapping_path.is_file():
        raise FileNotFoundError(f"Table mapping does not exist: {mapping_path}")
    if mapping_path.suffix.casefold() not in {".yaml", ".yml"}:
        raise ValueError("End-to-end migration currently requires a YAML table mapping")
    document = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    if document.get("version") != "1.0" or not document.get("table_mappings"):
        raise ValueError("Table mapping must contain version '1.0' and at least one table_mappings entry")
    return document


def semantic_features(datasource_ir: dict[str, Any], metric_ir: dict[str, Any]) -> dict[str, set[str]]:
    return {
        "relations": {
            f"{_relation_name(item.get('name'))}|{_normalized(item.get('relation_type'))}"
            for item in datasource_ir["relations"]
        },
        "calculations": {
            hashlib.sha256(_normalized(item.get("formula")).encode("utf-8")).hexdigest()
            for item in datasource_ir["calculations"]
        },
        "fields": {
            f"{_normalized(item.get('name'))}|{_normalized(item.get('datatype'))}"
            for item in datasource_ir["fields"]
        },
        "connections": {_normalized(item.get("class")) for item in datasource_ir["connections"]},
        "metadata": {
            *(_normalized(item.get("name")) for item in datasource_ir["metadata"].get("groups", [])),
            *(_normalized(item.get("name")) for item in datasource_ir["metadata"].get("drill_paths", [])),
            *(f"measure:{_normalized(item.get('display_name'))}" for item in metric_ir["measures"]),
        },
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def semantic_similarity(left: dict[str, set[str]], right: dict[str, set[str]]) -> tuple[float, dict[str, float]]:
    components = {name: _jaccard(left[name], right[name]) for name in FEATURE_WEIGHTS}
    score = sum(FEATURE_WEIGHTS[name] * value for name, value in components.items())
    return score, components


def _mapping_targets(mapping: dict[str, Any], datasource_ir: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    relation_names = {
        _relation_name(relation.get("name")) for relation in datasource_ir["relations"] if relation.get("name")
    }
    relation_names.update(
        _relation_name(relation.get("table")) for relation in datasource_ir["relations"] if relation.get("table")
    )
    datasource_name = _normalized(datasource_ir.get("datasource_name"))
    selected = []
    for entry in mapping["table_mappings"]:
        source = entry.get("source", {})
        if _relation_name(source.get("table")) not in relation_names:
            continue
        datasource_hint = source.get("datasource")
        if datasource_hint and _normalized(datasource_hint) != datasource_name:
            continue
        selected.append(entry)
    targets = sorted({entry["target"]["table"] for entry in selected})
    return selected, targets


def _semantic_assets(
    *,
    datasource_ir_index: dict[str, Any],
    metric_ir_index: dict[str, Any],
    mapping: dict[str, Any],
) -> list[dict[str, Any]]:
    datasource_entries = {item["datasource_id"]: item for item in datasource_ir_index["datasources"]}
    metric_entries = {item["datasource_id"]: item for item in metric_ir_index["datasources"]}
    semantic_assets = []
    for datasource_id in sorted(datasource_entries):
        datasource_entry = datasource_entries[datasource_id]
        metric_entry = metric_entries[datasource_id]
        datasource_ir = json.loads(Path(datasource_entry["output_path"]).read_text(encoding="utf-8"))
        metric_ir = json.loads(Path(metric_entry["output_path"]).read_text(encoding="utf-8"))
        selected_mapping, targets = _mapping_targets(mapping, datasource_ir)
        semantic_assets.append(
            {
                "datasource_id": datasource_id,
                "datasource_name": datasource_ir["datasource_name"],
                "source_path": datasource_ir["source_path"],
                "document_path": datasource_ir["document_path"],
                "datasource_ir_path": datasource_entry["output_path"],
                "metric_ir_path": metric_entry["output_path"],
                "features": semantic_features(datasource_ir, metric_ir),
                "mapping_entries": selected_mapping,
                "target_tables": targets,
                "target_schemas": sorted({table.split(".")[1] for table in targets}),
                "source_databases": sorted(
                    {entry["source"]["database"] for entry in selected_mapping if entry["source"].get("database")}
                ),
                "business_domains": sorted(
                    {
                        entry["source"]["business_domain"]
                        for entry in selected_mapping
                        if entry["source"].get("business_domain")
                    }
                ),
                "mapping_display_names": sorted(
                    {
                        entry["source"]["display_name"]
                        for entry in selected_mapping
                        if entry["source"].get("display_name")
                    }
                ),
                "relations": sorted(
                    {
                        relation_name
                        for relation in datasource_ir["relations"]
                        if (relation_name := _relation_name(relation.get("name") or relation.get("table")))
                    }
                ),
                "fields": sorted(
                    {field.get("name") for field in datasource_ir["fields"] if field.get("name")},
                    key=str.casefold,
                ),
                "calculations": sorted(
                    {item.get("display_name") for item in metric_ir["measures"] if item.get("display_name")},
                    key=str.casefold,
                ),
            }
        )
    return semantic_assets


def _similarity_edges(semantic_assets: list[dict[str, Any]], minimum_score: float = 0.10) -> list[dict[str, Any]]:
    edges = []
    for left_index, left in enumerate(semantic_assets):
        for right in semantic_assets[left_index + 1 :]:
            score, components = semantic_similarity(left["features"], right["features"])
            if score < minimum_score:
                continue
            edges.append(
                {
                    "left_datasource_id": left["datasource_id"],
                    "right_datasource_id": right["datasource_id"],
                    "score": round(score, 6),
                    "components": components,
                }
            )
    return sorted(edges, key=lambda item: (-item["score"], item["left_datasource_id"], item["right_datasource_id"]))


def build_grouping_request(
    *,
    inventory: dict[str, Any],
    datasource_ir_index: dict[str, Any],
    metric_ir_index: dict[str, Any],
    mapping_path: str | Path,
    grouping_result_path: str | Path,
) -> dict[str, Any]:
    mapping = load_table_mapping(mapping_path)
    semantic_assets = _semantic_assets(
        datasource_ir_index=datasource_ir_index,
        metric_ir_index=metric_ir_index,
        mapping=mapping,
    )
    return {
        "schema_version": "1.0",
        "workflow_run_id": inventory["workflow_run_id"],
        "status": "READY_FOR_GENIE",
        "mapping_path": Path(mapping_path).as_posix(),
        "grouping_result_path": Path(grouping_result_path).as_posix(),
        "datasources": [
            {
                key: asset[key]
                for key in (
                    "datasource_id",
                    "datasource_name",
                    "source_path",
                    "document_path",
                    "datasource_ir_path",
                    "metric_ir_path",
                    "source_databases",
                    "business_domains",
                    "mapping_display_names",
                    "relations",
                    "fields",
                    "calculations",
                    "target_tables",
                    "target_schemas",
                )
            }
            for asset in semantic_assets
        ],
        "deterministic_similarity_evidence": _similarity_edges(semantic_assets),
        "rules": {
            "business_datasource_definition": "A datasource with one or more approved target tables",
            "helper_datasource_definition": "A navigation, annotation, clipboard, scaffold, or display-only datasource",
            "required_business_membership": "Every business datasource must be a primary member of exactly one group",
            "required_helper_membership": "Every helper must be attached to one group or classified UI_HELPER",
            "target_compatibility": "Primary members must share a business domain; shared target schema is strong evidence",
            "naming": "Use a concise human-readable business domain name, never an internal Tableau identifier",
        },
    }


def _load_grouping_proposal(path: str | Path) -> dict[str, Any]:
    proposal_path = Path(path)
    if not proposal_path.is_file():
        raise FileNotFoundError(f"Genie semantic grouping proposal does not exist: {proposal_path}")
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    if proposal.get("schema_version") != "1.0" or proposal.get("status") != "COMPLETE":
        raise ValueError("Genie semantic grouping proposal must have schema_version 1.0 and status COMPLETE")
    if not isinstance(proposal.get("groups"), list) or not isinstance(proposal.get("ungrouped_datasources"), list):
        raise ValueError("Genie semantic grouping proposal requires groups and ungrouped_datasources arrays")
    return proposal


def _validate_grouping_proposal(
    proposal: dict[str, Any],
    semantic_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assets = {asset["datasource_id"]: asset for asset in semantic_assets}
    business_ids = {asset_id for asset_id, asset in assets.items() if asset["target_tables"]}
    seen: dict[str, str] = {}
    validated_groups = []
    display_names: set[str] = set()

    for position, group in enumerate(proposal["groups"], start=1):
        display_name = str(group.get("display_name") or "").strip()
        if len(display_name) < 3:
            raise ValueError(f"Grouping proposal group {position} has no readable display_name")
        display_key = display_name.casefold()
        if display_key in display_names:
            raise ValueError(f"Grouping proposal repeats display_name: {display_name}")
        display_names.add(display_key)
        confidence = float(group.get("confidence", 0))
        if confidence < 0.65 or confidence > 1:
            raise ValueError(f"Grouping proposal group {display_name} has invalid or low confidence: {confidence}")
        member_ids = list(dict.fromkeys(group.get("member_datasource_ids") or []))
        helper_ids = list(dict.fromkeys(group.get("helper_datasource_ids") or []))
        if not member_ids:
            raise ValueError(f"Grouping proposal group {display_name} has no primary business datasources")
        unknown_ids = sorted((set(member_ids) | set(helper_ids)) - set(assets))
        if unknown_ids:
            raise ValueError(f"Grouping proposal group {display_name} references unknown datasource IDs: {unknown_ids}")
        non_business = sorted(set(member_ids) - business_ids)
        if non_business:
            raise ValueError(f"Grouping proposal group {display_name} uses helpers as primary members: {non_business}")
        for datasource_id in [*member_ids, *helper_ids]:
            if datasource_id in seen:
                raise ValueError(
                    f"Datasource {datasource_id} appears in both {seen[datasource_id]} and {display_name}"
                )
            seen[datasource_id] = display_name
        target_schema_sets = [set(assets[datasource_id]["target_schemas"]) for datasource_id in member_ids]
        if len(target_schema_sets) > 1 and not set.intersection(*target_schema_sets):
            raise ValueError(f"Grouping proposal group {display_name} combines incompatible target schemas")
        validated_groups.append(
            {
                "display_name": display_name,
                "domain": str(group.get("domain") or display_name).strip(),
                "confidence": confidence,
                "rationale": str(group.get("rationale") or "").strip(),
                "member_datasource_ids": member_ids,
                "helper_datasource_ids": helper_ids,
            }
        )

    for item in proposal["ungrouped_datasources"]:
        datasource_id = item.get("datasource_id")
        if datasource_id not in assets:
            raise ValueError(f"Ungrouped proposal entry references unknown datasource ID: {datasource_id}")
        if datasource_id in seen:
            raise ValueError(f"Datasource {datasource_id} is both grouped and ungrouped")
        classification = item.get("classification")
        if classification != "UI_HELPER":
            raise ValueError(f"Ungrouped datasource {datasource_id} must be classified UI_HELPER")
        seen[datasource_id] = "UI_HELPER"

    missing_business = sorted(business_ids - set(seen))
    if missing_business:
        raise ValueError(f"Grouping proposal omits mapped business datasources: {missing_business}")
    misplaced_business = sorted(business_ids & {item["datasource_id"] for item in proposal["ungrouped_datasources"]})
    if misplaced_business:
        raise ValueError(f"Grouping proposal classifies mapped business datasources as helpers: {misplaced_business}")
    omitted_helpers = sorted(set(assets) - set(seen))
    if omitted_helpers:
        raise ValueError(f"Grouping proposal omits helper datasources: {omitted_helpers}")
    return validated_groups


def build_semantic_groups(
    *,
    inventory: dict[str, Any],
    datasource_ir_index: dict[str, Any],
    metric_ir_index: dict[str, Any],
    mapping_path: str | Path,
    grouping_proposal_path: str | Path,
    run_root: str | Path,
    candidate_catalog: str,
    candidate_schema: str,
) -> dict[str, Any]:
    mapping = load_table_mapping(mapping_path)
    semantic_assets = _semantic_assets(
        datasource_ir_index=datasource_ir_index,
        metric_ir_index=metric_ir_index,
        mapping=mapping,
    )
    proposal = _load_grouping_proposal(grouping_proposal_path)
    proposed_groups = _validate_grouping_proposal(proposal, semantic_assets)
    assets_by_id = {asset["datasource_id"]: asset for asset in semantic_assets}

    run_root_path = Path(run_root)
    group_entries = []
    used_slugs: set[str] = set()
    for proposed_group in sorted(proposed_groups, key=lambda item: item["display_name"].casefold()):
        primary_assets = [assets_by_id[datasource_id] for datasource_id in proposed_group["member_datasource_ids"]]
        helper_assets = [assets_by_id[datasource_id] for datasource_id in proposed_group["helper_datasource_ids"]]
        assets = [*primary_assets, *helper_assets]
        fingerprint_basis = {
            "datasource_ids": sorted(asset["datasource_id"] for asset in primary_assets),
            "target_tables": sorted({target for asset in primary_assets for target in asset["target_tables"]}),
        }
        semantic_hash = hashlib.sha256(
            json.dumps(fingerprint_basis, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        base_slug = _slug(proposed_group["display_name"])
        group_slug = base_slug
        if group_slug in used_slugs:
            group_slug = f"{base_slug[:27]}-{semantic_hash[:8]}"
        used_slugs.add(group_slug)
        group_path = run_root_path / "groups" / group_slug
        group_path.mkdir(parents=True, exist_ok=True)
        group_internal_path = group_path / "_internal"
        group_internal_path.mkdir(parents=True, exist_ok=True)
        group_report_path = run_root_path / "reports" / "groups" / group_slug
        immutable_mapping_path = group_path / "mapping.yaml"
        mapping_subset = {
            "version": "1.0",
            "table_mappings": [
                entry
                for entry in mapping["table_mappings"]
                if entry["target"]["table"] in fingerprint_basis["target_tables"]
            ],
            "relationships": [
                relationship
                for relationship in mapping.get("relationships", [])
                if relationship["left"]["table"] in fingerprint_basis["target_tables"]
                and relationship["right"]["table"] in fingerprint_basis["target_tables"]
            ],
        }
        immutable_mapping_path.write_text(yaml.safe_dump(mapping_subset, sort_keys=False), encoding="utf-8")
        candidate_name = f"bim_{group_slug.replace('-', '_')}_{semantic_hash[:8]}_candidate"
        candidate_fqn = f"{candidate_catalog}.{candidate_schema}.{candidate_name}"
        group_manifest = {
            "schema_version": "1.0",
            "workflow_run_id": inventory["workflow_run_id"],
            "group_id": group_slug,
            "display_name": proposed_group["display_name"],
            "domain": proposed_group["domain"],
            "grouping_confidence": proposed_group["confidence"],
            "grouping_rationale": proposed_group["rationale"],
            "semantic_hash": semantic_hash,
            "group_path": group_path.as_posix(),
            "internal_path": group_internal_path.as_posix(),
            "report_path": group_report_path.as_posix(),
            "candidate_metric_view_fqn": candidate_fqn,
            "mapping_path": immutable_mapping_path.as_posix(),
            "target_tables": fingerprint_basis["target_tables"],
            "datasources": [
                {key: asset[key] for key in ("datasource_id", "datasource_name", "source_path", "document_path", "datasource_ir_path", "metric_ir_path")}
                for asset in primary_assets
            ],
            "supporting_datasources": [
                {key: asset[key] for key in ("datasource_id", "datasource_name", "source_path", "document_path", "datasource_ir_path", "metric_ir_path")}
                for asset in helper_assets
            ],
            "status": "READY_FOR_PREFLIGHT",
            "provenance": {"generator": {"name": "datasource-semantic-migration", "version": __version__}},
        }
        source_summary = {
            "schema_version": "1.0",
            "workflow_run_id": inventory["workflow_run_id"],
            "group_id": group_slug,
            "display_name": proposed_group["display_name"],
            "domain": proposed_group["domain"],
            "grouping_confidence": proposed_group["confidence"],
            "grouping_rationale": proposed_group["rationale"],
            "semantic_hash": semantic_hash,
            "datasource_count": len(primary_assets),
            "supporting_datasource_count": len(helper_assets),
            "datasources": [
                {
                    "datasource_id": asset["datasource_id"],
                    "datasource_name": asset["datasource_name"],
                    "source_path": asset["source_path"],
                    "relation_count": len(asset["features"]["relations"]),
                    "calculation_count": len(asset["features"]["calculations"]),
                    "field_count": len(asset["features"]["fields"]),
                }
                for asset in primary_assets
            ],
            "supporting_datasources": [
                {
                    "datasource_id": asset["datasource_id"],
                    "datasource_name": asset["datasource_name"],
                    "source_path": asset["source_path"],
                }
                for asset in helper_assets
            ],
            "target_tables": fingerprint_basis["target_tables"],
            "grouping_basis": "Genie Code semantic proposal validated against deterministic mapping and membership rules",
        }
        source_summary_path = write_json_artifact(source_summary, group_internal_path / "source-summary.json")
        group_manifest_path = write_json_artifact(group_manifest, group_internal_path / "group-manifest.json")
        group_entries.append(
            {
                "group_id": group_slug,
                "display_name": proposed_group["display_name"],
                "group_path": group_path.as_posix(),
                "internal_path": group_internal_path.as_posix(),
                "report_path": group_report_path.as_posix(),
                "group_manifest_path": group_manifest_path.as_posix(),
                "candidate_metric_view_fqn": candidate_fqn,
                "source_summary_path": source_summary_path.as_posix(),
                "status": group_manifest["status"],
            }
        )
    return {
        "schema_version": "1.0",
        "workflow_run_id": inventory["workflow_run_id"],
        "created_at": inventory["created_at"],
        "status": "COMPLETE",
        "grouping_proposal_path": Path(grouping_proposal_path).as_posix(),
        "groups": group_entries,
        "ungrouped_datasources": proposal["ungrouped_datasources"],
        "summary": {
            "datasource_count": len(semantic_assets),
            "semantic_group_count": len(group_entries),
            "ready_group_count": len(group_entries),
            "blocked_group_count": 0,
            "excluded_helper_count": len(proposal["ungrouped_datasources"]),
        },
        "provenance": {"generator": {"name": "datasource-semantic-migration", "version": __version__}},
    }
