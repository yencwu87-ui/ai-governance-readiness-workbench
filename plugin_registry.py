"""Compatibility facade for the built-in plugin registry."""
from plugins.registry import get_plugin, list_plugins

__all__ = ["get_plugin", "list_plugins"]
