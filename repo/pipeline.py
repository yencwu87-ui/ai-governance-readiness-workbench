"""Pipeline nodes. Each function is one stage; the graph of calls is the governance story.

Lane A — readiness assessment (probabilistic, document-based, LLM under a harness):
  index_folder -> match_controls -> propose -> (human) record_decision -> export_playbook
  propose() never reaches write_back(): the only path to the playbook goes through record_decision().

Lane B — continuous control testing (deterministic, artefact-based, no model):
  run_audit -> [caa.runner: discover -> assert -> bundle] -> (human) sign_result
  The runner never writes human_verdict; sign_result() is the only path to it.

Both lanes end at a named reviewer. Neither lane's automated output is ever recorded as a conclusion.
"""
from __future__ import annotations

import datetime as dt

from assessor import assess
from playbook import write_back
from scanner import Index, scan_documents, scan_environment, signals_for


def index_folder(folder: str, progress=None) -> tuple[Index, list]:
    """Stage 1 — deterministic. Read documents, build the search index, detect environment signals."""
    chunks = scan_documents(folder, progress)
    return Index(chunks), scan_environment(folder)


def match_controls(index: Index, controls: list, min_score: float = 4.0, k: int = 3) -> dict:
    """Stage 2 — deterministic. Best passages per control; controls with no match are left out."""
    out = {}
    for c in controls:
        hits = index.query(c, k=k, min_score=min_score)
        if hits:
            out[c.key] = hits
    return out


def build_evidence(control, hits, signals) -> dict:
    """Assemble the evidence record a control will be assessed on."""
    text = "\n\n".join(f"--- Source: {ch.label} ---\n{ch.text}" for ch, _ in hits)
    sg = signals_for(control, signals)
    if sg:
        text += "\n\n--- Environment signals ---\n" + "\n".join(f"{x.path}: {x.hint}" for x in sg)
    return {"text": text[:20000], "file_name": "", "auto": True, "sources": [ch.path for ch, _ in hits]}


def propose(control, evidence: dict, pdf_bytes: bytes | None = None) -> dict:
    """Stage 3 — probabilistic under a harness. Returns a proposal; records nothing."""
    try:
        return assess(control, evidence.get("text", ""), pdf_bytes, evidence.get("file_name", ""))
    except Exception as e:
        return {"sufficiency": "none", "proposedMaturity": 1, "rationale": f"Assessment failed: {e}", "excerpt": "",
                "gaps": [], "remediation": [], "flags": ["assessor error"], "model": "error"}


def record_decision(proposal: dict, sufficiency: str, maturity: int, note: str, reviewer: str) -> dict:
    """Stage 4 — human. The only function whose output is ever written to the playbook."""
    return {"sufficiency": sufficiency, "maturity": int(maturity), "note": note, "reviewer": reviewer or "Unnamed reviewer",
            "at": dt.datetime.now().isoformat(timespec="seconds"),
            "aiSufficiency": proposal.get("sufficiency"), "aiMaturity": proposal.get("proposedMaturity")}


def gap_analysis(controls: list, proposals: dict, decisions: dict) -> list[dict]:
    """Stage 5a — report. Everything below full, prioritised: none, then no evidence, then partial."""
    rows = []
    for c in controls:
        d, a = decisions.get(c.key), proposals.get(c.key, {})
        r = d["sufficiency"] if d else a.get("sufficiency")
        if r == "full":
            continue
        no_ev = c.key not in proposals
        rows.append({"Priority": 0 if r == "none" else 1 if no_ev else 2, "Control": f"{c.id} {c.title}", "Library": c.lib,
                     "Finding": "not assessed — no evidence located" if no_ev else r + ("" if d else " (proposed, not yet reviewed)"),
                     "Gaps": "; ".join(a.get("gaps", [])) if not no_ev else "No document in the scanned folder matched this control",
                     "Suggested action": "; ".join(a.get("remediation", [])) if a.get("remediation") else ("Produce evidence: " + (c.req[:120] if no_ev else "see gaps")),
                     "Owner": c.owner})
    rows.sort(key=lambda r: r["Priority"])
    return rows


def export_playbook(src, dst: str, controls_by_lib: dict, decisions: dict, proposals: dict, evidence: dict) -> int:
    """Stage 5b — write-back. Only recorded decisions are written."""
    return write_back(src, dst, controls_by_lib, decisions, proposals, evidence)


def run_scan(folder: str, controls: list, min_score: float = 4.0, progress=None) -> tuple[dict, dict]:
    """Headless orchestration of stages 1–3. Returns (evidence, proposals). Never records, never writes back."""
    index, signals = index_folder(folder, progress)
    matches = match_controls(index, controls, min_score=min_score)
    evidence, proposals = {}, {}
    for c in controls:
        if c.key not in matches:
            continue
        evidence[c.key] = build_evidence(c, matches[c.key], signals)
        proposals[c.key] = propose(c, evidence[c.key])
    return evidence, proposals


# ====================================================================
# Lane B — continuous control testing (caa)
# ====================================================================
from pathlib import Path as _Path

from caa import review as _review
from caa.runner import run as _caa_run

CAA_CONFIG, CAA_CONTROLS, CAA_EVIDENCE = _Path("audit.yaml"), _Path("controls"), _Path("evidence")


def run_audit(folder: str, trigger: str = "manual") -> tuple[dict, _Path]:
    """Stage B1–B3 — deterministic. Discover artefacts, run control checks, write a hashed bundle.
    Records nothing a human is accountable for; every result has human_verdict = null."""
    return _caa_run(CAA_CONFIG, CAA_CONTROLS, CAA_EVIDENCE, trigger=trigger, target=_Path(folder))


def list_bundles() -> list[dict]:
    return _review.list_bundles(CAA_EVIDENCE)


def load_bundle(path) -> dict:
    return _review.load_bundle(_Path(path))


def open_items() -> list[dict]:
    return _review.open_items(CAA_EVIDENCE)


def sign_result(bundle_path, control_id: str, reviewer: str, disposition: str, rationale: str = "", exception_ref: str | None = None) -> dict:
    """Stage B4 — human. The only function that writes human_verdict. Refuses if bundle integrity fails."""
    return _review.sign(_Path(bundle_path), control_id, reviewer, disposition, rationale, exception_ref)


def unsign_result(bundle_path, control_id: str) -> None:
    _review.unsign(_Path(bundle_path), control_id)


def control_history(control_id: str) -> list[dict]:
    """Stage B5 — report. One control across every bundle, newest first."""
    return _review.control_history(CAA_EVIDENCE, control_id)
