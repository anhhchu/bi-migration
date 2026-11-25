"""BI tools the workflow can migrate from. The IR records one of these keys as source_system."""

from __future__ import annotations

from typing import Any

SOURCE_SYSTEMS = {"tableau": "Tableau", "powerbi": "Power BI"}
DEFAULT_SOURCE_SYSTEM = "tableau"


def source_system_of(document: dict[str, Any] | None) -> str:
    """source_system of an IR, manifest, or group; artifacts written before the field existed are Tableau."""
    value = str((document or {}).get("source_system") or DEFAULT_SOURCE_SYSTEM)
    if value not in SOURCE_SYSTEMS:
        raise ValueError(f"Unknown source_system {value!r}; expected one of {sorted(SOURCE_SYSTEMS)}")
    return value


def source_label(document: dict[str, Any] | None) -> str:
    """Display name of the source BI tool, for example 'Tableau'."""
    return SOURCE_SYSTEMS[source_system_of(document)]


def fill_source(value: Any, source: str) -> Any:
    """Replace the {source} placeholder in fixed report wording (strings, dicts, lists) with the BI tool name."""
    if isinstance(value, str):
        return value.replace("{source}", source)
    if isinstance(value, dict):
        return {key: fill_source(item, source) for key, item in value.items()}
    if isinstance(value, list):
        return [fill_source(item, source) for item in value]
    return value
