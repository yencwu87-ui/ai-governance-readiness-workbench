"""WB-033 — element verdicts as their own call.

No model. `_ollama` is replaced, so the routing, the parse tolerance and the degrade-to-unset
behaviour are asserted rather than observed.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import assessor as A  # noqa: E402

ELEMENTS = [{"id": "e1", "text": "An approved policy exists"},
            {"id": "e2", "text": "Approval precedes implementation"},
            {"id": "e3", "text": "Verification occurs afterwards"}]

EVIDENCE = "The standard was approved by the CIO on 3 March. Release happened on 13 March."

RATING_JSON = ('{"excerpt":"approved by the CIO on 3 March","gaps":[],"rationale":"r",'
               '"sufficiency":"partial","proposedMaturity":3,"remediation":[],"reviewerPrompt":"q"}')
VERDICT_JSON = ('{"elementVerdicts":[{"element_id":"e1","status":"met","excerpt":"approved by the CIO on 3 March"},'
                '{"element_id":"e2","status":"not_evidenced","excerpt":""},'
                '{"element_id":"e3","status":"not_evidenced","excerpt":""}]}')


class _Ctl:
    id, lib, title, req, owner, maps = "M3.12", "Control Library - MAS", "Change management", "requirement", "CIO", ""


@pytest.fixture
def wired(monkeypatch):
    """Route both calls to a scripted transport and record which system prompt each used."""
    calls = []

    def fake(system, user):
        calls.append({"system": system, "user": user})
        return VERDICT_JSON if system is A.SYSTEM_ELEMENTS else RATING_JSON

    monkeypatch.setattr(A, "PROVIDER", "ollama")
    monkeypatch.setattr(A, "_ollama", fake)
    monkeypatch.setattr(A, "model_name", lambda: "stub")
    monkeypatch.setattr(A, "_contract_elements", lambda c: list(ELEMENTS))
    monkeypatch.setattr(A, "scan_injection", lambda t: [])
    return calls


def test_split_makes_two_calls_and_fills_every_element(monkeypatch, wired):
    monkeypatch.setattr(A, "ELEMENT_PASS", "split")
    out = A.assess(_Ctl(), EVIDENCE)
    assert len(wired) == 2
    assert out["element_pass"] == "split"
    assert {v["element_id"] for v in out["elementVerdicts"]} == {"e1", "e2", "e3"}
    assert not any(v["status"] == "unset" for v in out["elementVerdicts"])


def test_the_rating_call_does_not_ask_for_elements_in_split_mode(monkeypatch, wired):
    monkeypatch.setattr(A, "ELEMENT_PASS", "split")
    A.assess(_Ctl(), EVIDENCE)
    rating = wired[0]
    assert "elementVerdicts" not in rating["system"]
    assert "a separate call decides each one" in rating["user"]


def test_the_element_call_carries_no_rating_question(monkeypatch, wired):
    monkeypatch.setattr(A, "ELEMENT_PASS", "split")
    A.assess(_Ctl(), EVIDENCE)
    el = wired[1]
    for word in ("sufficiency", "proposedMaturity", "remediation", "reviewerPrompt"):
        assert word not in el["system"]
    assert "Return exactly 3 entries" in el["user"]


def test_combined_makes_one_call(monkeypatch, wired):
    monkeypatch.setattr(A, "ELEMENT_PASS", "combined")
    monkeypatch.setattr(A, "_ollama", lambda s, u: (wired.append({"system": s, "user": u}),
                                                    RATING_JSON[:-1] + ',"elementVerdicts":[{"element_id":"e1","status":"not_evidenced"}]}')[1])
    out = A.assess(_Ctl(), EVIDENCE)
    assert len(wired) == 1
    assert "elementVerdicts" in wired[0]["system"]
    assert out["element_pass"] == "combined"


def test_a_failed_element_call_costs_the_verdicts_not_the_rating(monkeypatch, wired):
    """The rating succeeded. Losing it because the second call broke would be worse than
    reporting the elements as unset, which compare() already handles honestly."""
    monkeypatch.setattr(A, "ELEMENT_PASS", "split")

    def fake(system, user):
        if system is A.SYSTEM_ELEMENTS:
            raise RuntimeError("read timeout")
        return RATING_JSON

    monkeypatch.setattr(A, "_ollama", fake)
    out = A.assess(_Ctl(), EVIDENCE)
    assert out["sufficiency"] == "partial"
    assert all(v["status"] == "unset" for v in out["elementVerdicts"])
    assert out["element_call_returned"] == 0


def test_garbage_from_the_element_call_becomes_unset_not_met(monkeypatch, wired):
    monkeypatch.setattr(A, "ELEMENT_PASS", "split")
    monkeypatch.setattr(A, "_ollama",
                        lambda s, u: "sorry, I cannot do that" if s is A.SYSTEM_ELEMENTS else RATING_JSON)
    out = A.assess(_Ctl(), EVIDENCE)
    assert all(v["status"] == "unset" for v in out["elementVerdicts"])


def test_off_mode_returns_no_verdicts(monkeypatch, wired):
    monkeypatch.setattr(A, "ELEMENT_PASS", "off")
    out = A.assess(_Ctl(), EVIDENCE)
    assert all(v["status"] == "unset" for v in out["elementVerdicts"])
    assert len(wired) == 1


def test_a_partial_element_response_is_filled_out_not_dropped(monkeypatch, wired):
    """The failure mode actually seen in the field: 1 verdict of 3. The two the model skipped
    must land as unset so compare() excludes them, rather than as not_evidenced."""
    monkeypatch.setattr(A, "ELEMENT_PASS", "split")
    monkeypatch.setattr(A, "_ollama",
                        lambda s, u: ('{"elementVerdicts":[{"element_id":"e1","status":"not_evidenced"}]}'
                                      if s is A.SYSTEM_ELEMENTS else RATING_JSON))
    out = A.assess(_Ctl(), EVIDENCE)
    by = {v["element_id"]: v["status"] for v in out["elementVerdicts"]}
    assert by == {"e1": "not_evidenced", "e2": "unset", "e3": "unset"}
    assert out["element_call_returned"] == 1


@pytest.mark.parametrize("payload,expected", [
    ('{"elementVerdicts":[{"element_id":"e1","status":"met","excerpt":"x"}]}', 1),
    ('[{"element_id":"e1","status":"met"}]', 1),
    ('{"e1":"met","e2":"not_evidenced"}', 2),
    ('```json\n{"elementVerdicts":[{"element_id":"e1","status":"met"}]}\n```', 1),
    ("not json at all", 0),
    ("", 0),
])
def test_parse_elements_tolerates_the_shapes_models_return(payload, expected):
    assert len(A._parse_elements(payload)) == expected


def test_unrecognised_status_is_the_conservative_value():
    assert A._normalise_verdicts([{"element_id": "e1", "status": "probably"}])[0]["status"] == "not_evidenced"


# ---------------- WB-034: a downgrade must stay diagnosable ----------------

def test_a_rejected_met_excerpt_is_retained_for_diagnosis(monkeypatch, wired):
    """Clearing the excerpt on downgrade destroyed the only record of why. A paraphrase and a
    quote that lost its markdown markup produce identical counts and need opposite fixes."""
    monkeypatch.setattr(A, "ELEMENT_PASS", "split")
    monkeypatch.setattr(A, "_ollama",
                        lambda s, u: ('{"elementVerdicts":[{"element_id":"e1","status":"met",'
                                      '"excerpt":"the CIO signed the standard in early March"}]}'
                                      if s is A.SYSTEM_ELEMENTS else RATING_JSON))
    out = A.assess(_Ctl(), EVIDENCE)
    e1 = [v for v in out["elementVerdicts"] if v["element_id"] == "e1"][0]
    assert e1["status"] == "not_evidenced"
    assert e1["excerpt"] == ""                                    # never rated on
    assert e1["rejected_excerpt"] == "the CIO signed the standard in early March"
    assert "not verbatim" in e1["downgraded"]


def test_a_met_with_no_excerpt_is_distinguished_from_a_failed_quote(monkeypatch, wired):
    monkeypatch.setattr(A, "ELEMENT_PASS", "split")
    monkeypatch.setattr(A, "_ollama",
                        lambda s, u: ('{"elementVerdicts":[{"element_id":"e1","status":"met","excerpt":""}]}'
                                      if s is A.SYSTEM_ELEMENTS else RATING_JSON))
    out = A.assess(_Ctl(), EVIDENCE)
    e1 = [v for v in out["elementVerdicts"] if v["element_id"] == "e1"][0]
    assert e1["downgraded"] == "met asserted with no excerpt"
    assert e1["rejected_excerpt"] == ""



# ---------------- WB-035: the excerpt is committed to before the status ----------------

def test_the_element_schema_puts_excerpt_before_status(monkeypatch, wired):
    """All five downgrades on M3.6 were `met` with an empty excerpt. With status generated
    first the model commits to the verdict and then has nothing to justify it with, which is
    the ordering the main assessor prompt already avoids: find the excerpt, then decide."""
    monkeypatch.setattr(A, "ELEMENT_PASS", "split")
    A.assess(_Ctl(), EVIDENCE)
    schema = wired[1]["system"]
    assert schema.index('"excerpt"') < schema.index('"status"')
    assert "Never write \"met\" with an empty excerpt" in schema
    assert "copy the\npassage, and then set the status" in wired[1]["user"]
