"""
Adapter: environment_scan

Wraps the workbench's scanner.scan_environment() so its filename-pattern signals
become Lane B inventory records with artefact hashes. The scanner keeps its job
(finding things); this adapter adds provenance and strips nothing else.

Record fields: path, kind, hint, controls (list of Lane A control ids), sha256
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import AdapterResult, Artefact, adapter


@adapter("environment_scan")
def environment_scan(target: Path, cfg: dict) -> AdapterResult:
    try:
        from scanner import scan_environment  # workbench module at repo root
    except ImportError as e:
        return AdapterResult("error", message=f"scanner.py not importable: {e}")
    if not target.is_dir():
        return AdapterResult("missing", message=f"{target} is not a directory")
    kinds = set(cfg.get("kinds", []))  # optional filter
    records, artefacts = [], []
    for s in scan_environment(str(target)):
        if kinds and s.kind not in kinds:
            continue
        p = target / s.path
        try:
            data = p.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            artefacts.append(Artefact(str(p), sha, len(data)))
        except OSError:
            sha = None
        records.append({"path": s.path, "kind": s.kind, "hint": s.hint, "controls": list(s.controls), "sha256": sha})
    return AdapterResult("ok", records, artefacts)
