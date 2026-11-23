from __future__ import annotations

from dataclasses import dataclass

from .config import validate_volume_path


@dataclass(frozen=True)
class InputContract:
    input_volume_path: str

    @classmethod
    def create(cls, input_volume_path: str) -> "InputContract":
        return cls(input_volume_path=validate_volume_path(input_volume_path, "input_volume_path"))

    @property
    def datasources_path(self) -> str:
        return f"{self.input_volume_path}/datasources"

    @property
    def mappings_path(self) -> str:
        return f"{self.input_volume_path}/mappings"

    def as_dict(self) -> dict[str, str]:
        return {
            "input_volume_path": self.input_volume_path,
            "datasources_path": self.datasources_path,
            "mappings_path": self.mappings_path,
        }
