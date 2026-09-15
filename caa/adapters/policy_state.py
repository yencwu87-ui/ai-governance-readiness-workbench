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


# Where each required artefact is expected to live. An artefact must have its own evidence:
# never point two obligations at the same file, or one satisfies the other by accident.
# independent_validation is not a file — it is tested behaviourally by GOV-05 and MCM-05.
ARTEFACT_LOCATIONS = {
    "model_card": ["MODEL_CARD.md", "model_card.md", "docs/MODEL_CARD.md"],
    "registry_entry": ["governance/model_registry.csv"],
    "change_ticket": ["governance/tickets.csv"],
    "impact_assessment": ["governance/assessments.csv", "governance/impact_assessment.md",
                          "governance/impact_assessments/"],
    "stress_test_pre_release": ["stress/results"],
    "eval_before_deploy": ["governance/eval_results.json"],
}
BEHAVIOURAL_ARTEFACTS = {"independent_validation"}   # asserted by GOV-05, not by file presence


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
        tier = str(m.get("risk_tier", "")).strip().lower()
        universal = list(req.get("all", []))
        tiered = [a for a in req.get(tier, []) if a not in universal]
        for art in universal + (tiered if cfg.get("enforce_tier", True) else []):
            if art in BEHAVIOURAL_ARTEFACTS:
                continue
            found = None
            for loc in ARTEFACT_LOCATIONS.get(art, []):
                p = _resolve(target, loc)
                if p.exists() and (not p.is_dir() or any(p.iterdir())):
                    found = loc
                    break
            scope = "tier" if art in tiered else "all"
            records.append({"model_id": m.get("model_id"), "risk_tier": tier, "artefact": art, "scope": scope,
                            "present": bool(found), "location": found,
                            "universal_gap": scope == "all" and not found,
                            "tier_gap": scope == "tier" and not found})
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


@adapter("tier_obligations")
def tier_obligations(target: Path, cfg: dict) -> AdapterResult:
    """One row per (model, obligation) from policy.golden_state.tier_obligations, with met true/false.

    Obligations tested here are the ones that are not simply "a file exists":
      review_cycle_days      — an approved change ticket for this model within the cycle
      eval_before_deploy     — an eval run exists for the model's latest deployed version
      independent_validation — the approver of the latest ticket is not the registered model owner
      stress_test_within_days— a stress-test result dated within the window
    approval_level is recorded but not machine-tested; it is the human gate.
    """
    pol = _policy(target, cfg)
    if not pol:
        return AdapterResult("missing", message="policy file not found")
    obligations = (pol.get("golden_state") or {}).get("tier_obligations") or {}
    reg = target / "governance" / "model_registry.csv"
    if not reg.exists():
        return AdapterResult("missing", message="model_registry.csv not found")

    tickets = _read_table(target / "governance" / "tickets.csv") if (target / "governance" / "tickets.csv").exists() else []
    evals = _read_table(target / "governance" / "eval_results.json") if (target / "governance" / "eval_results.json").exists() else []
    deploys = []
    dp = target / "deploy.yml"
    if dp.exists():
        deploys = (yaml.safe_load(dp.read_text()) or {}).get("models", []) or []
    stress_dates = []
    sd = target / "stress" / "results"
    if sd.is_dir():
        for f in sd.glob("*.json"):
            try:
                import json as _json
                d = _json.loads(f.read_text())
                stress_dates.append(str(d.get("run_at") or d.get("results", [{}])[0].get("run_at", ""))[:10])
            except Exception:  # noqa: BLE001
                continue

    def _days_since(iso: str) -> int | None:
        try:
            return (datetime.now(timezone.utc).date() - datetime.fromisoformat(str(iso)[:10]).date()).days
        except (ValueError, TypeError):
            return None

    records = []
    for m in _read_table(reg):
        mid, tier = str(m.get("model_id", "")), str(m.get("risk_tier", "")).strip().lower()
        owner = str(m.get("owner", "")).strip().lower()
        ob = obligations.get(tier) or {}
        mine = [t for t in tickets if str(t.get("model_id", "")) == mid]
        approved = [t for t in mine if str(t.get("approved_at", "")).strip()]
        latest = max(approved, key=lambda t: str(t.get("approved_at")), default=None)

        def add(name, met, detail=""):
            records.append({"model_id": mid, "risk_tier": tier, "obligation": name,
                            "met": bool(met), "detail": detail})

        if "review_cycle_days" in ob:
            d = _days_since(latest.get("approved_at")) if latest else None
            add("review_cycle_days", d is not None and d <= int(ob["review_cycle_days"]),
                f"last approved change {d} days ago, cycle {ob['review_cycle_days']}" if d is not None else "no approved change ticket")
        if ob.get("eval_before_deploy"):
            versions = [str(d_.get("version")) for d_ in deploys if str(d_.get("name", mid)) == mid] or [str(d_.get("version")) for d_ in deploys]
            evaluated = {str(e.get("version")) for e in evals}
            missing = [v for v in versions if v not in evaluated]
            add("eval_before_deploy", not missing and bool(versions),
                f"deployed versions without an eval: {missing}" if missing else f"{len(versions)} deployed version(s) evaluated")
        if ob.get("independent_validation"):
            appr = str((latest or {}).get("approver", "")).strip().lower()
            add("independent_validation", bool(appr) and appr != owner,
                f"latest approver {appr!r} vs model owner {owner!r}")
        if "stress_test_within_days" in ob:
            ds = [x for x in (_days_since(s) for s in stress_dates) if x is not None]
            add("stress_test_within_days", bool(ds) and min(ds) <= int(ob["stress_test_within_days"]),
                f"most recent stress result {min(ds)} days ago" if ds else "no stress-test result found")
        if ob.get("approval_level"):
            add("approval_level_recorded", True, f"policy requires {ob['approval_level']} — human gate")
    return AdapterResult("ok", records, [_hash_file(reg)])


@adapter("policy_history")
def policy_history(target: Path, cfg: dict) -> AdapterResult:
    """Rows from policy/history.csv, each annotated against the policy file actually in force.

    Fields per row: version, sha256, approved_by, approved_on, ticket_id, is_current,
    hash_matches (current row only), ticket_exists, approver_matches_policy, complete.
    The current row is the one whose version equals the policy file's `version`.
    """
    pol = _policy(target, cfg)
    if not pol:
        return AdapterResult("missing", message="policy file not found")
    hp = _resolve(target, cfg.get("history", "policy/history.csv"))
    if not hp.exists():
        return AdapterResult("missing", message=f"{hp} not found — no approval record for the policy in force")
    tickets = _read_table(target / "governance" / "tickets.csv") if (target / "governance" / "tickets.csv").exists() else []
    ticket_ids = {str(t.get("ticket_id", "")).strip() for t in tickets}
    body = str(pol.get("approved_by", "")).strip().lower()
    cur_version, cur_hash = str(pol.get("version", "")).strip(), pol["_sha256"]
    PLACEHOLDERS = {"", "tbd", "reviewer name", "unnamed", "n/a", "none"}

    records = []
    for r in _read_table(hp):
        v = str(r.get("version", "")).strip()
        is_current = v == cur_version
        appr = str(r.get("approved_by", "")).strip()
        rec = {
            "version": v, "is_current": is_current,
            "sha256": str(r.get("sha256", "")).strip(),
            "hash_matches": (str(r.get("sha256", "")).strip() == cur_hash) if is_current else None,
            "approved_by": appr, "approved_on": str(r.get("approved_on", "")).strip(),
            "ticket_id": str(r.get("ticket_id", "")).strip(),
            "ticket_exists": str(r.get("ticket_id", "")).strip() in ticket_ids,
            "approver_named": appr.lower() not in PLACEHOLDERS,
            "approver_matches_policy": appr.lower() == body if body else None,
        }
        rec["complete"] = bool(rec["approver_named"] and rec["ticket_exists"] and rec["approved_on"])
        # the version in force must additionally hash-match: an edited policy is an unapproved policy
        rec["in_force_and_approved"] = bool(is_current and rec["complete"] and rec["hash_matches"])
        rec["current_unapproved"] = bool(is_current and not rec["in_force_and_approved"])
        records.append(rec)

    if not any(r["is_current"] for r in records):
        records.append({"version": cur_version, "is_current": True, "sha256": cur_hash, "hash_matches": False,
                        "approved_by": "", "approved_on": "", "ticket_id": "", "ticket_exists": False,
                        "approver_named": False, "approver_matches_policy": False, "complete": False,
                        "in_force_and_approved": False, "current_unapproved": True,
                        "detail": "the policy version in force has no row in the history register"})
    return AdapterResult("ok", records, [_hash_file(hp), _hash_text(pol["_path"], cur_hash)])
