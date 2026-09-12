"""WB-030 — end-to-end test of the second challenge pass with the model stubbed out.

The unit tests cover `scope_filter` and `_normalise_supports` in isolation. This exercises the
whole of `challenge_disagreement()` — prompt build, model call, JSON parse, the full
`_validate_structured` chain, the scope drop, the supports rule and the outcome recomputation —
by replacing only the transport. Nothing here needs Ollama, an API key or a network.

That matters because the expensive failures in this path are integration failures: a valid
challenge rejected by a pointer check, or an out-of-scope one surviving validation.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import challenge as CH  # noqa: E402

# A real MAS control with real contract elements — the requirement_pointer check resolves
# against requirements/mas.yaml, so an invented element id would be rejected.
CONTROL_ID = "M3.12"
E2_TEXT = "Change records link approval, implementation and the deployed system/version."

EVIDENCE = """Change management extract, Q1.
CHG-4471 approved 14 March 09:12 by the change authority.
Deployment log records release of pricing-model v3 at 13 March 22:40.
All changes in the period were raised in the register."""

QUOTE = "Deployment log records release of pricing-model v3 at 13 March 22:40."

BLIND = {"sufficiency": "full", "maturity": 4, "reason": "records link approval to the release",
         "element_verdicts": [{"element_id": "e2", "status": "met"}]}
AI = {"sufficiency": "partial", "proposedMaturity": 3, "rationale": "approval postdates release",
      "gaps": ["approval timestamp is later than the deployment timestamp"], "flags": [],
      "elementVerdicts": [{"element_id": "e2", "status": "not_evidenced", "excerpt": QUOTE}]}
DIFF = {"comparable": True, "disagreements": ["e2"], "diff_sha": "deadbeef1234",
        "rows": [{"element_id": "e2", "text": E2_TEXT, "reviewer": "met", "ai": "not_evidenced",
                  "direction": "reviewer_more_generous", "ai_excerpt": QUOTE}]}


class _Ctl:
    id, lib, title, req, maps = CONTROL_ID, "Control Library - MAS", "Change management", "req", ""


def _challenge(element_id="e2", supports="assessor", strength="strong", quote=QUOTE, text=E2_TEXT):
    return {
        "observation": "the reviewer treats the change record as linking approval to the release",
        "evidence_basis": [quote],
        "requirement_basis": [text],
        "knowledge_basis": [],
        "inference": "an approval timestamped after the release cannot have authorised it",
        "challenge": "which record authorised the 13 March release?",
        "factual_pointer": {"source": "reviewer_supplied", "locator": "line:3", "quote": quote,
                            "fact": quote, "what_it_supports": "the release preceded the approval"},
        "requirement_pointer": {"control_id": CONTROL_ID, "locator": f"controls.{CONTROL_ID}.elements[1]",
                                "element_id": element_id, "text": text},
        "risk_to_address": "a production model change without prior authorisation",
        "resolution_pointer": "the emergency change record with its incident reference",
        "recommended_action": "request_evidence",
        "severity": "high",
        "confidence": "high",
        "supports": supports,
        "claim_test": {"claim": "e2 is met", "fact_meaning": "release precedes approval",
                       "rebuttal": "the timestamps contradict the claim",
                       "rebuttal_strength": strength, "risk_addressed": "unauthorised change"},
    }


def _stub(monkeypatch, payload):
    """Replace only the transport. Everything downstream of it runs for real."""
    monkeypatch.setattr(CH, "PROVIDER", "ollama")
    monkeypatch.setattr(CH, "_ollama", lambda system, user: json.dumps(payload))
    monkeypatch.setattr(CH, "model_name", lambda: "stub-model")
    # The knowledge brain is exercised by its own tests; an empty context keeps this test
    # about the challenge path rather than about retrieval.
    monkeypatch.setattr(CH, "scan_injection", lambda t: [])


def test_in_scope_challenge_survives_the_full_validation_chain(monkeypatch):
    _stub(monkeypatch, {"overall_reasoning": "the release preceded the approval",
                        "challenges": [_challenge()], "sharpest": "which record authorised it?",
                        "unaddressed": []})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)
    assert len(out["challenges"]) == 1
    c = out["challenges"][0]
    assert c["supports"] == "assessor"
    assert c["challenge_strength"] == "strong"
    assert c["factual_pointer"]["locator"] == "line:3"       # verified, not echoed
    assert out["challenge_outcome"] == "substantive"
    assert out["pass"] == 2 and out["scope_elements"] == ["e2"]
    assert out["diff_sha"] == "deadbeef1234"


def test_out_of_scope_challenge_is_dropped_before_validation(monkeypatch):
    _stub(monkeypatch, {"overall_reasoning": "x",
                        "challenges": [_challenge(), _challenge(element_id="e1", text="Change categories, impact assessment, required testing and approval criteria are defined.")],
                        "sharpest": "s", "unaddressed": []})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)
    assert out["out_of_scope_dropped"] == 1
    assert [c["requirement_pointer"]["element_id"] for c in out["challenges"]] == ["e2"]


def test_a_pass_that_finds_only_out_of_scope_points_returns_nothing(monkeypatch):
    """Silence is a valid result. It must not be filled with the nearest available challenge."""
    _stub(monkeypatch, {"overall_reasoning": "x",
                        "challenges": [_challenge(element_id="e3", text="Post-implementation verification and closure or exception handling are required.")],
                        "sharpest": "s", "unaddressed": []})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)
    assert out["challenges"] == []
    assert out["out_of_scope_dropped"] == 1
    assert out["challenge_outcome"] == "no_rebuttal"


def test_unverifiable_quote_is_rejected(monkeypatch):
    _stub(monkeypatch, {"overall_reasoning": "x",
                        "challenges": [_challenge(quote="the CAB minutes record a verbal approval")],
                        "sharpest": "s", "unaddressed": []})
    with pytest.raises(ValueError, match="not verifiable"):
        CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)


def test_requirement_text_is_canonicalized_from_the_governed_element(monkeypatch):
    _stub(monkeypatch, {"overall_reasoning": "x",
                        "challenges": [_challenge(text="change records must be complete and timely")],
                        "sharpest": "s", "unaddressed": []})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)
    c = out["challenges"][0]
    assert c["requirement_pointer"]["element_id"] == "e2"
    assert c["requirement_pointer"]["text"] == E2_TEXT
    assert c["requirement_pointer_repaired"] is True


def test_strong_but_supporting_neither_side_is_downgraded_and_changes_the_outcome(monkeypatch):
    _stub(monkeypatch, {"overall_reasoning": "x",
                        "challenges": [_challenge(supports="neither", strength="strong")],
                        "sharpest": "s", "unaddressed": []})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)
    assert out["challenges"][0]["challenge_strength"] == "weak"
    assert out["challenge_outcome"] == "weak_or_refining"      # recomputed, not carried over


def test_the_pass_can_find_for_the_reviewer(monkeypatch):
    """The asymmetry that matters: this pass must be able to say the assessor is wrong."""
    _stub(monkeypatch, {"overall_reasoning": "x",
                        "challenges": [_challenge(supports="reviewer")],
                        "sharpest": "s", "unaddressed": []})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)
    assert out["challenges"][0]["supports"] == "reviewer"
    assert out["supports_tally"]["reviewer"] == 1
    assert out["supports_tally"]["assessor"] == 0


def test_no_rating_of_any_kind_escapes_the_pass(monkeypatch):
    payload = {"overall_reasoning": "x", "challenges": [_challenge()], "sharpest": "s",
               "unaddressed": [], "sufficiency": "partial", "proposedMaturity": 2}
    _stub(monkeypatch, payload)
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)
    for c in out["challenges"]:
        assert "sufficiency" not in c and "maturity" not in c and "proposedMaturity" not in c


def test_disagreement_pass_derives_resolution_from_control_testing_vocabulary(monkeypatch):
    payload_challenge = _challenge()
    payload_challenge.pop("resolution_pointer")
    _stub(monkeypatch, {"overall_reasoning": "the release preceded approval",
                        "challenges": [payload_challenge], "sharpest": "which record authorised it?",
                        "unaddressed": []})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)
    assert out["challenges"][0]["resolution_pointer"] == "A change record whose approval timestamp precedes deployment, or an approved retrospective acceptance naming the exposure."


def test_requirement_pointer_text_is_canonicalized_from_element_id(monkeypatch):
    payload = _challenge(text="stale model wording for e2")
    _stub(monkeypatch, {"overall_reasoning": "the release preceded the approval",
                        "challenges": [payload], "sharpest": "which record authorised it?",
                        "unaddressed": []})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)
    c = out["challenges"][0]
    assert c["requirement_pointer"]["element_id"] == "e2"
    assert c["requirement_pointer"]["text"] == E2_TEXT
    assert c["requirement_pointer_repaired"] is True
    assert c["requirement_pointer_original_text"] == "stale model wording for e2"
    assert c["requirement_basis"] == [E2_TEXT]
