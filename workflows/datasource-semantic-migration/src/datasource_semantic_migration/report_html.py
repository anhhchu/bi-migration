"""HTML for the semantic migration review.

Layout per group, in reading order: header → next step → stage strip → action items →
key numbers → collapsed details. Everything a reviewer must act on is above the fold;
supporting evidence is folded away but one click from view.
"""

from __future__ import annotations

from html import escape
from typing import Any

from .action_items import plain_language

STATUS_STYLE = {
    "BLOCKED": ("Blocked", "danger"),
    "NEEDS_REVIEW": ("Needs review", "warning"),
    "CHECKS_PENDING": ("Checks pending", "info"),
    "READY_FOR_PARITY": ("Ready for parity", "success"),
    "READY": ("Ready", "success"),
}
STAGE_STYLE = {"PASS": ("✓", "success"), "WARN": ("!", "warning"), "FAIL": ("✕", "danger"), "NOT_RUN": ("–", "muted")}
STAGE_TEXT = {"PASS": "Pass", "WARN": "Review", "FAIL": "Fix", "NOT_RUN": "Not run"}
CATEGORY_TONE = {
    "data_mapping": "info",
    "business_definition": "warning",
    "calculation": "danger",
    "access_platform": "danger",
    "number_checks": "muted",
    "sign_off": "muted",
}

CSS = """
:root{--ink:#0b2026;--muted:#5d6b70;--line:#e3e6e8;--bg:#f6f7f8;--card:#fff;
--danger:#b42318;--danger-bg:#fef3f2;--warning:#9a6700;--warning-bg:#fff8e6;
--success:#1b7f3b;--success-bg:#edf7ef;--info:#1f5fae;--info-bg:#eef4fc;--muted-bg:#f2f4f5;--accent:#ff3621}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 24px 64px}
h1,h2,h3,h4{margin:0;line-height:1.25}h1{font-size:26px}h2{font-size:20px}h3{font-size:15px}h4{font-size:14px}
p{margin:0}code{font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}
.eyebrow{color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
.page-head{display:grid;gap:6px;margin-bottom:20px}.page-head .meta{color:var(--muted)}
.tiles{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:24px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile span{display:block;color:var(--muted);font-size:12px}.tile strong{font-size:24px}
.tile.danger strong{color:var(--danger)}.tile.warning strong{color:var(--warning)}.tile.success strong{color:var(--success)}
.index{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:24px;overflow:hidden}
.index a{display:grid;grid-template-columns:1fr auto auto;gap:16px;align-items:center;padding:10px 16px;color:inherit;text-decoration:none;border-top:1px solid var(--line)}
.index a:first-of-type{border-top:0}.index a:hover{background:var(--muted-bg)}.index .counts{color:var(--muted);font-size:12px}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
.pill.danger{background:var(--danger-bg);color:var(--danger)}.pill.warning{background:var(--warning-bg);color:var(--warning)}
.pill.success{background:var(--success-bg);color:var(--success)}.pill.info{background:var(--info-bg);color:var(--info)}
.pill.muted{background:var(--muted-bg);color:var(--muted)}
.group{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-top:24px;overflow:hidden}
.group-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;padding:20px 24px;border-bottom:1px solid var(--line)}
.group-head .fqn{margin-top:6px;color:var(--muted)}.group-head .fqn a{margin-left:8px;color:var(--info);font-size:12px;font-weight:600}
.group-body{display:grid;gap:22px;padding:20px 24px 24px}
.next{border-left:4px solid var(--accent);background:var(--muted-bg);border-radius:6px;padding:12px 16px}
.next.danger{border-color:var(--danger);background:var(--danger-bg)}.next.warning{border-color:var(--warning);background:var(--warning-bg)}
.next.success{border-color:var(--success);background:var(--success-bg)}.next p{margin-top:4px}
.stages{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}
.stage{border:1px solid var(--line);border-radius:8px;padding:10px;display:grid;gap:4px}
.stage .mark{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;font-size:12px;font-weight:700}
.stage.success .mark{background:var(--success);color:#fff}.stage.warning .mark{background:#e0a100;color:#fff}
.stage.danger .mark{background:var(--danger);color:#fff}.stage.muted .mark{background:var(--muted-bg);color:var(--muted)}
.stage .label{font-weight:700}.stage .state{color:var(--muted);font-size:12px}
.section-title{display:flex;align-items:baseline;gap:10px;margin-bottom:10px}.section-title .sub{color:var(--muted);font-size:12px}
.category{border:1px solid var(--line);border-left:4px solid var(--line);border-radius:8px;padding:14px 16px;margin-top:10px}
.category.danger{border-left-color:var(--danger)}.category.warning{border-left-color:#e0a100}
.category.info{border-left-color:var(--info)}.category.muted{border-left-color:#c4cbcf}
.category-head{display:flex;justify-content:space-between;gap:12px;align-items:center}
.category-head h4{font-size:15px;font-weight:700;letter-spacing:.01em}
.category.danger h4{color:var(--danger)}.category.warning h4{color:var(--warning)}.category.info h4{color:var(--info)}
.category-head .count{display:inline-block;margin-left:6px;padding:0 7px;border-radius:999px;background:var(--muted-bg);color:var(--muted);font-size:12px}
.why{color:var(--muted);font-size:13px;margin-top:4px}
.items{list-style:none;margin:10px 0 0;padding:0;display:grid;gap:10px}
.items li{border-top:1px solid var(--line);padding-top:10px;display:grid;gap:4px}
.item-head{display:flex;justify-content:space-between;gap:12px;align-items:center}
.item-title{font-size:14px;font-weight:600;color:var(--ink)}
.detail{color:#33454b;font-size:13px}
.names{display:flex;flex-wrap:wrap;gap:4px}.names span{background:var(--muted-bg);border:1px solid var(--line);border-radius:4px;padding:1px 6px;font-size:12px}
.items code{display:block;background:var(--muted-bg);border-radius:6px;padding:6px 8px}
.todo{font-size:13px;color:#33454b}.todo b{color:var(--ink);font-weight:600}
.none{color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.kpi{background:var(--muted-bg);border-radius:8px;padding:10px 12px}.kpi span{display:block;color:var(--muted);font-size:12px}.kpi strong{font-size:18px}
details{border:1px solid var(--line);border-radius:8px;padding:0 14px}details+details{margin-top:8px}
summary{cursor:pointer;padding:10px 0;font-weight:700}summary .sub{color:var(--muted);font-weight:400}
details[open] summary{border-bottom:1px solid var(--line);margin-bottom:10px}details>*:last-child{margin-bottom:12px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;background:var(--muted-bg)}
ul.plain{margin:0;padding-left:18px}ul.plain li{margin:4px 0}
@media (max-width:820px){.tiles{grid-template-columns:repeat(2,1fr)}.stages{grid-template-columns:repeat(3,1fr)}.kpis{grid-template-columns:repeat(2,1fr)}}
"""


def _pill(text: str, tone: str) -> str:
    return f"<span class='pill {tone}'>{escape(text)}</span>"


def _status(group: dict[str, Any]) -> tuple[str, str]:
    gate_status = (group.get("gate") or {}).get("status") or group.get("readiness") or "UNKNOWN"
    return STATUS_STYLE.get(gate_status, (gate_status.replace("_", " ").title(), "muted"))


def _display_name(group: dict[str, Any]) -> str:
    return str(group.get("display_name") or str(group["group_id"]).replace("-", " ").title())


def _details(title: str, body: str, count: int | None = None, hint: str = "") -> str:
    if not body:
        return ""
    counter = f" · {count}" if count is not None else ""
    sub = f" <span class='sub'>{escape(hint)}</span>" if hint else ""
    return f"<details><summary>{escape(title)}{counter}{sub}</summary>{body}</details>"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _stage_strip(gate: dict[str, Any]) -> str:
    cells = []
    for stage in gate.get("stages", []):
        mark, tone = STAGE_STYLE.get(stage["status"], ("?", "muted"))
        cells.append(
            f"<div class='stage {tone}' title='{escape(stage['summary'], quote=True)}'>"
            f"<span class='mark'>{mark}</span><span class='label'>{escape(stage['label'])}</span>"
            f"<span class='state'>{STAGE_TEXT.get(stage['status'], stage['status'])}</span></div>"
        )
    return f"<div class='stages'>{''.join(cells)}</div>"


def _action_items(action_groups: dict[str, Any] | None, legacy_actions: list[dict[str, Any]]) -> str:
    if action_groups is None:
        if not legacy_actions:
            return "<p class='none'>No action items.</p>"
        items = "".join(
            f"<li><div class='item-head'><strong>{escape(action['title'])}</strong>"
            f"{_pill(action['priority'].title(), 'danger' if action['priority'] == 'BLOCKING' else 'warning')}</div>"
            f"<p>{escape(action['description'])}</p><p class='todo'>{escape(', '.join(action.get('items', [])))}</p></li>"
            for action in legacy_actions
        )
        return f"<div class='category muted'><ul class='items'>{items}</ul></div>"
    ordered = sorted(action_groups["groups"], key=lambda group: not group["blocking"])
    blocks = []
    for group in ordered:
        tone = CATEGORY_TONE.get(group["category"], "muted")
        items = "".join(
            "<li><div class='item-head'>"
            f"<span class='item-title'>{escape(str(item['title']))}</span>"
            + (_pill("Blocking", "danger") if item.get("blocking") else "")
            + "</div>"
            + (
                "<div class='names'>" + "".join(f"<span>{escape(str(name))}</span>" for name in item["names"]) + "</div>"
                if len(item.get("names", [])) > 1
                else ""
            )
            + f"<p class='detail'>{escape(str(item['detail']))}</p>"
            + (f"<code>{escape(str(item['expression']))}</code>" if item.get("expression") else "")
            + f"<p class='todo'><b>What to do:</b> {escape(str(item['what_to_do']))}</p></li>"
            for item in group["items"]
        )
        blocks.append(
            f"<div class='category {tone}'><div class='category-head'>"
            f"<h4>{escape(group['label'])} <span class='count'>{sum(len(item.get('names', [item['title']])) for item in group['items'])}</span></h4>"
            f"{_pill(group['owner'], 'muted')}</div>"
            f"<p class='why'>Why a person is needed: {escape(group['why_human'])}</p>"
            f"<ul class='items'>{items}</ul></div>"
        )
    return "".join(blocks) or "<p class='none'>No action items.</p>"


def catalog_explorer_url(workspace_url: str | None, full_name: str | None) -> str | None:
    """Catalog Explorer page for a three-part Unity Catalog name."""
    if not workspace_url or not full_name:
        return None
    parts = [part.strip().strip("`") for part in full_name.split(".") if part.strip()]
    if len(parts) != 3:
        return None
    from urllib.parse import quote

    return f"{workspace_url.rstrip('/')}/explore/data/" + "/".join(quote(part, safe="") for part in parts)


def _group_html(group: dict[str, Any], workspace_url: str | None = None) -> str:
    label, tone = _status(group)
    gate = group.get("gate") or {}
    action_groups = group.get("action_groups")
    coverage = group.get("coverage", {})
    candidate_fqn = (group.get("candidate") or {}).get("metric_view_fqn")
    candidate = candidate_fqn or "Not created"
    candidate_link = catalog_explorer_url(workspace_url, candidate_fqn)
    blocking = action_groups["blocking_count"] if action_groups else 0
    review = action_groups["review_count"] if action_groups else len(group.get("recommended_actions", []))

    next_step = ""
    if gate:
        next_step = (
            f"<div class='next {tone}'><strong>{escape(gate.get('headline', ''))}</strong>"
            + (f"<p>Next step: {escape(gate['next_step'])}</p>" if gate.get("next_step") else "")
            + "</div>"
        )
    kpis = "".join(
        f"<div class='kpi'><span>{escape(name)}</span><strong>{escape(str(value))}</strong></div>"
        for name, value in (
            ("Dimensions", coverage.get("dimensions_created", "—")),
            ("Measures", coverage.get("measures_created", "—")),
            ("Semantic coverage", f"{coverage.get('semantic_coverage_percent', '—')}%"),
            ("Business items left out", coverage.get("business_items_not_translated", "—")),
        )
    )

    stage_rows = [
        [
            f"<strong>{escape(stage['label'])}</strong>",
            _pill(STAGE_TEXT.get(stage["status"], stage["status"]), STAGE_STYLE.get(stage["status"], ("", "muted"))[1]),
            escape(stage["summary"])
            + (f"<br><span class='why'>Next: {escape(stage['next_step'])}</span>" if stage.get("next_step") and stage["status"] != "PASS" else ""),
        ]
        for stage in gate.get("stages", [])
    ]
    automatic = (action_groups or {}).get("automatic", [])
    automatic_body = (
        "<ul class='plain'>"
        + "".join(f"<li><strong>{escape(str(item['title']))}</strong>: {escape(str(item['detail']))}</li>" for item in automatic)
        + "</ul>"
        if automatic
        else ""
    )
    contract = next((stage for stage in gate.get("stages", []) if stage["key"] == "contract"), {})
    grain_rows = [[f"<code>{escape(str(item['table']))}</code>", escape(str(item.get("grain") or "Not recorded"))] for item in contract.get("tables", [])]
    additivity_rows = [
        [escape(str(item["name"])), escape(item["additivity"].replace("_", "-")), escape(item["basis"])]
        for item in contract.get("measures", [])
    ]
    contract_body = (
        (f"<h4>Grain</h4>{_table(['Table', 'One row is'], grain_rows)}" if grain_rows else "")
        + (f"<h4 style='margin-top:12px'>Measure additivity (inferred)</h4>{_table(['Measure', 'Additivity', 'Why'], additivity_rows)}" if additivity_rows else "")
    )
    not_migrated_rows = [
        [escape(str(item.get("name", "—"))), escape(plain_language(str(item.get("reason", "—"))))]
        for item in group.get("items_not_translated", [])
    ]
    approximation_rows = [
        [escape(str(item.get("name", "—"))), escape(str(item.get("detail", "—")))] for item in group.get("approximations", [])
    ]
    validation_rows = [[escape(str(key)), escape(str(value))] for key, value in (group.get("validation") or {}).items()]
    notes = group.get("notes") or []
    notes_body = "<ul class='plain'>" + "".join(f"<li>{escape(str(note))}</li>" for note in notes) + "</ul>" if notes else ""

    return (
        f"<section class='group' id='{escape(str(group['group_id']), quote=True)}'>"
        f"<div class='group-head'><div><p class='eyebrow'>Semantic group</p><h2>{escape(_display_name(group))}</h2>"
        f"<p class='fqn'><code>{escape(candidate)}</code>"
        + (
            f" <a href='{escape(candidate_link, quote=True)}' target='_blank' rel='noopener noreferrer'>"
            "Open in Catalog Explorer ↗</a>"
            if candidate_link
            else ""
        )
        + f"</p></div>{_pill(label, tone)}</div>"
        f"<div class='group-body'>{next_step}"
        + (_stage_strip(gate) if gate else "")
        + "<div><div class='section-title'><h3>Action items</h3>"
        f"<span class='sub'>{blocking} blocking · {review} to review</span></div>"
        f"{_action_items(action_groups, group.get('recommended_actions', []))}</div>"
        f"<div class='kpis'>{kpis}</div>"
        "<div>"
        + _details("Stage evidence", _table(["Stage", "Status", "Evidence"], stage_rows))
        + _details("Handled automatically", automatic_body, len(automatic), "no action needed")
        + _details("Contract: grain and additivity", contract_body)
        + _details("Everything not migrated", _table(["Item", "Reason"], not_migrated_rows), len(not_migrated_rows))
        + _details("Approximations", _table(["Item", "Translation"], approximation_rows), len(approximation_rows))
        + _details("Validation evidence", _table(["Check", "Result"], validation_rows), len(validation_rows))
        + _details("Translation notes", notes_body, len(notes), "recorded during import")
        + "</div></div></section>"
    )


def render_workflow_html(review: dict[str, Any]) -> str:
    groups = review["groups"]
    totals = review["totals"]
    needs_review = sum(_status(group)[0] in {"Needs review", "Checks pending"} for group in groups)
    ready = sum(_status(group)[1] == "success" for group in groups)
    blocked = sum(_status(group)[0] == "Blocked" for group in groups)
    tiles = "".join(
        f"<div class='tile {tone}'><span>{escape(name)}</span><strong>{value}</strong></div>"
        for name, value, tone in (
            ("Semantic groups", len(groups), ""),
            ("Ready for parity", ready, "success"),
            ("Need review", needs_review, "warning"),
            ("Blocked", blocked, "danger"),
            ("Action items", totals.get("actions", 0), ""),
        )
    )
    index = ""
    if len(groups) > 1:
        rows = []
        for group in sorted(groups, key=lambda item: ("Blocked", "Needs review").index(_status(item)[0]) if _status(item)[0] in ("Blocked", "Needs review") else 2):
            label, tone = _status(group)
            action_groups = group.get("action_groups") or {}
            rows.append(
                f"<a href='#{escape(str(group['group_id']), quote=True)}'><strong>{escape(_display_name(group))}</strong>"
                f"<span class='counts'>{action_groups.get('blocking_count', 0)} blocking · {action_groups.get('review_count', 0)} to review</span>"
                f"{_pill(label, tone)}</a>"
            )
        index = f"<nav class='index' aria-label='Semantic groups'>{''.join(rows)}</nav>"
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Semantic migration review · {escape(str(review['workflow_run_id']))}</title><style>{CSS}</style></head>"
        "<body><main><header class='page-head'><p class='eyebrow'>Semantic migration review</p>"
        f"<h1>Run {escape(str(review['workflow_run_id']))}</h1><p class='meta'>{escape(review['headline'])}</p></header>"
        f"<div class='tiles'>{tiles}</div>{index}{''.join(_group_html(group, review.get('workspace_url')) for group in groups)}</main></body></html>\n"
    )
