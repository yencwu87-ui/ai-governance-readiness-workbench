from __future__ import annotations

from typing import Any

_TOOLS: dict[str, Any] = {}


def register(tool_cls) -> None:
    spec = tool_cls.spec
    if spec.id in _TOOLS:
        raise ValueError(f"duplicate tool id: {spec.id}")
    _TOOLS[spec.id] = tool_cls


def list_tools() -> list[dict[str, Any]]:
    return [{
        "id": cls.spec.id,
        "version": cls.spec.version,
        "description": cls.spec.description,
        "side_effect": cls.spec.side_effect,
        "capabilities": list(cls.spec.capabilities),
    } for cls in _TOOLS.values()]


def get_tool(tool_id: str):
    cls = _TOOLS.get(tool_id)
    if not cls:
        raise KeyError(f"unknown tool: {tool_id}")
    return cls()
