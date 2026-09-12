"""
Continuous AI audit runner.

    python -m caa.runner --config audit.yaml --controls controls/ --out evidence/ [--trigger on_commit]

Stages:
  1. Discover  — run every adapter named in audit.yaml, produce an inventory
  2. Assert    — run every control in the control pack against the inventory
  3. Bundle    — write inventory + evidence bundle as JSON, hashed, append-only

Stage 4 (Review) is a separate process that reads bundles and fills human_verdict.
The runner never writes human_verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import yaml

from . import checks
from . import adapters as ad
from .policy import gate_for, hash_of, load as load_policy

RUNNER_VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text())


def _git(target: Path, *args) -> str | None:
    import subprocess
    try:
        return subprocess.run(["git", "-C", str(target), *args], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


# ---------- stage 1: discover ----------

def discover(target: Path, config: dict) -> dict:
    sources = {}
    for name, cfg in config.get("sources", {}).items():
        adapter_name = cfg.get("adapter", name)
        fn = ad.REGISTRY.get(adapter_name)
        if fn is None:
            sources[name] = {"adapter": adapter_name, "status": "error", "message": "unknown adapter", "records": [], "artefacts": []}
            continue
        try:
            res = fn(target, cfg.get("args", {}))
        except Exception as e:  # an adapter must never take the run down; a source that errors is NOT_TESTABLE
            sources[name] = {"adapter": adapter_name, "status": "error", "message": f"{type(e).__name__}: {e}"[:300],
                             "records": [], "artefacts": []}
            continue
        sources[name] = {
            "adapter": adapter_name,
            "status": res.status,
            "message": res.message,
            "records": res.records,
            "artefacts": [asdict(a) for a in res.artefacts],
        }
    inv = {
        "inventory_id": str(uuid.uuid4()),
        "generated_at": _now(),
        "target": {"path": str(target), "git_head": _git(target, "rev-parse", "HEAD"), "git_remote": _git(target, "remote", "get-url", "origin")},
        "sources": sources,
    }
    jsonschema.validate(inv, _load_schema("inventory"))
    return inv


# ---------- stage 2: assert ----------

def load_controls(controls_path: Path) -> tuple[list[dict], str]:
    files = sorted(controls_path.glob("*.y*ml")) if controls_path.is_dir() else [controls_path]
    schema = _load_schema("control")
    controls, blob = [], ""
    for f in files:
        text = f.read_text()
        blob += text
        for c in yaml.safe_load(text) or []:
            jsonschema.validate(c, schema)
            controls.append(c)
    return controls, hashlib.sha256(blob.encode()).hexdigest()


def _apply_policy_params(c: dict, policy: dict) -> dict:
    """Substitute {policy: dotted.path} placeholders in params so a threshold lives in one place."""
    from .policy import resolve

    def walk(v):
        if isinstance(v, dict):
            if set(v) == {"policy"}:
                return resolve(policy, v["policy"])
            return {k: walk(x) for k, x in v.items()}
        return [walk(x) for x in v] if isinstance(v, list) else v

    return walk(c.get("params", {})) if policy else c.get("params", {})


def _floor_for(control: dict, policy: dict | None) -> int:
    """Minimum source population a control must have examined before a PASS counts.

    A control that examined nothing and found nothing wrong has not passed — it did not
    run. Resolution is control id, then severity, then 1. Declared in policy rather than
    in the control packs so the floor is hash-bound with the rest of the golden state.
    """
    ef = (policy or {}).get("evidence_floor", {})
    if control["id"] in ef.get("overrides", {}):
        return int(ef["overrides"][control["id"]])
    return int(ef.get("by_severity", {}).get(control.get("severity", "medium"), 1))


def run_controls(controls: list[dict], inventory: dict, trigger: str, policy: dict | None = None) -> list[dict]:
    ctx = {name: s["records"] for name, s in inventory["sources"].items() if s["status"] == "ok"}
    results = []
    for c in controls:
        if trigger != "manual" and not _in_scope(c["frequency"], trigger):
            continue
        fn = checks.REGISTRY[c["check"]]
        try:
            r = fn(ctx, _apply_policy_params(c, policy or {}))
        except Exception as e:  # noqa: BLE001
            r = checks.CheckResult("NOT_TESTABLE", f"check raised {type(e).__name__}: {e}")
        # A pass over too small a population is not a pass. Only PASS is rewritten: a FAIL on a
        # thin population is still a FAIL, and NOT_TESTABLE is already NOT_TESTABLE.
        floor = _floor_for(c, policy)
        # The floor tests in_scope, not examined. examined is the source population BEFORE the
        # scope filter, so a control whose filter empties the population clears the floor on
        # records it never evaluated. Observed 2026-09-10 in one bundle:
        #   MCM-09  PASS          0 of 15 records in scope, all within 7 days
        #   OVS-02  NOT_TESTABLE  examined 0 records, floor is 1 - 0 of 0 records matched
        # Both evaluated nothing; only the one with an empty source was caught. Per the
        # contract in checks.py, in_scope equals examined where there is no scope filter, so
        # this is strictly stronger and never weaker. Verified: no CheckResult sets examined
        # without also setting in_scope.
        if r.verdict == "PASS" and r.in_scope < floor:
            detail = (f"examined {r.examined} records but only {r.in_scope} were in scope, "
                      f"floor is {floor} — {r.detail}") if r.in_scope < r.examined else \
                     f"examined {r.in_scope} records, floor is {floor} — {r.detail}"
            r = checks.CheckResult("NOT_TESTABLE", detail,
                                   examined=r.examined, in_scope=r.in_scope)
        evidence = []
        for inp in c["inputs"]:
            src = inventory["sources"].get(inp["source"])
            for a in (src or {}).get("artefacts", []):
                evidence.append({"source": inp["source"], "ref": a["ref"], "sha256": a["sha256"]})
        results.append({
            "control_id": c["id"],
            "domain": c["domain"],
            "assertion": c["assertion"],
            "framework_refs": c.get("framework_refs", []),
            "play_refs": c.get("play_refs", []),
            "policy_refs": c.get("policy_refs", []),
            "severity": c.get("severity", "medium"),
            "machine_verdict": r.verdict,
            "detail": r.detail,
            "findings": r.findings,
            "examined": r.examined,
            "in_scope": r.in_scope,
            "evidence_floor": floor,
            "evidence": evidence,
            "human_gate": c["human_gate"],
            "human_verdict": None,
        })
    return results


def _in_scope(frequency: str, trigger: str) -> bool:
    # on_commit controls also run on deploy; scheduled runs everything periodic
    if trigger == "on_commit":
        return frequency == "on_commit"
    if trigger == "on_deploy":
        return frequency in ("on_commit", "on_deploy")
    if trigger == "scheduled":
        return frequency in ("daily", "weekly", "monthly", "quarterly")
    return True


# ---------- stage 3: bundle ----------

def bundle(inventory: dict, results: list[dict], controls_path: Path, pack_sha: str, n_controls: int, trigger: str,
           policy: dict | None = None) -> dict:
    b = {
        "bundle_id": str(uuid.uuid4()),
        "run_at": _now(),
        "trigger": trigger,
        "inventory_id": inventory["inventory_id"],
        "runner_version": RUNNER_VERSION,
        "control_pack": {"path": str(controls_path), "sha256": pack_sha, "control_count": n_controls},
        "policy": ({"path": policy["_path"], "version": str(policy.get("version", "")), "sha256": hash_of(policy)} if policy else None),
        "results": results,
    }
    b["bundle_sha256"] = bundle_hash(b)
    jsonschema.validate(b, _load_schema("evidence_bundle"))
    return b


def bundle_hash(b: dict) -> str:
    """Hash everything except bundle_sha256 and human_verdict blocks, so later review does not break integrity."""
    stripped = {k: v for k, v in b.items() if k != "bundle_sha256"}
    stripped["results"] = [{k: v for k, v in r.items() if k != "human_verdict"} for r in b["results"]]
    return _sha(stripped)


def verify_bundle(path: Path) -> bool:
    b = json.loads(path.read_text())
    return bundle_hash(b) == b["bundle_sha256"]


# ---------- entry ----------

def run(config_path: Path, controls_path: Path, out: Path, trigger: str = "manual", target: Path | None = None, return_inventory: bool = False):
    """Library entry point used by pipeline.py. Returns (bundle, bundle_path)."""
    config = yaml.safe_load(Path(config_path).read_text())
    target = Path(target or config.get("target", ".")).resolve()
    out = Path(out)
    (out / "inventories").mkdir(parents=True, exist_ok=True)
    (out / "bundles").mkdir(parents=True, exist_ok=True)

    policy_path = target / "policy" / "ai-lifecycle.yaml"
    policy = load_policy(policy_path)
    if not policy:
        # Fail closed. Every path that depends on the policy degrades silently and in the
        # permissive direction when it is absent:
        #   _floor_for()          -> evidence floor falls back to 1, so a control that
        #                            examined one record passes
        #   gate_for()            -> fail_on defaults to "none", so nothing blocks
        #   _apply_policy_params()-> {policy: dotted.path} placeholders pass through
        #                            unresolved, and the check compares against a dict
        # A bundle produced without a policy is indistinguishable from a governed one when
        # read later, which is worse than no bundle at all.
        raise SystemExit(
            f"No policy at {policy_path}.\n"
            f"Refusing to run: without it the evidence floor defaults to 1, gates default to "
            f"fail_on=none, and policy-derived thresholds pass through unresolved. The bundle "
            f"would look governed and would not be.\n"
            f"Either add a policy to the target, or point --target at a repository that has one."
        )
    inv = discover(target, config)
    controls, pack_sha = load_controls(Path(controls_path))
    results = run_controls(controls, inv, trigger, policy)
    b = bundle(inv, results, Path(controls_path), pack_sha, len(controls), trigger, policy)

    stamp = b["run_at"].replace(":", "").replace("+0000", "Z")
    (out / "inventories" / f"{stamp}_{inv['inventory_id'][:8]}.json").write_text(json.dumps(inv, indent=2, default=str))
    bpath = out / "bundles" / f"{stamp}_{b['bundle_id'][:8]}.json"
    bpath.write_text(json.dumps(b, indent=2, default=str))
    return (b, bpath, inv, policy) if return_inventory else (b, bpath)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Continuous AI audit runner")
    ap.add_argument("--config", default="audit.yaml")
    ap.add_argument("--controls", default="controls")
    ap.add_argument("--out", default="evidence")
    ap.add_argument("--target", default=None, help="Override target folder from audit.yaml")
    ap.add_argument("--trigger", default="manual", choices=["manual", "on_commit", "on_deploy", "scheduled"])
    ap.add_argument("--fail-on", default=None, choices=["none", "critical", "high", "any"],
                    help="Override the policy's gate for this trigger (recorded in the run output)")
    a = ap.parse_args(argv)
    b, bpath, inv, policy = run(Path(a.config), Path(a.controls), Path(a.out), a.trigger, a.target, return_inventory=True)
    _print_summary(b, bpath, inv)
    fail_on, require_pass = gate_for(policy, a.trigger, a.fail_on)
    if policy:
        src = "CLI override" if a.fail_on else f"policy v{policy.get('version')}"
        print(f"gate: fail_on={fail_on} ({src})" + (f", require_pass={', '.join(require_pass)}" if require_pass else ""))
    inconclusive_on = str(((policy or {}).get("gates", {}).get(a.trigger) or {})
                          .get("inconclusive_on", "none"))
    if policy and inconclusive_on != "none":
        print(f"gate: inconclusive_on={inconclusive_on}")
    return _exit_code(b["results"], fail_on,
                      _excepted_controls(inv, b["results"], policy), require_pass,
                      inconclusive_on)

def _print_summary(b: dict, path: Path, inventory: dict | None = None):
    counts = {"PASS": 0, "FAIL": 0, "NOT_TESTABLE": 0}
    for r in b["results"]:
        counts[r["machine_verdict"]] += 1
    print(f"\nBundle {b['bundle_id'][:8]}  trigger={b['trigger']}  controls={len(b['results'])}")
    print(f"  PASS {counts['PASS']}   FAIL {counts['FAIL']}   NOT_TESTABLE {counts['NOT_TESTABLE']}\n")
    for r in b["results"]:
        flag = {"PASS": "  ", "FAIL": "!!", "NOT_TESTABLE": "??"}[r["machine_verdict"]]
        print(f"{flag} {r['control_id']:<8} {r['machine_verdict']:<13} {r['detail']}")
    bad = {n: s.get("message", "") for n, s in ((inventory or {}).get("sources") or {}).items() if s["status"] == "error"}
    if bad:
        print("\nSources in error (their controls are NOT_TESTABLE):")
        for n, m in bad.items():
            print(f"  {n}: {m}")
    print(f"\nWritten: {path}\nbundle_sha256: {b['bundle_sha256']}")


def _excepted_controls(inventory: dict, results: list[dict], policy: dict | None) -> dict[str, str]:
    """control_id -> exception_id for open, unexpired rows in the exception register.

    Controls whose severity is listed in gates.non_waivable are never exempt. An
    exception is a documented acceptance of a known gap, and the policy declares
    some gaps unacceptable however well documented. A register row naming one is a
    policy error, so it raises rather than being ignored — an inert exception row
    still reads as coverage to anyone reviewing the register.
    """
    src = inventory["sources"].get("exception_register", {})
    non_waivable = set((policy or {}).get("gates", {}).get("non_waivable", []))
    severity = {r["control_id"]: r.get("severity") for r in results}
    if src.get("status") != "ok":
        return {}
    today = datetime.now(timezone.utc).date().isoformat()
    out, refused = {}, []
    for r in src["records"]:
        cid = str(r.get("control_id", "")).strip()
        if not (str(r.get("status", "")).strip().lower() == "open"
                and str(r.get("expires_on", "")) >= today and cid):
            continue
        if severity.get(cid) in non_waivable:
            refused.append((r.get("exception_id", ""), cid, severity.get(cid)))
            continue
        out[cid] = str(r.get("exception_id", ""))
    if refused:
        rows = ", ".join(f"{e} -> {c} ({s})" for e, c, s in refused)
        raise ValueError(f"exception register names non-waivable control(s): {rows}")
    return out


def _exit_code(results: list[dict], fail_on: str, excepted: dict[str, str] | None = None,
               require_pass: list[str] | None = None, inconclusive_on: str = "none") -> int:
    """Non-zero if any FAIL at or above the severity floor that is not covered by an open exception,
    if any control the policy requires to pass did not pass, or if any control at or above
    inconclusive_on could not be tested. require_pass is not exception-exempt: the policy names
    those controls precisely because they gate the action.

    A control that could not be tested has not passed. Treating NOT_TESTABLE as silence is how four
    high-severity governance controls reported green on 2026-09-06 having tested nothing at all."""
    excepted = excepted or {}
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    inconclusive = []
    if inconclusive_on != "none":
        ifloor = {"any": 0, "high": 2, "critical": 3}[inconclusive_on]
        inconclusive = [r for r in results if r["machine_verdict"] == "NOT_TESTABLE"
                        and rank[r["severity"]] >= ifloor and r["control_id"] not in excepted]
        if inconclusive:
            print("\nGATE: could not be tested at or above " + inconclusive_on + ": "
                  + ", ".join(r["control_id"] for r in inconclusive))
    must = [r for r in results if r["control_id"] in (require_pass or []) and r["machine_verdict"] != "PASS"]
    if must:
        print(f"\nGATE: policy requires these to pass: {', '.join(r['control_id'] + '=' + r['machine_verdict'] for r in must)}")
    if fail_on == "none":
        return 1 if (must or inconclusive) else 0
    floor = {"any": 0, "high": 2, "critical": 3}[fail_on]
    blocking = [r for r in results if r["machine_verdict"] == "FAIL" and rank[r["severity"]] >= floor and r["control_id"] not in excepted]
    if blocking:
        print(f"\nGATE: blocked by {', '.join(r['control_id'] for r in blocking)}")
    covered = [r["control_id"] for r in results if r["machine_verdict"] == "FAIL" and r["control_id"] in excepted]
    if covered:
        print("GATE: FAIL covered by open exception: " + ", ".join(f"{c} ({excepted[c]})" for c in covered))
    return 1 if (blocking or must or inconclusive) else 0


if __name__ == "__main__":
    sys.exit(main())
