"""
Adapters that turn the declared policy plus repository state into records the GOV-* controls test.

runtime_config   — providers actually configured or deployed (assessor default, env, deploy.yml)
policy_providers — providers the policy permits, plus any covered by an open exception
artefact_status  — one row per (model, required artefact) with present true/false
exception_status — one row per open exception with completeness and max-life flags
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import AdapterResult, _hash_file, _hash_text, _read_table, _resolve, adapter


def _policy(target: Path, cfg: dict) -> dict:
    from ..policy import load
    return load(_resolve(target, cfg.get("policy", "policy/ai-lifecycle.yaml")))


def _open_exceptions(target: Path) -> list[dict]:
    p = target / "governance" / "exceptions.csv"
    if not p.exists():
        return []
    today = datetime.now(timezone.utc).date().isoformat()
    return [r for r in _read_table(p)
            if str(r.get("status", "")).strip().lower() == "open" and str(r.get("expires_on", "")) >= today]


@adapter("runtime_config")
def runtime_config(target: Path, cfg: dict) -> AdapterResult:
    """Providers in force: assessor default, ASSESSOR_PROVIDER env, and any provider named in deploy.yml."""
    records, artefacts = [], []
    ap = _resolve(target, "assessor.py")
    if ap.exists():
        m = re.search(r'ASSESSOR_PROVIDER["\']?\s*,\s*["\'](\w+)["\']', ap.read_text())
        if m:
            records.append({"provider": m.group(1).lower(), "source": "assessor.py default"})
        artefacts.append(_hash_file(ap))
    env = os.environ.get("ASSESSOR_PROVIDER")
    if env:
        records.append({"provider": env.lower(), "source": "ASSESSOR_PROVIDER env"})
    dp = _resolve(target, "deploy.yml")
    if dp.exists():
        doc = yaml.safe_load(dp.read_text()) or {}
        for m_ in doc.get("models", []) or []:
            if m_.get("provider"):
                records.append({"provider": str(m_["provider"]).lower(), "source": f"deploy.yml {m_.get('version')}"})
        artefacts.append(_hash_file(dp))
    if not records:
        return AdapterResult("missing", message="no provider configuration found")
    return AdapterResult("ok", records, artefacts)


@adapter("policy_providers")
def policy_providers(target: Path, cfg: dict) -> AdapterResult:
    """Allowed = policy allowed_providers + any provider with an open exception naming GOV-01."""
    pol = _policy(target, cfg)
    if not pol:
        return AdapterResult("missing", message="policy file not found")
    inf = (pol.get("golden_state") or {}).get("inference") or {}
    recs = [{"provider": str(p).lower(), "basis": "policy"} for p in inf.get("allowed_providers", [])]
    excs = _open_exceptions(target)
    for pe in inf.get("provider_exceptions", []) or []:
        name = str(pe.get("provider", "")).lower()
        hit = next((e for e in excs if str(e.get("control_id", "")).strip() == "GOV-01"
                    and name in str(e.get("rationale", "")).lower()), None)
        if hit:
            recs.append({"provider": name, "basis": f"exception {hit.get('exception_id')}"})
    return AdapterResult("ok", recs, [_hash_text(pol["_path"], pol["_sha256"])])


ARTEFACT_LOCATIONS = {
    "model_card": ["MODEL_CARD.md", "model_card.md", "docs/MODEL_CARD.md"],
    "registry_entry": ["governance/model_registry.csv"],
    "change_ticket": ["governance/tickets.csv"],
    "impact_assessment": ["governance/assessments.csv", "governance/impact_assessment.md"],
    "independent_validation": ["governance/tickets.csv"],
    "stress_test_pre_release": ["stress/results"],
    "eval_before_deploy": ["governance/eval_results.json"],
}


@adapter("artefact_status")
def artefact_status(target: Path, cfg: dict) -> AdapterResult:
    """One row per (model, required artefact). `present` is existence only; currency is the human gate."""
    pol = _policy(target, cfg)
    if not pol:
        return AdapterResult("missing", message="policy file not found")
    req = (pol.get("golden_state") or {}).get("required_artefacts") or {}
    reg = target / "governance" / "model_registry.csv"
    if not reg.exists():
        return AdapterResult("missing", message="model_registry.csv not found")
    records = []
    for m in _read_table(reg):
        needed = list(req.get("all", []))
        if cfg.get("enforce_tier"):
            needed += list(req.get(str(m.get("risk_tier", "")).lower(), []))
        for art in needed:
            found = None
            for loc in ARTEFACT_LOCATIONS.get(art, []):
                p = _resolve(target, loc)
                if p.exists() and (not p.is_dir() or any(p.iterdir())):
                    found = loc
                    break
            records.append({"model_id": m.get("model_id"), "artefact": art, "present": bool(found), "location": found})
    return AdapterResult("ok", records, [_hash_file(reg)])


@adapter("exception_status")
def exception_status(target: Path, cfg: dict) -> AdapterResult:
    """Completeness and max-life of every open exception, per the policy's own rules."""
    pol = _policy(target, cfg)
    if not pol:
        return AdapterResult("missing", message="policy file not found")
    rules = pol.get("exceptions") or {}
    required, max_days = rules.get("requires", []), int(rules.get("max_days", 180))
    p = target / "governance" / "exceptions.csv"
    if not p.exists():
        return AdapterResult("missing", message="exceptions.csv not found")
    today = datetime.now(timezone.utc).date()
    records = []
    for r in _read_table(p):
        if str(r.get("status", "")).strip().lower() != "open":
            continue
        missing = [f for f in required if not str(r.get(f, "")).strip()]
        try:
            life_ok = (datetime.fromisoformat(str(r["expires_on"])).date() - today).days <= max_days
        except (ValueError, KeyError):
            life_ok = False
        records.append({"exception_id": r.get("exception_id"), "control_id": r.get("control_id"),
                        "complete": not missing, "missing_fields": missing,
                        "within_max_life": life_ok, "ok": bool(not missing and life_ok)})
    return AdapterResult("ok", records, [_hash_file(p)])
