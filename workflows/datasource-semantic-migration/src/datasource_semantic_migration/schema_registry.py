from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SchemaDefinition:
    name: str
    version: str
    path: Path
    document: dict[str, Any]


class SchemaRegistry:
    def __init__(self, schemas_root: str | Path):
        self.schemas_root = Path(schemas_root)
        registry_path = self.schemas_root / "registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        self._entries = registry["schemas"]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def get(self, name: str) -> SchemaDefinition:
        try:
            entry = self._entries[name]
        except KeyError as error:
            raise KeyError(f"Unknown schema: {name}") from error
        path = self.schemas_root / entry["path"]
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("$id") != entry["id"]:
            raise ValueError(f"Schema ID mismatch for {name}")
        return SchemaDefinition(name=name, version=entry["version"], path=path, document=document)
