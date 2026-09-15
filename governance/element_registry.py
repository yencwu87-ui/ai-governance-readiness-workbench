"""Authoritative element registry and shared element identity graph.

Element IDs are governed contract keys. This module is deliberately read-only: retrieval,
plugins, tests and inference may attach metadata to an element, but none may create or mutate
the governed element list implicitly.
"""
from __future__ import annotations
from functools import lru_cache
from typing import Any

from governance.control_contract import requirement_context
from governance.element_contract import element_testing_context
from governance.semantic_registry import element_semantics as semantic_element


def _key(control_id: str, requirement_id: str, element_id: str) -> str:
    return f"{control_id}.{requirement_id}.{element_id}"


def elements_for(control_id: str, framework: str = "", requirement_id: str = "R1") -> list[dict[str, Any]]:
    ctx = requirement_context(control_id, framework)
    out: list[dict[str, Any]] = []
    for idx, e in enumerate(ctx.get("elements") or []):
        if not isinstance(e, dict) or e.get("lane", "a") == "b" or not e.get("text"):
            continue
        eid = str(e.get("id") or f"e{idx}").strip()
        row = dict(e)
        row.update({
            "control_id": str(control_id),
            "requirement_id": requirement_id,
            "element_id": eid,
            "element_key": _key(str(control_id), requirement_id, eid),
            "text": " ".join(str(e.get("text") or "").split()),
            "locator": e.get("locator") or f"controls.{control_id}.elements[{idx}]",
        })
        out.append(row)
    return out


def catalog(control_id: str, framework: str = "", requirement_id: str = "R1") -> dict[str, dict[str, Any]]:
    return {e["element_id"]: e for e in elements_for(control_id, framework, requirement_id)}


def get(control_id: str, element_id: str, framework: str = "", requirement_id: str = "R1") -> dict[str, Any] | None:
    return catalog(control_id, framework, requirement_id).get(str(element_id))


def testing_metadata(control_id: str, framework: str, element_id: str) -> dict[str, Any]:
    rows = element_testing_context(control_id, framework)
    return dict(rows.get(str(element_id)) or {})


def capability_index(control_id: str, framework: str = "", requirement_id: str = "R1") -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for e in elements_for(control_id, framework, requirement_id):
        meta = testing_metadata(control_id, framework, e["element_id"])
        out[e["element_id"]] = [str(x) for x in meta.get("capability_hints") or []]
    return out


def validate_pointer(control_id: str, element_id: str, framework: str = "", requirement_id: str = "R1") -> tuple[bool, str]:
    e = get(control_id, element_id, framework, requirement_id)
    if not e:
        return False, f"{control_id}.{requirement_id}.{element_id} is not governed"
    return True, ""


def semantic_metadata(control_id: str, framework: str, element_id: str) -> dict[str, Any]:
    """Reviewer-facing semantic metadata; read-only projection of the governed registry."""
    return dict(semantic_element(control_id, framework, element_id) or {})
