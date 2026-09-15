"""Load governed deterministic predicate specifications."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json
import yaml

ROOT = Path(__file__).resolve().parent.parent
PREDICATE_SPECS = ROOT / "governance" / "knowledge" / "predicate_specs.yaml"

def load_predicate_specs() -> dict[str, Any]:
    if not PREDICATE_SPECS.exists():
        return {}
    return yaml.safe_load(PREDICATE_SPECS.read_text(encoding="utf-8")) or {}

def control_predicate_specs(control_id: str, framework: str = "") -> dict[str, Any]:
    data = load_predicate_specs()
    canonical = str(framework or "").strip()
    if canonical:
        frameworks = data.get("frameworks") or {}
        fdata = frameworks.get(canonical) or frameworks.get(canonical.replace("_", " "))
        if isinstance(fdata, dict):
            controls = fdata.get("controls") or {}
            spec = controls.get(str(control_id))
            if isinstance(spec, dict):
                return dict(spec.get("elements") or {})
    # Backward-compatible single-framework shape (currently MAS M3.6).
    if str(data.get("control_id")) == str(control_id):
        return dict(data.get("elements") or {})
    return {}

def predicate_spec_hash(control_id: str, framework: str = "") -> str:
    specs = control_predicate_specs(control_id, framework)
    raw = json.dumps(specs, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()
