"""WB-030 — the assessor's per-element verdicts, and the downgrade-only checks on them.

These sit beside the other test_*_wb0nn.py files at the repo root rather than in tests/,
matching where the assessor's own validation tests already live.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from assessor import _parse, _validate  # noqa: E402

ELEMENTS = [
    {"id": "e1", "text": "An approved policy exists"},
    {"id": "e2", "text": "Approval precedes implementation"},
    {"id": "e3", "text": "Verification occurs after implementation"},
]

EVIDENCE = ("The change management standard was approved by the CIO on 3 March. "
            "Change CHG-4471 was approved on 14 March and released on 13 March.")


def base(**kw):
    out = {"excerpt": "", "gaps": [], "rationale": "r", "sufficiency": "partial",
           "proposedMaturity": 3, "remediation": [], "reviewerPrompt": "q", "elementVerdicts": []}
    out.update(kw)
    return out


def v(eid, status, excerpt=""):
    return {"element_id": eid, "status": status, "excerpt": excerpt}


def test_parse_normalises_verdict_shapes():
    out = _parse('{"excerpt":"","gaps":[],"rationale":"r","sufficiency":"partial","proposedMaturity":3,'
                 '"remediation":[],"reviewerPrompt":"q",'
                 '"elementVerdicts":[{"element_id":"e1","status":"Met","excerpt":"x"},'
                 '{"element_id":"e2","status":"nonsense"}]}')
    assert out["elementVerdicts"][0]["status"] == "met"
    # An unrecognised status is the conservative value, never the generous one.
    assert out["elementVerdicts"][1]["status"] == "not_evidenced"


def test_parse_tolerates_a_mapping_instead_of_a_list():
    out = _parse('{"excerpt":"","gaps":[],"rationale":"r","sufficiency":"none","proposedMaturity":1,'
                 '"remediation":[],"reviewerPrompt":"q","elementVerdicts":{"e1":"met"}}')
    assert out["elementVerdicts"] == [{"element_id": "e1", "status": "met", "excerpt": ""}]


def test_met_without_a_verbatim_excerpt_becomes_not_evidenced():
    out = _validate(base(excerpt="approved by the CIO on 3 March",
                         elementVerdicts=[v("e1", "met", "the board signed it off last year"),
                                          v("e2", "not_evidenced"), v("e3", "not_evidenced")]),
                    EVIDENCE, [], [], ELEMENTS)
    e1 = [x for x in out["elementVerdicts"] if x["element_id"] == "e1"][0]
    assert e1["status"] == "not_evidenced" and e1["excerpt"] == ""
    assert any("no verbatim excerpt" in f for f in out["flags"])


def test_met_with_a_verbatim_excerpt_survives():
    out = _validate(base(excerpt="approved by the CIO on 3 March",
                         elementVerdicts=[v("e1", "met", "approved by the CIO on 3 March"),
                                          v("e2", "not_evidenced"), v("e3", "not_evidenced")]),
                    EVIDENCE, [], [], ELEMENTS)
    assert [x for x in out["elementVerdicts"] if x["element_id"] == "e1"][0]["status"] == "met"


def test_missing_elements_are_recorded_as_unset_not_as_absent():
    out = _validate(base(excerpt="approved by the CIO on 3 March",
                         elementVerdicts=[v("e1", "met", "approved by the CIO on 3 March")]),
                    EVIDENCE, [], [], ELEMENTS)
    by_id = {x["element_id"]: x for x in out["elementVerdicts"]}
    assert by_id["e2"]["status"] == "unset" and by_id["e3"]["status"] == "unset"
    assert any("no verdict for 2 of 3" in f for f in out["flags"])


def test_verdict_on_an_undeclared_element_is_dropped():
    out = _validate(base(excerpt="approved by the CIO on 3 March",
                         elementVerdicts=[v("e1", "met", "approved by the CIO on 3 March"),
                                          v("e9", "met", "approved by the CIO on 3 March")]),
                    EVIDENCE, [], [], ELEMENTS)
    assert "e9" not in {x["element_id"] for x in out["elementVerdicts"]}
    assert any("does not declare" in f for f in out["flags"])


def test_full_with_an_unmet_element_is_downgraded_to_partial():
    out = _validate(base(sufficiency="full", proposedMaturity=5,
                         excerpt="approved by the CIO on 3 March",
                         elementVerdicts=[v("e1", "met", "approved by the CIO on 3 March"),
                                          v("e2", "not_evidenced"), v("e3", "met", "approved by the CIO on 3 March")]),
                    EVIDENCE, [], [], ELEMENTS)
    assert out["sufficiency"] == "partial"
    assert out["proposedMaturity"] <= 3        # the existing ceiling still applies after the downgrade


def test_every_decided_element_unmet_forces_none():
    out = _validate(base(sufficiency="partial", excerpt="approved by the CIO on 3 March",
                         elementVerdicts=[v("e1", "not_evidenced"), v("e2", "not_evidenced"),
                                          v("e3", "not_evidenced")]),
                    EVIDENCE, [], [], ELEMENTS)
    assert out["sufficiency"] == "none"
    assert out["proposedMaturity"] == 1


def test_unset_elements_alone_do_not_force_none():
    """Silence from the model is not evidence of absence, at the element level either."""
    out = _validate(base(sufficiency="partial", excerpt="approved by the CIO on 3 March",
                         elementVerdicts=[]),
                    EVIDENCE, [], [], ELEMENTS)
    assert out["sufficiency"] == "partial"
    assert all(x["status"] == "unset" for x in out["elementVerdicts"])


def test_validate_is_unchanged_when_no_elements_are_declared():
    """Controls with no contract elements must behave exactly as they did before WB-030."""
    out = _validate(base(excerpt="approved by the CIO on 3 March"), EVIDENCE, [], [], None)
    assert out["sufficiency"] == "partial"
    assert "elementVerdicts" in out
