from __future__ import annotations
from typing import Protocol
from governance.observation import Observation


class Plugin(Protocol):
    id: str
    version: str
    target_types: list[str]
    capabilities: list[str]
    side_effects: list[str]

    def collect(self, target: dict) -> list[Observation]: ...

    def capabilities_for_element(self, element_id: str, control_id: str = "") -> list[str]:
        """Optional mapping: return capabilities this provider can use for a governed element."""
        ...
