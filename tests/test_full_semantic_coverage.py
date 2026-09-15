from __future__ import annotations
import yaml
from pathlib import Path

from governance.semantic_registry import coverage_summary, control_semantics, element_semantics, load_semantic_registry
from governance.predicate_coverage import coverage


def test_full_governed_inventory_has_semantic_record():
    summary = coverage_summary()
    assert summary["controls_total"] == 195
    assert summary["elements_total"] == 562
    data = load_semantic_registry()
    assert len(data.get("controls") or []) == 195
    for c in data["controls"]:
        assert c.get("semantic_status")
        assert c.get("requirement")
        assert c.get("elements")
        for e in c["elements"]:
            assert e.get("id")
            assert e.get("intent")
            assert e.get("governed_text")
            assert e.get("verification") in {"DETERMINISTIC", "HUMAN_JUDGEMENT", "OUT_OF_BAND"}
            assert e.get("source_basis")


def test_known_mas_control_boundaries_are_not_cross_contaminated():
    m11 = control_semantics("M1.1", "MAS")
    m36 = control_semantics("M3.6", "MAS")
    assert m11 is not None and m36 is not None
    assert len(m11["elements"]) == 3
    assert len(m36["elements"]) == 14
    assert m11["elements"][0]["governed_text"] != m36["elements"][0]["governed_text"]


def test_predicate_availability_and_verification_mode_are_separate_facts():
    """This asserted DETERMINISTIC on M3.6 and D1.2 because a predicate specification existed.

    That was the conflation: `verification` was derived from `predicate_spec.present`, so it
    restated a fact about our code as a fact about the evidence boundary. M3.6 e6 — "reviewed by
    parties not involved in its development" — was DETERMINISTIC while the adjudicated corpus for
    the same element treated it as human judgement.

    The predicate still exists and is still recorded. What changed is that the mode now depends
    on whether a declared provider supplies the observations the predicate needs, and none is
    declared yet.
    """
    c = control_semantics("M3.6", "MAS")
    assert c is not None
    assert all(e["predicate_available"] for e in c["elements"]), "predicates still recorded"
    modes = {e["verification"] for e in c["elements"]}
    assert modes == {"HUMAN_JUDGEMENT", "OUT_OF_BAND"}

    d = control_semantics("D1.2", "MGF Agentic")
    assert d is not None
    assert all(e["predicate_available"] for e in d["elements"])
    assert all(e["verification"] == "HUMAN_JUDGEMENT" for e in d["elements"])
    assert all("no declared provider supplies" in e["verification_reason"]
               for e in d["elements"])


def test_coverage_does_not_equate_semantic_coverage_with_predicate_coverage():
    cov = coverage()
    assert cov["controls"] == 195
    assert cov["elements"] == 562
    assert cov["semantic_elements"] == 562
    assert cov["deterministic_elements"] < cov["elements"]
    assert cov["human_judgement_elements"] > 0


def test_every_semantic_element_can_be_retrieved_by_key():
    data = load_semantic_registry()
    for c in data["controls"]:
        for e in c["elements"]:
            got = element_semantics(c["control_id"], c["framework"], e["id"])
            assert got is not None
            assert got["id"] == e["id"]


def test_mgf_is_purposefully_decomposed_and_d13_has_four_elements():
    from governance.semantic_registry import control_semantics
    import yaml
    from pathlib import Path

    c = control_semantics("D1.3", "MGF Agentic")
    assert c is not None
    assert [e["id"] for e in c["elements"]] == ["e1", "e2", "e3", "e4"]
    assert "minimum required" in c["elements"][0]["governed_text"]
    assert "autonomy" in c["elements"][1]["governed_text"]
    assert "area of impact" in c["elements"][2]["governed_text"]
    assert "deterministic technical controls" in c["elements"][3]["governed_text"]


def test_mgf_contract_and_consolidated_contract_match_element_counts():
    root = Path(__file__).resolve().parents[1]
    mgf = yaml.safe_load((root / "governance/knowledge/contracts/mgf_agentic.yaml").read_text())
    allc = yaml.safe_load((root / "governance/knowledge/control_contracts.yaml").read_text())
    a = {c["control_id"]: len(c.get("elements") or []) for c in mgf["controls"]}
    b = {c["control_id"]: len(c.get("elements") or []) for c in allc["controls"] if c.get("control_id", "").startswith("D")}
    assert a == {k:v for k,v in b.items() if k in a}
    assert sum(a.values()) > 39
