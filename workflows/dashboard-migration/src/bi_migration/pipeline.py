from __future__ import annotations

import csv
import json
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from bi_migration.grouping import dependency_graph, group_assets
from bi_migration.ingest import build_artifact_manifest, build_run_manifest
from bi_migration.inventory import build_inventory_preflight
from bi_migration.mapping import apply_mapping_evidence, draft_mapping, write_mapping_outputs
from bi_migration.mapping_documents import load_mapping_documents
from bi_migration.preflight import build_readiness_report
from bi_migration.tableau import find_tableau_files, parse_tableau


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _write_mapping_template(path: Path, mapping: dict) -> None:
    fieldnames = [
        "datasource",
        "legacy",
        "datatype",
        "calculation",
        "assets",
        "target_table",
        "target_expression",
        "source_grain",
        "target_grain",
        "conversion",
        "status",
        "evidence",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for field in mapping.get("fields", []):
            writer.writerow(
                {
                    **{key: field.get(key, "") for key in fieldnames},
                    "assets": "|".join(field.get("assets", [])),
                    "evidence": "|".join(field.get("evidence", [])),
                }
            )


def _compile_group_outputs(
    output: Path,
    groups: list[dict],
    assets: list[dict],
    target_metadata: dict,
    domain: str,
    evidence: list[dict],
) -> list[dict]:
    assets_by_id = {asset["asset_id"]: asset for asset in assets}
    summaries = []
    for group in groups:
        scoped_assets = [assets_by_id[asset_id] for asset_id in group["assets"]]
        group_domain = f"{domain}-{group['group_id']}"
        mapping, _, kpis = draft_mapping(scoped_assets, target_metadata, group_domain)
        mapping["semantic_group"] = group["group_id"]
        mapping["coverage_signature"] = group["coverage_signature"]
        mapping, conflicts = apply_mapping_evidence(mapping, evidence)
        unresolved = [item for item in mapping["fields"] if item["status"] == "unresolved"]
        readiness = build_readiness_report(scoped_assets, [], mapping, conflicts, [])
        group_output = output / "groups" / group["group_id"]
        group_output.mkdir(parents=True, exist_ok=True)
        _write_json(group_output / "source_inventory.json", scoped_assets)
        _write_json(group_output / "mapping_evidence.json", {"conflicts": conflicts})
        _write_json(group_output / "readiness_report.json", readiness)
        _write_mapping_template(group_output / "mapping_template.csv", mapping)
        write_mapping_outputs(mapping, unresolved, kpis, group_output)
        summaries.append(
            {
                "group_id": group["group_id"],
                "coverage_signature": group["coverage_signature"],
                "assets": group["assets"],
                "field_count": len(mapping["fields"]),
                "mapped_fields": readiness["coverage"]["mapped_fields"],
                "unresolved_fields": readiness["coverage"]["unresolved_fields"],
                "mapping_percentage": readiness["coverage"]["mapping_percentage"],
                "relationship_count": readiness["coverage"]["total_relationships"],
                "unresolved_relationships": readiness["coverage"]["unresolved_relationships"],
                "contract_status": readiness["contract_status"],
                "ready": readiness["ready"],
                "output_path": str(group_output),
            }
        )
    return summaries


def run_backend_pipeline(
    input_path: str | Path,
    target_metadata_path: str | Path,
    domain: str,
    output_path: str | Path,
    mapping_documents_path: str | Path | None = None,
    run_id: str = "local-run",
    source_base_uri: str | None = None,
) -> dict:
    output = Path(output_path)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    roots = [input_path]
    if mapping_documents_path and Path(mapping_documents_path).resolve() != Path(input_path).resolve():
        roots.append(mapping_documents_path)
    manifest = build_artifact_manifest(*roots, source_base_uri=source_base_uri)
    run_manifest = build_run_manifest(manifest, run_id=run_id, source_base_uri=source_base_uri)

    assets = []
    inventory_errors = []
    for path in find_tableau_files(input_path):
        try:
            assets.append(parse_tableau(path))
        except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as error:
            inventory_errors.append({"file": str(path), "error": str(error), "status": "quarantined"})

    errors_by_path = {item["file"]: item["error"] for item in inventory_errors}
    for artifact in manifest:
        if artifact["path"] in errors_by_path:
            artifact["status"] = "quarantined"
            artifact["error"] = errors_by_path[artifact["path"]]

    groups = group_assets(assets)
    graph = dependency_graph(assets)
    target_metadata = json.loads(Path(target_metadata_path).read_text(encoding="utf-8"))
    mapping, _, kpis = draft_mapping(assets, target_metadata, domain)
    evidence, document_errors = load_mapping_documents(mapping_documents_path)
    document_errors_by_path = {item["file"]: item["error"] for item in document_errors}
    for artifact in manifest:
        if artifact["path"] in document_errors_by_path:
            artifact["status"] = "quarantined"
            artifact["error"] = document_errors_by_path[artifact["path"]]
    run_manifest["artifacts"] = manifest
    inventory_preflight = build_inventory_preflight(assets, inventory_errors, run_manifest)
    mapping, conflicts = apply_mapping_evidence(mapping, evidence)
    unresolved = [item for item in mapping["fields"] if item["status"] == "unresolved"]
    readiness = build_readiness_report(assets, inventory_errors, mapping, conflicts, document_errors)
    group_summaries = _compile_group_outputs(
        output=output,
        groups=groups,
        assets=assets,
        target_metadata=target_metadata,
        domain=domain,
        evidence=evidence,
    )
    readiness["groups"] = group_summaries
    readiness["group_summary"] = {
        "total": len(group_summaries),
        "ready": sum(1 for item in group_summaries if item["ready"]),
        "blocked": sum(1 for item in group_summaries if not item["ready"]),
    }

    _write_json(output / "artifact_manifest.json", manifest)
    _write_json(output / "run_manifest.json", run_manifest)
    _write_json(output / "inventory.json", assets)
    _write_json(output / "inventory_preflight.json", inventory_preflight)
    _write_json(output / "inventory_errors.json", inventory_errors)
    _write_json(output / "dependency_graph.json", graph)
    _write_json(output / "groups.json", groups)
    _write_json(output / "mapping_evidence.json", {"evidence": evidence, "conflicts": conflicts, "errors": document_errors})
    _write_json(output / "readiness_report.json", readiness)
    _write_json(output / "group_readiness.json", group_summaries)
    write_mapping_outputs(mapping, unresolved, kpis, output)
    return {
        "artifacts": len(manifest),
        "assets": len(assets),
        "quarantined": len(inventory_errors) + len(document_errors),
        "groups": len(groups),
        "fields": len(mapping["fields"]),
        "unresolved": len(unresolved),
        "ready": readiness["ready"],
        "inventory_status": inventory_preflight["status"],
    }
