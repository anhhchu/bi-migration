from __future__ import annotations


MAPPED_STATUSES = {"proposed", "approved"}
DISPOSITIONED_STATUSES = {"skipped", "unsupported", "redesign", "rejected"}


def build_readiness_report(
    assets: list[dict],
    inventory_errors: list[dict],
    mapping: dict,
    mapping_conflicts: list[dict],
    document_errors: list[dict],
) -> dict:
    fields = mapping.get("fields", [])
    mapped = [item for item in fields if item.get("status") in MAPPED_STATUSES and item.get("target_expression")]
    dispositioned = [item for item in fields if item.get("status") in DISPOSITIONED_STATUSES]
    unresolved = [item for item in fields if item not in mapped and item not in dispositioned]
    relationships = mapping.get("relationships", [])
    mapped_relationships = [
        item for item in relationships if item.get("status") in MAPPED_STATUSES
    ]
    dispositioned_relationships = [
        item for item in relationships if item.get("status") in DISPOSITIONED_STATUSES
    ]
    unresolved_relationships = [
        item
        for item in relationships
        if item not in mapped_relationships and item not in dispositioned_relationships
    ]
    issues = []
    if inventory_errors:
        issues.append({"code": "inventory_errors", "count": len(inventory_errors), "severity": "warning"})
    if document_errors:
        issues.append({"code": "mapping_document_errors", "count": len(document_errors), "severity": "warning"})
    if mapping_conflicts:
        issues.append({"code": "mapping_conflicts", "count": len(mapping_conflicts), "severity": "error"})
    if unresolved:
        issues.append({"code": "unresolved_fields", "count": len(unresolved), "severity": "error"})
    if unresolved_relationships:
        issues.append(
            {"code": "unresolved_relationships", "count": len(unresolved_relationships), "severity": "error"}
        )
    if mapping.get("status") != "approved":
        issues.append({"code": "contract_not_approved", "count": 1, "severity": "error"})
    total = len(fields)
    return {
        "ready": not any(issue["severity"] == "error" for issue in issues),
        "asset_count": len(assets),
        "contract_status": mapping.get("status"),
        "coverage": {
            "total_fields": total,
            "mapped_fields": len(mapped),
            "dispositioned_fields": len(dispositioned),
            "unresolved_fields": len(unresolved),
            "mapping_percentage": round((len(mapped) + len(dispositioned)) / total * 100, 2) if total else 100.0,
            "total_relationships": len(relationships),
            "mapped_relationships": len(mapped_relationships),
            "dispositioned_relationships": len(dispositioned_relationships),
            "unresolved_relationships": len(unresolved_relationships),
        },
        "issues": issues,
        "unresolved": [
            {"datasource": item.get("datasource"), "legacy": item.get("legacy"), "assets": item.get("assets", [])}
            for item in unresolved
        ],
        "unresolved_relationships": [
            {
                "datasource": item.get("datasource"),
                "left_table": item.get("source", {}).get("left_table"),
                "right_table": item.get("source", {}).get("right_table"),
                "assets": item.get("assets", []),
            }
            for item in unresolved_relationships
        ],
    }
