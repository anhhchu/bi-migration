from __future__ import annotations

import json
from typing import Any


def build_analysis_batches(inventory: dict[str, Any], batch_size: int) -> list[str]:
    if batch_size < 1:
        raise ValueError("analysis batch size must be positive")
    indexes = [index for index, asset in enumerate(inventory.get("assets", [])) if asset.get("duplicate_of") is None]
    return [
        json.dumps(indexes[offset : offset + batch_size], separators=(",", ":"))
        for offset in range(0, len(indexes), batch_size)
    ]
