"""WB-030 — element-level compare, and the scope rule on the second challenge pass.

Every test here runs without a model. That is the point of splitting compare() out as a pure
function: the properties that matter (silence is not agreement, a failed call is not a pass,
the rate has a floor) are deterministic and can be asserted rather than observed.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import compare as C  # noqa: E402
from challenge import scope_filter, _normalise_supports  # noqa: E402


class FakeControl:
    """Stands in for a playbook Control without loading the workbook."""
    def __init__(self, cid="X1", lib="Control Library - MAS"):
        self.id, self.lib = cid, lib


ELEMENTS = [
    {"id": "e1", "text": "An approved policy exists", "scope": "model", "locator": "controls.X1.elements[0]"},
    {"id": "e2", "text": "Approval precedes implementation", "scope": "model", "locator": "controls.X1.elements[1]"},
    {"id": "e3", "text": "Post-implementation verification occurs", "scope": "model", "locator": "controls.X1.elements[2]"},
    {"id": "e4", "text": "Exceptions are dispositioned", "scope": "model", "locator": "controls.X1.elements[3]"},
]


@pytest.fixture(autouse=True)
def _stub_elements(monkeypatch):
    monkeypatch.setattr(C, "elements_for", lambda control: list(ELEMENTS))


def blind(**verdicts):
    return {"sufficiency": verdicts.pop("_suff", "partial"), "maturity": verdicts.pop("_mat", 3),
            "reason": "stated reason for the reading",
            "element_verdicts": [{"element_id": k, "status": v} for k, v in verdicts.items()]}


def ai(**verdicts):
    return {"sufficiency": verdicts.pop("_suff", "partial"), "proposedMaturity": verdicts.pop("_mat", 3),
            "rationale": "r", "gaps": [],
            "elementVerdicts": [{"element_id": k, "status": v, "excerpt": ""} for k, v in verdicts.items()]}


# ---------------- agreement and disagreement ----------------

def test_identical_verdicts_agree_on_every_element():
    d = C.compare(blind(e1="met", e2="met", e3="not_evidenced", e4="met"),
                  ai(e1="met", e2="met", e3="not_evidenced", e4="met"), FakeControl())
    assert d["comparable"] is True
    assert d["summary"]["n_compared"] == 4
    assert d["summary"]["n_disagree"] == 0
    assert d["summary"]["agreement_rate"] == 1.0
    assert d["disagreements"] == []


def test_disagreement_is_located_and_directed():
    d = C.compare(blind(e1="met", e2="met", e3="met", e4="met"),
                  ai(e1="met", e2="not_evidenced", e3="met", e4="met"), FakeControl())
    assert d["disagreements"] == ["e2"]
    row = [r for r in d["rows"] if r["element_id"] == "e2"][0]
    assert row["direction"] == "reviewer_more_generous"
    assert d["summary"]["agreement_rate"] == 0.75


def test_same_rating_can_hide_element_disagreement():
    """The reason this block exists: both sides say partial, and agree on nothing."""
    d = C.compare(blind(_suff="partial", e1="met", e2="not_evidenced", e3="met", e4="not_evidenced"),
                  ai(_suff="partial", e1="not_evidenced", e2="met", e3="not_evidenced", e4="met"),
                  FakeControl())
    assert d["rating"]["agree"] is True
    assert d["summary"]["n_disagree"] == 4


# ---------------- silence ----------------

def test_unset_on_either_side_is_never_agreement():
    d = C.compare(blind(e1="met", e2="unset", e3="met", e4="met"),
                  ai(e1="met", e3="met", e4="met"), FakeControl())   # e2 absent from both
    row = [r for r in d["rows"] if r["element_id"] == "e2"][0]
    assert row["compared"] is False and row["agree"] is None
    assert row["direction"] == "not_compared"
    assert d["summary"]["n_compared"] == 3
    assert d["summary"]["reviewer_unset"] == 1 and d["summary"]["assessor_unset"] == 1


def test_element_missing_from_the_assessor_is_unset_not_disagreement():
    d = C.compare(blind(e1="met", e2="met", e3="met", e4="met"),
                  ai(e1="met", e2="met"), FakeControl())
    assert d["disagreements"] == []
    assert d["summary"]["assessor_unset"] == 2


def test_verdict_on_an_undeclared_element_is_ignored():
    b = blind(e1="met", e2="met", e3="met", e4="met")
    b["element_verdicts"].append({"element_id": "e99", "status": "met"})
    d = C.compare(b, ai(e1="met", e2="met", e3="met", e4="met"), FakeControl())
    assert [r["element_id"] for r in d["rows"]] == ["e1", "e2", "e3", "e4"]
    assert d["summary"]["n_compared"] == 4


# ---------------- failure and floor ----------------

def test_failed_assessor_call_is_not_comparable():
    for broken in ({"status": "error", "error": "read timeout"}, {}, None, {"error": "boom"}):
        d = C.compare(blind(e1="met"), broken, FakeControl())
        assert d["comparable"] is False
        assert d["disagreements"] == []
        assert "rating" not in d or d["rating"]["ai"] is None


def test_no_reviewer_reading_is_not_comparable():
    assert C.compare({}, ai(e1="met"), FakeControl())["comparable"] is False


def test_agreement_rate_is_withheld_below_the_floor():
    d = C.compare(blind(e1="met", e2="met"), ai(e1="met", e2="met"), FakeControl(), min_compared=3)
    assert d["summary"]["n_compared"] == 2
    assert d["summary"]["floor_met"] is False
    assert d["summary"]["agreement_rate"] is None          # not 1.0 — two elements is not a rate
    assert "below the floor" in C.headline(d)


def test_headline_never_asserts_who_is_right():
    d = C.compare(blind(e1="met", e2="met", e3="met", e4="not_evidenced"),
                  ai(e1="met", e2="met", e3="met", e4="met"), FakeControl())
    h = C.headline(d).lower()
    assert "e4" in h
    for word in ("correct", "wrong", "should", "error"):
        assert word not in h


# ---------------- determinism ----------------

def test_diff_sha_is_stable_and_order_independent():
    a1 = C.compare(blind(e1="met", e2="not_evidenced"), ai(e1="met", e2="not_evidenced"), FakeControl())
    a2 = C.compare(blind(e2="not_evidenced", e1="met"), ai(e2="not_evidenced", e1="met"), FakeControl())
    assert a1["diff_sha"] == a2["diff_sha"]


def test_diff_sha_changes_when_a_verdict_changes():
    a1 = C.compare(blind(e1="met", e2="met"), ai(e1="met", e2="met"), FakeControl())
    a2 = C.compare(blind(e1="met", e2="not_evidenced"), ai(e1="met", e2="met"), FakeControl())
    assert a1["diff_sha"] != a2["diff_sha"]


# ---------------- pass 2 scope rule ----------------

def _ch(element_id, **kw):
    c = {"requirement_pointer": {"element_id": element_id}, "challenge": "q"}
    c.update(kw)
    return c


def test_scope_filter_keeps_only_disputed_elements():
    kept, dropped = scope_filter([_ch("e2"), _ch("e1"), _ch("e3")], ["e2", "e3"])
    assert [k["requirement_pointer"]["element_id"] for k in kept] == ["e2", "e3"]
    assert dropped == 1


def test_scope_filter_drops_malformed_and_pointerless_challenges():
    kept, dropped = scope_filter([_ch("e2"), {"challenge": "no pointer"}, "not an object", None], ["e2"])
    assert len(kept) == 1 and dropped == 3


def test_supports_defaults_to_neither_when_unstated():
    cleaned = _normalise_supports([{"challenge_strength": "weak"}], [{}])
    assert cleaned[0]["supports"] == "neither"


def test_strong_rebuttal_supporting_neither_side_is_downgraded():
    """A fact cannot contradict a verdict while settling neither side's verdict."""
    cleaned = _normalise_supports([{"challenge_strength": "strong"}], [{"supports": "neither"}])
    assert cleaned[0]["challenge_strength"] == "weak"
    assert cleaned[0]["strength_downgraded"]


def test_supports_may_find_for_the_reviewer_against_the_assessor():
    cleaned = _normalise_supports([{"challenge_strength": "strong"}], [{"supports": "reviewer"}])
    assert cleaned[0]["supports"] == "reviewer"
    assert cleaned[0]["challenge_strength"] == "strong"


# ---------------- regression: both prompt builders must construct ----------------

class _Ctl:
    id, lib, title, req, maps = "M3.12", "Control Library - MAS", "Change management", "req", ""


def test_pass_one_prompt_builds():
    """`_get(control, "lib", "")` is called in five places. Before WB-030 `_get` took two
    arguments, so every call to challenge() raised TypeError before reaching the model and
    "Challenge my reading" could not run at all."""
    import challenge as CH
    p = CH._prompt(_Ctl(), "evidence", {"sufficiency": "full", "maturity": 4, "reason": "x"})
    assert "THE REVIEWER'S READ TO ATTACK" in p


def test_pass_two_prompt_builds_and_states_its_scope():
    import challenge as CH
    diff = {"comparable": True, "disagreements": ["e1"], "diff_sha": "abc",
            "rows": [{"element_id": "e1", "text": "An element", "reviewer": "met",
                      "ai": "not_evidenced", "direction": "reviewer_more_generous", "ai_excerpt": "q"}]}
    p = CH._prompt_disagreement(_Ctl(), "evidence", {"sufficiency": "full", "maturity": 4, "reason": "x"},
                                {"sufficiency": "partial", "proposedMaturity": 3, "rationale": "r", "gaps": []},
                                diff, "", "")
    assert "work only on these elements" in p.lower()
    assert "reviewer says: met" in p and "assessor says: not_evidenced" in p


def test_pass_two_refuses_to_run_without_a_disagreement():
    import challenge as CH
    import pytest as _pt
    with _pt.raises(ValueError):
        CH.challenge_disagreement(_Ctl(), "ev", {}, {}, {"comparable": True, "disagreements": []})
    with _pt.raises(ValueError):
        CH.challenge_disagreement(_Ctl(), "ev", {}, {}, {"comparable": False, "disagreements": ["e1"]})
