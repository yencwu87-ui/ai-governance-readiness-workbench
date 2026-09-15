"""Canonical semantic coverage registry for governed control elements.

The registry is intentionally broader than deterministic predicate coverage. Every governed
control/element gets a reviewer-facing semantic record; verification may be deterministic,
human-judgement, or out-of-band. Source matching is recorded as provenance and never promoted
into a claim of regulatory authority.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Any
import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "governance" / "knowledge" / "semantic_registry.yaml"

@lru_cache(maxsize=1)
def load_semantic_registry() -> dict[str, Any]:
    if not REGISTRY.exists():
        return {"controls": [], "summary": {}}
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {"controls": [], "summary": {}}


def _key(control_id: str, framework: str = "") -> tuple[str, str]:
    return str(framework or "").strip(), str(control_id).strip().replace("★", "")


def control_semantics(control_id: str, framework: str = "") -> dict[str, Any] | None:
    fw, cid = _key(control_id, framework)
    for c in load_semantic_registry().get("controls") or []:
        if str(c.get("control_id")) == cid and str(c.get("framework")) == fw:
            return dict(c)
    return None


def element_semantics(control_id: str, framework: str, element_id: str) -> dict[str, Any] | None:
    c = control_semantics(control_id, framework)
    if not c:
        return None
    for e in c.get("elements") or []:
        if str(e.get("id")) == str(element_id):
            return dict(e)
    return None


def elements_for(control_id: str, framework: str = "") -> list[dict[str, Any]]:
    c = control_semantics(control_id, framework)
    return list(c.get("elements") or []) if c else []


def coverage_summary() -> dict[str, Any]:
    return dict(load_semantic_registry().get("summary") or {})
