"""WB-042 — the assessment cycle as a library.

Until now the cycle existed only as control flow inside `app.py`, interleaved with Streamlit
widgets. `run_scan.py` stopped at proposals; blind read, compare, challenge and decide were
reachable only by a person clicking. That was the ceiling on everything else — a continuous
audit cannot be scheduled, replayed, exposed as an API or driven from CI if its middle is a UI.

Nothing here re-implements assessment. It orchestrates the existing modules — `pipeline.propose`,
`compare.compare`, `challenge.challenge_disagreement`, `reasons.reason_error` — and writes each
step to the append-only event store. The deterministic constraints all still live where they
were, which is the layer that was already right.

Two invariants this module enforces, both of which were previously enforced by the shape of the
UI rather than by code — and a UI is not a control:

  blindness    `proposal_for_reviewer()` returns nothing until a read is recorded. The proposal
               can be computed at any time, including hours earlier in a batch: blindness is
               about what the reviewer was shown, not when the call was made. A caller that
               wants the proposal regardless must ask for it explicitly through
               `state()["proposal"]`, which is an auditable choice rather than an accident.

  reasons      `decide()` runs the same `reasons.reason_error` check the UI runs. The hollow
               record — 47 accepts to 4 amends, every reason reading "accept" — happened because
               agreement was one click. A headless path with no reason check would reproduce it
               at machine speed.

No module below this one imports Streamlit. That is the test of whether the extraction worked.
"""
from __future__ import annotations

from typing import Any

import events
import llm
from governance.observation import declare_observation_envelope

declare_observation_envelope("reviewer_read")

__all__ = ["start", "bind_evidence", "rebind_evidence", "gap_scan", "check_bundle_unchanged",
           "assess", "record_proposal", "challenge_read", "record_challenge", "record_note",
           "contract_status", "assert_contract_executable",
           "record_compare", "record_observation",
           "record_read",
           "proposal_for_reviewer", "compare_reads", "challenge", "decide", "state",
           "open_cycles"]


class CycleError(RuntimeError):
    """A step was attempted out of order, or on a cycle that cannot support it."""


def _control(control_id: str, framework: str = ""):
    from playbook import load_controls
    import glob
    wb = sorted(glob.glob("data/*.xlsx"))
    if not wb:
        raise CycleError("no playbook workbook found in data/")
    for lib, controls in load_controls(wb[0]).items():
        if framework and lib != framework:
            continue
        for c in controls:
            if c.id == control_id:
                return c
    raise CycleError(f"control {control_id} not found"
                     + (f" in {framework}" if framework else ""))


# ---------------------------------------------------------------- cycle lifecycle

def start(control_id: str, *, framework: str = "", actor: str = "system") -> str:
    c = _control(control_id, framework)
    cid = events.new_cycle_id(control_id)
    events.append("cycle_started", cycle_id=cid, actor=actor, control_id=control_id,
                  framework=c.lib, payload={"title": c.title})
    return cid


def bind_evidence(cycle_id: str, evidence: dict, *, actor: str = "system") -> dict:
    """Attach the evidence bundle. Recorded before assessment so that what the model was given
    is part of the record, not reconstructed from what it said afterwards."""
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    return events.append("evidence_bound", cycle_id=cycle_id, actor=actor,
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload=evidence)


def gap_scan(cycle_id: str, chunks=None, *, actor: str = "system") -> dict:
    """WB-103 — deterministic completeness pass over the bound evidence.

    Runs before the reviewer's blind read, and safe to show them, because it produces no rating
    and no element verdict: only which declared artefacts have no candidate document. A list of
    what is missing cannot anchor a reader the way a proposed sufficiency can — there is no
    verdict to agree with.

    No model is called. See governance/completeness.py for why this is a matching rule rather
    than a judgement.
    """
    from governance.completeness import scan, hash_chunks
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    ev = s.get("evidence") or {}
    if chunks is None:
        chunks = ev.get("chunks") or []
    c = _control(s["control_id"], s.get("framework", ""))
    result = scan(c, chunks)
    result["bundle_hash_at_scan"] = hash_chunks(chunks)
    events.append("gap_scanned", cycle_id=cycle_id, actor=actor, control_id=s["control_id"],
                  framework=s.get("framework", ""), payload={"completeness": result})
    return result


def rebind_evidence(cycle_id: str, evidence: dict, *, actor: str, reason: str = "") -> dict:
    """Re-bind after the reviewer topped up the bundle in response to the gap scan.

    Two things this records that a silent re-bind would lose.

    First, the bundle assessed must be the bundle the blind read and the challenge saw. Without
    an explicit re-bind those three steps can attack different objects and nothing in the record
    would show it.

    Second, a bundle assembled against a checklist is not an independent sample of what the
    organisation had. `evidence_added_after_gap_scan` marks it, for the same reason label.py
    records `assessor_shown`: the number is still usable, but it is no longer usable as eval
    material, and the record has to say which it is rather than leaving a later reader to guess.
    """
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not actor or not str(actor).strip():
        raise CycleError("a re-bind must name who added the evidence")
    if s.get("read"):
        raise CycleError("the reviewer has already recorded a read — topping up the bundle now "
                         "would leave that read attached to evidence it never saw. Start a new "
                         "cycle rather than editing the object under an existing reading")
    payload = dict(evidence)
    payload["evidence_added_after_gap_scan"] = bool(s.get("completeness"))
    payload["rebind_reason"] = str(reason or "")
    payload["supersedes_bundle_hash"] = (s.get("evidence") or {}).get("bundle_hash")
    return events.append("evidence_bound", cycle_id=cycle_id, actor=actor,
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload=payload)


def contract_status(control_id: str, framework: str = "", *, source_path=None) -> dict:
    """Integrity status for one control. The UI's only route to it.

    `app.py` calls this and renders the verdict. It does not assemble a contract, does not know
    which checks exist, and does not decide what blocks — the same shape the predicate engine
    will use later, where the app asks `evaluate(control_id, scope)` and receives a ControlResult
    without learning what a predicate is.
    """
    from governance.contract_integrity import status_for_control
    c = _control(control_id, framework)
    return status_for_control(c, source_path=source_path)


def assert_contract_executable(control_id: str, framework: str = "") -> dict:
    """Raise `ContractInvalid` unless the contract is sound.

    GE-110. Enforced here rather than in the UI, because a gate the caller has to remember is a
    gate that holds until someone adds a second caller. `app.py` renders the block; this makes it
    true whether or not it does.
    """
    from governance.contract_integrity import ContractInvalid, status_for_control
    c = _control(control_id, framework)
    report = status_for_control(c)
    if not report["executable"]:
        raise ContractInvalid(report)
    return report


def check_bundle_unchanged(cycle_id: str, evidence: dict | None = None) -> None:
    """Raise if the bundle moved after the completeness scan without a recorded re-bind.

    Public, and separate from `assess()`, because `app.py` does not call `assess()` — it computes
    the proposal itself and writes a `proposed` event directly. A guard that lives only inside
    the library function the UI skips is a guard the UI does not have, which is the same class of
    mistake as enforcing blindness by screen order. Call this at any point that is about to
    record a proposal.
    """
    from governance.completeness import hash_chunks, chunks_from_evidence
    s = events.state(cycle_id)
    if not s:
        return
    ev = evidence if evidence is not None else (s.get("evidence") or {})
    scanned = (s.get("completeness") or {}).get("bundle_hash_at_scan")
    if not scanned:
        return
    chunks = ev.get("chunks") or chunks_from_evidence(ev)
    current = ev.get("bundle_hash") or hash_chunks(chunks)
    if current != scanned and not ev.get("evidence_added_after_gap_scan"):
        raise CycleError(
            "the evidence bundle changed after the completeness scan without a recorded "
            "re-bind — call rebind_evidence() so the record shows which bundle each step saw")


def assess(cycle_id: str, *, actor: str = "assessor") -> dict:
    """Run the assessor over the bound evidence under the `assess` role's model."""
    from pipeline import is_error, propose
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    ev = s.get("evidence")
    if not ev:
        raise CycleError("bind evidence before assessing — an assessment with no recorded "
                         "evidence cannot be reproduced or replayed")
    assert_contract_executable(s["control_id"], s.get("framework", ""))
    check_bundle_unchanged(cycle_id)
    c = _control(s["control_id"], s.get("framework", ""))
    with llm.model_for("assess") as model:
        with llm.observe("assess", cycle_id=cycle_id, control_id=s["control_id"]) as m:
            proposal = propose(c, ev)
            m["ok"] = not is_error(proposal)
            m["error"] = proposal.get("error") if not m["ok"] else None
    events.append("proposed", cycle_id=cycle_id, actor=actor, control_id=s["control_id"],
                  framework=s.get("framework", ""),
                  payload={"proposal": proposal, "model": model,
                           "assessment_identity": ev.get("assessment_identity")})
    return proposal


def record_proposal(cycle_id: str, proposal: dict, *, model: str | None = None,
                    assessment_identity: dict | None = None, actor: str = "assessor") -> dict:
    """Record a proposal the caller already computed.

    GE-109. `assess()` both runs the assessor and writes the result, which the UI cannot use —
    it runs `propose()` on a background thread so the reviewer is never blocked, and only has a
    finished proposal to hand. Before this, the UI wrote the `proposed` event itself, which meant
    it skipped every guard `assess()` applies. Two of them matter:

      * a failed call is not a proposal. `propose()` returns `status: "error"` with no
        sufficiency rather than manufacturing a `none` (WB-021), and writing that to the ledger
        would record a rating the assessor never made.
      * the bundle must not have moved since the completeness scan (WB-103), or the proposal is
        about an object nothing else in the cycle saw.

    This is the write half of `assess()` with both guards, and nothing else.
    """
    from pipeline import is_error
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not isinstance(proposal, dict) or not proposal:
        raise CycleError("a proposal must be a non-empty record")
    if is_error(proposal):
        raise CycleError("the assessor call failed — a failed call is not a proposal and is not "
                         "recorded as one. Surface the error to the reviewer instead")
    assert_contract_executable(s["control_id"], s.get("framework", ""))
    check_bundle_unchanged(cycle_id)
    return events.append("proposed", cycle_id=cycle_id, actor=actor,
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload={"proposal": proposal,
                                  "model": model or proposal.get("model"),
                                  "assessment_identity": assessment_identity})


def challenge_read(cycle_id: str, *, actor: str = "challenger") -> dict:
    """First-pass challenge: attack the reviewer's own reading.

    Distinct from `challenge()`, which is the second pass and is scoped to the disagreement
    between the two reads. This one needs only a recorded read, and refuses without one — a
    challenge against a reading nobody has written down has nothing to attack.
    """
    from challenge import challenge as challenge_reading
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    read = s.get("read")
    if not read:
        raise CycleError("no reviewer read recorded — this pass attacks your reading, so there "
                         "must be a reading to attack")
    c = _control(s["control_id"], s.get("framework", ""))
    ev_text = (s.get("evidence") or {}).get("text", "")
    with llm.model_for("challenge") as model:
        with llm.observe("challenge", cycle_id=cycle_id, control_id=s["control_id"]):
            out = challenge_reading(c, ev_text, read)
    out["model"] = out.get("model") or model
    return out


def record_challenge(cycle_id: str, record: dict, *, actor: str = "challenger") -> dict:
    """Write a challenge pass to the ledger.

    Separate from running it, because the UI decorates the challenger's return with dossier and
    display fields before it is stored. The one thing this refuses is an empty record: a pass
    that produced nothing must still say which of the three it was (ran clean, blocked, never
    ran), and a bare `{}` says none of them.
    """
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not isinstance(record, dict) or not record:
        raise CycleError("an empty challenge record cannot be written — a pass that produced "
                         "nothing still has to record whether it ran, was blocked, or found "
                         "nothing")
    return events.append("challenged", cycle_id=cycle_id, actor=actor,
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload=record)


def record_note(cycle_id: str, payload: dict, *, actor: str) -> dict:
    """A reviewer annotation on an existing cycle — currently challenge responses.

    Notes carry no rating and gate nothing, but they are attributable, so a named actor is
    required for the same reason `decide()` requires one.
    """
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not actor or not str(actor).strip():
        raise CycleError("a note must name who wrote it")
    if not isinstance(payload, dict) or not payload:
        raise CycleError("an empty note is not a record of anything")
    return events.append("note", cycle_id=cycle_id, actor=str(actor).strip(),
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload=payload)


def record_read(cycle_id: str, read: dict, *, actor: str) -> dict:
    """Record the reviewer's own reading.

    Accepts `element_verdicts` as [{element_id, status}] or as {element_id: status}; both are
    normalised by `compare`. A read with no element verdicts is allowed and will simply compare
    on the rating alone — recorded honestly as unset rather than refused, because refusing would
    push a reviewer toward filling boxes to get past a gate.
    """
    if not actor or not str(actor).strip():
        raise CycleError("a read must name its reviewer — an unattributed read is not a read")
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not read.get("sufficiency"):
        raise CycleError("a read must state a sufficiency")
    return events.append("read", cycle_id=cycle_id, actor=actor, control_id=s["control_id"],
                         framework=s.get("framework", ""), payload={"read": read})


def proposal_for_reviewer(cycle_id: str) -> dict | None:
    """The proposal, or None while no read has been recorded.

    This is the blindness control expressed as code rather than as screen order.
    """
    s = events.state(cycle_id)
    if not s.get("read"):
        return None
    return s.get("proposal")


def compare_reads(cycle_id: str, *, actor: str = "system") -> dict:
    from compare import compare
    s = events.state(cycle_id)
    if not s.get("read"):
        raise CycleError("no reviewer read recorded — there is nothing to compare against")
    if not s.get("proposal"):
        raise CycleError("no proposal recorded — run assess() first")
    c = _control(s["control_id"], s.get("framework", ""))
    diff = compare(s["read"], s["proposal"], c)
    events.append("compared", cycle_id=cycle_id, actor=actor, control_id=s["control_id"],
                  framework=s.get("framework", ""), payload={"diff": diff})
    return diff


def record_compare(cycle_id: str, diff: dict, *, actor: str = "system") -> dict:
    """Write a comparison the caller already computed.

    `compare_reads()` computes and writes; the UI computes the diff inline while rendering and
    only needs the write. The guard that matters is the one `compare.compare` already encodes and
    the UI had no reason to re-check: a diff must say whether it is comparable. An incomparable
    diff is still recorded — NOT_COMPARABLE is a result — but a diff missing the field entirely
    is not a comparison, it is a dict.
    """
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not isinstance(diff, dict) or "comparable" not in diff:
        raise CycleError("a comparison must record whether the two reads were comparable")
    return events.append("compared", cycle_id=cycle_id, actor=actor,
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload={"diff": diff})


def challenge(cycle_id: str, *, actor: str = "challenger") -> dict:
    """Second-pass challenge, scoped to the disagreement, under the challenge role's model."""
    from challenge import challenge_disagreement
    s = events.state(cycle_id)
    diff = s.get("diff")
    if not diff:
        raise CycleError("run compare_reads() first — this pass attacks the disagreement, "
                         "not either read on its own")
    if not diff.get("comparable"):
        raise CycleError(f"not comparable: {diff.get('reason')}")
    if not diff.get("disagreements"):
        raise CycleError("the reviewer and the assessor agree on every compared element — "
                         "there is nothing for this pass to attack")
    c = _control(s["control_id"], s.get("framework", ""))
    ev_text = (s.get("evidence") or {}).get("text", "")
    with llm.model_for("challenge_disagreement") as model:
        with llm.observe("challenge_disagreement", cycle_id=cycle_id, control_id=s["control_id"]):
            out = challenge_disagreement(c, ev_text, s["read"], s["proposal"], diff)
    out["model"] = out.get("model") or model
    events.append("challenged", cycle_id=cycle_id, actor=actor, control_id=s["control_id"],
                  framework=s.get("framework", ""), payload=out)
    return out


def _last_challenge_run(state: dict) -> dict:
    """The most recent challenge envelope for this cycle, or {} if the pass never ran.

    `state["challenges"]` is a list of whole challenger returns, each carrying its own
    `validation_status`. An envelope with `challenges: []` and `validation_status: "blocked"`
    is a pass that produced nothing admissible; that is not the same fact as a pass that ran
    cleanly and had nothing to say, and only this envelope distinguishes them.
    """
    rows = [x for x in (state.get("challenges") or []) if isinstance(x, dict)]
    return rows[-1] if rows else {}


def decide(cycle_id: str, *, sufficiency: str, maturity: int, reason: str, reviewer: str,
           action: str = "accept") -> dict:
    """Close the cycle. The only step that produces a governance outcome.

    The reason is checked by the same rule the UI applies. A headless path that skipped it would
    reproduce the hollow record at machine speed, which is worse than not having the path.
    """
    from reasons import reason_error
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not reviewer or not str(reviewer).strip():
        raise CycleError("a decision must name its reviewer")
    blind = s.get("read") or {}
    revised = bool(blind) and (blind.get("sufficiency") != sufficiency
                               or blind.get("maturity") != maturity)
    err = reason_error(reason, rating=sufficiency, revised=revised)
    if err:
        raise CycleError(f"reason refused: {err}")

    # v0.8: the human remains the decision authority, but the engine compiles the
    # governed evidence/challenge/falsification state and blocks only hard conflicts.
    from governance.decision_engine import evaluate as evaluate_governance
    prior_states = [x for x in events.iter_states() if x.get("control_id") == s["control_id"]
                    and x.get("cycle_id") != cycle_id and x.get("stage") == "decided"]
    governed = evaluate_governance(
        control_id=s["control_id"],
        reviewer_decision={"action": action, "sufficiency": sufficiency, "maturity": int(maturity), "reason": reason.strip()},
        claims=(s.get("claim_register") or {}).get("claims") or s.get("claims") or [],
        challenges=s.get("challenges") or [],
        probes=(s.get("falsification_engine") or {}).get("probes") or [],
        proposed=s.get("proposal"), reviewer_read=blind, history=prior_states,
        # WB-102: pass the challenger's envelope, not only its rows, so the engine can tell a
        # pass that found nothing from a pass whose output was rejected in validation.
        challenge_run=_last_challenge_run(s),
    )
    # Hard policy is enforced at the API boundary, outside prompts and UI.
    from governance.decision_engine import enforce as enforce_governance
    enforce_governance(governed)

    payload: dict[str, Any] = {
        "action": action, "sufficiency": sufficiency, "maturity": int(maturity),
        "governance_decision": governed,
        "reason": reason.strip(), "assessor_shown": bool(s.get("proposal")),
        "challenged": bool(s.get("challenges")), "revised_after_assessor": revised and bool(s.get("proposal")),
        "revised_after_compare": revised and bool(s.get("diff")),
        "revised_after_challenge": revised and bool(s.get("challenges")),
        "assessment_identity": s.get("assessment_identity"),
    }
    if revised and blind:
        payload["supersedes"] = {k: blind.get(k) for k in ("sufficiency", "maturity", "reason")}
    if s.get("diff"):
        d = s["diff"]
        payload["element_diff"] = {"summary": d.get("summary"), "rating": d.get("rating"),
                                   "disagreements": d.get("disagreements"),
                                   "diff_sha": d.get("diff_sha")}
    events.append("decided", cycle_id=cycle_id, actor=reviewer, control_id=s["control_id"],
                  framework=s.get("framework", ""), payload=payload)
    return payload


# ---------------------------------------------------------------- views

def state(cycle_id: str) -> dict:
    return events.state(cycle_id)


def open_cycles() -> list[dict]:
    return [s for s in events.iter_states() if s.get("stage") != "decided"]


def record_observation(observation: dict, *, actor: str = "plugin", control_id: str = "",
                       framework: str = "") -> dict:
    """Record a globally scoped plugin observation before it is bound to any assessment cycle.

    `control_id` and `framework` are optional overrides for a caller that already knows which
    control it collected against. Without them the values are read off the observation itself,
    which is the right default for a provider sweep that is not yet attached to any control.
    """
    if not isinstance(observation, dict) or not observation:
        raise CycleError("an empty observation records nothing")
    return events.append("observed", cycle_id="", actor=actor,
                         control_id=(str(control_id).strip()
                                     or str((observation.get("resource") or "")).strip()),
                         framework=(str(framework).strip()
                                    or str((observation.get("provider") or "")).strip()),
                         payload={"observation": observation})
