"""Policy as code: load policy/ai-lifecycle.yaml, expose it to the runner, render POLICY.md.

    from caa.policy import load, gate_for, hash_of
    python -m caa.policy render          # writes POLICY.md next to the policy file

The policy declares the golden state and the gate rules; controls test them. Nothing here makes a
judgement — it resolves numbers and lists that would otherwise be hard-coded in ten places.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import yaml

DEFAULT_PATH = Path("policy/ai-lifecycle.yaml")


def load(path: Path | str = DEFAULT_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    d = yaml.safe_load(p.read_text()) or {}
    d["_path"], d["_sha256"] = str(p), hashlib.sha256(p.read_bytes()).hexdigest()
    return d


def hash_of(policy: dict) -> str:
    return policy.get("_sha256", "")


def gate_for(policy: dict, trigger: str, cli_fail_on: str | None = None) -> tuple[str, list[str]]:
    """Gate rules come from the policy; an explicit --fail-on on the CLI still wins (and is recorded)."""
    g = (policy.get("gates") or {}).get(trigger, {})
    return (cli_fail_on or g.get("fail_on", "none")), list(g.get("require_pass") or [])


def resolve(policy: dict, dotted: str, default=None):
    """resolve(p, 'cadence.rollback_test_days') -> 180"""
    cur = policy
    for part in dotted.split("."):
        if isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


# ---------- POLICY.md renderer ----------

def render(policy: dict, controls: list[dict]) -> str:
    by_ref: dict[str, list[str]] = {}
    for c in controls:
        for ref in c.get("policy_refs", []) or []:
            by_ref.setdefault(ref, []).append(c["id"])
    ctl = lambda ref: ", ".join(sorted(by_ref.get(ref, []))) or "—"

    gs, ev = policy.get("golden_state", {}), policy.get("golden_state", {}).get("evaluation", {})
    inf = gs.get("inference", {})
    L = [f"# {policy.get('policy')} — policy v{policy.get('version')}", "",
         f"**Owner** {policy.get('owner')} · **Approved by** {policy.get('approved_by')} · "
         f"**Effective** {policy.get('effective')} · **Policy hash** `{hash_of(policy)[:16]}`", "",
         "> Generated from `policy/ai-lifecycle.yaml`. Do not edit by hand — edit the policy and re-render, "
         "so the approved policy and the enforced gate cannot drift apart.", "",
         f"**Scope.** {policy.get('scope', '').strip()}", "",
         "## 1. Golden state", "",
         "| Clause | Requirement | Enforced by |", "|---|---|---|",
         f"| Inference residency | {inf.get('residency')}; providers {', '.join(inf.get('allowed_providers', []))}; "
         f"any locally-served model permitted | {ctl('inference.residency')} |",
         f"| Non-local providers | {', '.join(p['provider'] for p in inf.get('provider_exceptions', []))} permitted only under a "
         f"registered, unexpired exception | {ctl('inference.provider_exceptions')} |",
         f"| Dependencies | pinned in `{gs.get('dependencies', {}).get('lockfile')}` | {ctl('dependencies.pinned')} |",
         f"| Artefacts, all models | {', '.join(gs.get('required_artefacts', {}).get('all', []))} | {ctl('required_artefacts.all')} |",
         f"| Artefacts, high tier | {', '.join(gs.get('required_artefacts', {}).get('high', []))} | {ctl('required_artefacts.high')} |",
         f"| Evaluation | golden set ≥ {ev.get('golden_set_min_items')} items; run before deploy | {ctl('evaluation.run_before_deploy')} |",
         f"| Segregation of duties | approver is not the author | {ctl('segregation_of_duties.approver_not_author')} |", "",
         "## 2. Gates", "", "| Trigger | Blocks on | Must pass |", "|---|---|---|"]
    for trig, g in (policy.get("gates") or {}).items():
        L.append(f"| {trig} | FAIL at severity {g.get('fail_on')} or above, not covered by an exception | "
                 f"{', '.join(g.get('require_pass') or []) or '—'} |")
    exc, cad, ov = policy.get("exceptions", {}), policy.get("cadence", {}), policy.get("oversight", {})
    L += ["", "## 3. Exceptions", "",
          f"An exception exempts a control from the gate. Maximum life {exc.get('max_days')} days. "
          f"Required fields: {', '.join(exc.get('requires', []))}. Re-tabled at the {exc.get('re_table_at')}. "
          f"Enforced by {ctl('exceptions.max_days')}.", "",
          "## 4. Cadence", "", "| Activity | Limit |", "|---|---|",
          f"| Stress test | per tracker cadence ({', '.join(f'{k} {v}d' for k, v in (cad.get('stress_test_days') or {}).items())}) |",
          f"| Rollback test | every {cad.get('rollback_test_days')} days |",
          f"| Emergency change closed | within {cad.get('emergency_change_close_days')} days |", "",
          "## 5. Human oversight", "",
          f"A named reviewer records every decision. AI may: {', '.join(ov.get('ai_may', []))}. "
          f"AI may not: {', '.join(ov.get('ai_may_not', []))}. "
          f"Reviewer override rate of AI proposals is monitored within "
          f"{int(ov.get('override_rate_band', [0, 1])[0] * 100)}–{int(ov.get('override_rate_band', [0, 1])[1] * 100)}%; "
          f"outside that band is a finding, not a target. Enforced by {ctl('oversight.reviewer_required')}, "
          f"{ctl('oversight.override_rate_band')}.", "",
          "## 6. Controls enforcing this policy", "", "| Control | Policy clause |", "|---|---|"]
    for c in sorted(controls, key=lambda c: c["id"]):
        if c.get("policy_refs"):
            L.append(f"| {c['id']} {c['assertion'][:70]} | {', '.join(c['policy_refs'])} |")
    L += ["", f"Controls with no policy clause test operating discipline rather than the golden state; "
              f"see `controls/*.yaml`.", ""]
    return "\n".join(L)


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv or argv[0] != "render":
        print("usage: python -m caa.policy render [policy_path] [controls_dir]"); return 2
    ppath = Path(argv[1]) if len(argv) > 1 else DEFAULT_PATH
    cdir = Path(argv[2]) if len(argv) > 2 else Path("controls")
    policy = load(ppath)
    if not policy:
        print(f"no policy at {ppath}"); return 1
    controls = [c for f in sorted(cdir.glob("*.y*ml")) for c in (yaml.safe_load(f.read_text()) or [])]
    out = ppath.parent / "POLICY.md"
    out.write_text(render(policy, controls))
    print(f"wrote {out} ({len(controls)} controls, policy {hash_of(policy)[:16]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
