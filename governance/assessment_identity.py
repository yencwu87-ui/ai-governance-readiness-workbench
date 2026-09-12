"""Build an immutable identity for a governance assessment configuration.

The identity deliberately hashes every artefact that can change what an assessment means:
code, prompt, requirements, validator, retriever and evaluation rubric.  It is metadata only;
it does not grant or revoke any governance decision.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(path: Path | str) -> str:
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _git_sha() -> str | None:
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def _file_hashes(paths: Iterable[Path | str]) -> dict[str, str | None]:
    out = {}
    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT / p
        key = str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
        out[key] = sha256_file(p) if p.exists() and p.is_file() else None
    return out


def build_assessment_identity(
    *,
    engine_version: str,
    model: str,
    model_digest: str | None = None,
    retrieval: dict | None = None,
    git_sha: str | None = None,
    artefacts: Iterable[Path | str] | None = None,
) -> dict:
    """Return a stable, JSON-serialisable identity and its SHA-256 fingerprint."""
    files = list(artefacts or [
        "assessor.py",
        "pipeline.py",
        "requirements_overlay.py",
        "requirements/mas.yaml",
        "validator.py",
        "retriever.py",
        "eval/rubric.md",
        "policy/ai-lifecycle.yaml",
        "governance/knowledge/brain.yaml",
        "governance/knowledge/control_testing.yaml",
        "governance/knowledge/control_contracts.yaml",
        "governance/knowledge/contracts/mas.yaml",
        "governance/knowledge/contracts/iso_42001.yaml",
        "governance/knowledge/contracts/nist_ai_rmf.yaml",
        "governance/knowledge/contracts/mgf_agentic.yaml",
        "governance/knowledge/contracts/safr.yaml",
    ])
    body = {
        "engine_version": engine_version,
        "git_sha": git_sha if git_sha is not None else _git_sha(),
        "model": model,
        "model_digest": model_digest,
        "retrieval": retrieval or {},
        "artefact_sha256": _file_hashes(files),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["assessment_id"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return body
