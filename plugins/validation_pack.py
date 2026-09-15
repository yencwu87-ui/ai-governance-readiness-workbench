"""Read-only provider for producer-owned structured validation-pack observations.

The provider does not infer governance conclusions. It reads a manifest of observed facts whose
source names and payloads are declared by the producer, then emits canonical GE-111 Observations.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from governance.observation import Observation, observe


class ValidationPackPlugin:
    id = "validation_pack"
    version = "1.0.0"
    target_types = ["m36_validation_pack"]
    capabilities = ["observe.m36_validation_pack"]
    side_effects = ["read_only"]

    def capabilities_for_element(self, element_id: str, control_id: str = "") -> list[str]:
        return list(self.capabilities)

    def collect(self, target: dict[str, Any]) -> list[Observation]:
        path = Path(str(target.get("path") or ""))
        if not path.is_file():
            raise FileNotFoundError(f"validation-pack observation source not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw.get("observations") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise ValueError("validation-pack observation source must contain an observations list")
        out: list[Observation] = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"observation row {i} must be an object")
            source = str(row.get("source") or "").strip()
            payload = dict(row.get("payload") or {})
            subject = str(row.get("subject") or target.get("id") or path.name)
            if not source:
                raise ValueError(f"observation row {i} has no source")
            if not payload:
                raise ValueError(f"observation row {i} has no payload")
            observed_at = str(row.get("observed_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"))
            provenance = dict(row.get("provenance") or {})
            provenance.setdefault("provider", self.id)
            provenance.setdefault("source_file", str(path))
            out.append(observe(subject, source, payload, observed_at=observed_at,
                               provenance=provenance))
        return out
