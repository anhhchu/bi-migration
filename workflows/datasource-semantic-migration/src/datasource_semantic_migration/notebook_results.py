from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote


def format_notebook_result(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)


def _volume_paths(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if value.startswith("/Volumes/") else set()
    if isinstance(value, dict):
        return {path for item in value.values() for path in _volume_paths(item)}
    if isinstance(value, (list, tuple, set)):
        return {path for item in value for path in _volume_paths(item)}
    return set()


def volume_catalog_url(path: str) -> str | None:
    parts = Path(path).parts
    if len(parts) < 5 or parts[1] != "Volumes":
        return None
    catalog, schema, volume = parts[2:5]
    return "/explore/data/volumes/{}/{}/{}".format(
        quote(catalog, safe=""),
        quote(schema, safe=""),
        quote(volume, safe=""),
    )


def render_volume_links_html(result: dict[str, Any]) -> str:
    rows = []
    for path in sorted(_volume_paths(result)):
        url = volume_catalog_url(path)
        if not url:
            continue
        rows.append(
            "<li style='margin:6px 0'>"
            f"<a href='{escape(url, quote=True)}' target='_blank' rel='noopener noreferrer'>Open Volume</a>"
            f"<code style='margin-left:8px'>{escape(path)}</code>"
            "</li>"
        )
    if not rows:
        return ""
    return (
        "<div style='margin:12px 0;padding:12px 14px;border:1px solid #dce0e2;border-radius:6px'>"
        "<strong>Volume artifacts</strong><ul style='margin:6px 0 0 18px;padding:0'>"
        + "".join(rows)
        + "</ul></div>"
    )


def summarize_semantic_groups(groups_index: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for group_index, group in enumerate(groups_index.get("groups", [])):
        source_summary_path = Path(group["source_summary_path"])
        source_summary = json.loads(source_summary_path.read_text(encoding="utf-8"))
        summaries.append(
            {
                "group_index": group_index,
                "group_name": group.get("display_name") or group["group_id"],
                "status": group["status"],
                "will_migrate": group["status"] == "READY_FOR_PREFLIGHT",
                "datasources": [
                    {
                        "name": datasource["datasource_name"],
                        "file": Path(datasource["source_path"]).name,
                        "role": "PRIMARY",
                    }
                    for datasource in source_summary.get("datasources", [])
                ]
                + [
                    {
                        "name": datasource["datasource_name"],
                        "file": Path(datasource["source_path"]).name,
                        "role": "SUPPORTING",
                    }
                    for datasource in source_summary.get("supporting_datasources", [])
                ],
                "target_tables": source_summary.get("target_tables", []),
                "candidate_metric_view": group["candidate_metric_view_fqn"],
            }
        )
    return summaries
