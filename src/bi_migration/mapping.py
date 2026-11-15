from __future__ import annotations

import csv
import re
from difflib import SequenceMatcher
from pathlib import Path

import yaml


class _MappingDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower().strip("[]"))


def _source_fields(assets: list[dict]) -> list[dict]:
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
            columns.append({**column, "table": table_name})
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
        "confidence": round(score, 3),
        "status": "proposed" if score >= 0.92 else "unresolved",
        "evidence": evidence or ["name_similarity"],
    }


def draft_mapping(assets: list[dict], target_metadata: dict, domain: str) -> tuple[dict, list[dict], list[dict]]:
    targets = _target_columns(target_metadata)
    proposals = []
    kpis = []
    for source in _source_fields(assets):
        proposal = {**source, **_best_match(source, targets)}
        proposals.append(proposal)
        if source.get("calculation"):
            kpis.append(
                {
                    "legacy_name": source["legacy"],
                    "legacy_expression": source["calculation"],
                    "assets": source["assets"],
                    "status": "candidate",
                }
            )
    mapping = {
        "mapping_version": "0.1.0",
        "domain": domain,
        "status": "proposed",
        "sources": sorted({asset["asset_id"] for asset in assets}),
        "fields": proposals,
        "kpis": kpis,
    }
    unresolved = [proposal for proposal in proposals if proposal["status"] == "unresolved"]
    return mapping, unresolved, kpis


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
        writer = csv.DictWriter(handle, fieldnames=["legacy_name", "legacy_expression", "assets", "status"])
        writer.writeheader()
        for item in kpis:
            writer.writerow(item)
