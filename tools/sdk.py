from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


SIDE_EFFECTS = {"read_only", "write", "destructive"}


@dataclass(frozen=True)
class ToolSpec:
    id: str
    version: str
    description: str
    side_effect: str = "read_only"
    capabilities: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.side_effect not in SIDE_EFFECTS:
            raise ValueError(f"unsupported side_effect: {self.side_effect}")


@dataclass(frozen=True)
class ToolResult:
    tool_id: str
    ok: bool
    output: Any
    provenance: dict[str, Any]
    side_effect: str


class Tool(Protocol):
    spec: ToolSpec

    def run(self, target: dict[str, Any], params: dict[str, Any] | None = None) -> ToolResult: ...
