from __future__ import annotations
from typing import Any

from .github import GitHubPlugin
from .validation_pack import ValidationPackPlugin

_PLUGINS = {
    GitHubPlugin.id: GitHubPlugin,
    ValidationPackPlugin.id: ValidationPackPlugin,
}


def list_plugins() -> list[dict[str, Any]]:
    return [
        {"id": cls.id, "version": cls.version, "target_types": list(cls.target_types),
         "capabilities": list(getattr(cls, "capabilities", [])),
         "side_effects": list(getattr(cls, "side_effects", ["read_only"]))}
        for cls in _PLUGINS.values()
    ]


def get_plugin(plugin_id: str):
    cls = _PLUGINS.get(plugin_id)
    if not cls:
        raise KeyError(f"unknown plugin: {plugin_id}")
    return cls()


def capabilities_for_element(plugin_id: str, control_id: str, element_id: str) -> list[str]:
    """Resolve provider capability hints without allowing providers to create elements."""
    plugin = get_plugin(plugin_id)
    method = getattr(plugin, "capabilities_for_element", None)
    if callable(method):
        try:
            return [str(x) for x in (method(element_id, control_id) or [])]
        except TypeError:
            return [str(x) for x in (method(element_id) or [])]
    declared = list(getattr(plugin, "capabilities", []) or [])
    return declared
