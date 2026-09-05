"""
Review stage (stage 4). The only code that writes human_verdict.

    list_bundles(dir)                    -> newest-first summaries
    load_bundle(path)                    -> dict
    sign(path, control_id, ...)          -> writes human_verdict, verifies integrity before and after
    control_history(dir, control_id)     -> one control across all bundles
    open_items(dir)                      -> latest bundle's FAIL / NOT_TESTABLE without a human verdict

Integrity: bundle_sha256 excludes human_verdict blocks, so signing never breaks it,
and a mismatch means a machine verdict was edited after the run.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .runner import bundle_hash

DISPOSITIONS = ("ACCEPT", "EXCEPTION_RAISED", "ESCALATE", "REJECT_MACHINE_VERDICT")


def load_bundle(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def integrity_ok(b: dict) -> bool:
    return bundle_hash(b) == b.get("bundle_sha256")


def summarise(b: dict, path: Path) -> dict:
    counts = {"PASS": 0, "FAIL": 0, "NOT_TESTABLE": 0}
    unsigned = 0
    for r in b["results"]:
        counts[r["machine_verdict"]] += 1
        if r["machine_verdict"] != "PASS" and not r.get("human_verdict"):
            unsigned += 1
    return {"path": str(path), "bundle_id": b["bundle_id"], "run_at": b["run_at"], "trigger": b["trigger"],
            "controls": len(b["results"]), **counts, "unsigned": unsigned, "integrity": integrity_ok(b)}


def list_bundles(evidence_dir: Path) -> list[dict]:
    d = Path(evidence_dir) / "bundles"
    if not d.exists():
        return []
    out = [summarise(load_bundle(p), p) for p in d.glob("*.json")]
    return sorted(out, key=lambda s: s["run_at"], reverse=True)


def sign(path: Path, control_id: str, reviewer: str, disposition: str, rationale: str = "", exception_ref: str | None = None) -> dict:
    if disposition not in DISPOSITIONS:
        raise ValueError(f"disposition must be one of {DISPOSITIONS}")
    if not reviewer.strip():
        raise ValueError("reviewer name is required")
    path = Path(path)
    b = load_bundle(path)
    if not integrity_ok(b):
        raise RuntimeError("Bundle integrity check failed; machine results were modified after the run. Refusing to sign.")
    hit = [r for r in b["results"] if r["control_id"] == control_id]
    if not hit:
        raise KeyError(control_id)
    hit[0]["human_verdict"] = {
        "reviewer": reviewer.strip(),
        "signed_at": datetime.now(timezone.utc).isoformat(),
        "disposition": disposition,
        "rationale": rationale.strip(),
        "exception_ref": exception_ref or None,
    }
    assert integrity_ok(b), "signing must not alter machine results"
    path.write_text(json.dumps(b, indent=2, default=str))
    return hit[0]["human_verdict"]


def unsign(path: Path, control_id: str) -> None:
    path = Path(path)
    b = load_bundle(path)
    for r in b["results"]:
        if r["control_id"] == control_id:
            r["human_verdict"] = None
    path.write_text(json.dumps(b, indent=2, default=str))


def control_history(evidence_dir: Path, control_id: str) -> list[dict]:
    rows = []
    for s in list_bundles(evidence_dir):
        b = load_bundle(Path(s["path"]))
        for r in b["results"]:
            if r["control_id"] == control_id:
                hv = r.get("human_verdict") or {}
                rows.append({"run_at": b["run_at"], "trigger": b["trigger"], "machine_verdict": r["machine_verdict"],
                             "detail": r["detail"], "disposition": hv.get("disposition"), "reviewer": hv.get("reviewer"),
                             "bundle": s["path"]})
    return rows


def open_items(evidence_dir: Path) -> list[dict]:
    bs = list_bundles(evidence_dir)
    if not bs:
        return []
    b = load_bundle(Path(bs[0]["path"]))
    return [r for r in b["results"] if r["machine_verdict"] != "PASS" and not r.get("human_verdict")]
