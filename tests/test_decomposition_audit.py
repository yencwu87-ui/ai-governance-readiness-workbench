"""Decomposition quality — is this a decomposition, or the control restated?"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.decomposition_audit import audit_control, audit_library

LIB = ROOT / "governance" / "knowledge" / "control_contracts.yaml"


def _lib():
    return yaml.safe_load(LIB.read_text(encoding="utf-8"))["controls"]


def test_an_element_that_is_just_the_control_id_is_an_error():
    f = audit_control({"control_id": "MAP 2.1", "title": "t",
                       "elements": [{"id": "e1", "text": "MAP 2.1"}]})
    assert f[0]["code"] == "EMPTY_ELEMENT"


def test_a_stock_prefix_wrapping_a_fragment_is_an_error():
    f = audit_control({"control_id": "X", "title": "t", "elements": [
        {"id": "e1", "text": "The organization must ensure that stand up a repeatable process."}]})
    assert any(x["code"] == "TEMPLATE_WRAPPED" for x in f)


def test_a_clean_obligation_produces_nothing():
    assert audit_control({"control_id": "X", "title": "Change management", "elements": [
        {"id": "e1", "text": "Change records link approval to the deployed version."}]}) == []


def test_the_archetype_collapse_is_only_visible_after_normalising_the_title():
    """The defect no other check sees: unique ids, differing text, same requirement."""
    a = {"control_id": "S1.2", "framework": "SAFR", "title": "Agent mandate definition",
         "elements": [{"id": "e1", "text": "The control design specifies the authority boundary "
                                           "for Agent mandate definition and its limits."}]}
    b = {"control_id": "S4.2", "framework": "SAFR", "title": "Gateway interception of actions",
         "elements": [{"id": "e1", "text": "The control design specifies the authority boundary "
                                           "for Gateway interception of actions and its limits."}]}
    assert audit_control(a) == [] or all(x["severity"] != "error" for x in audit_control(a))
    lib = audit_library([a, b])
    refs = {f["ref"] for f in lib["findings"] if f["code"] == "TEMPLATED_SET"}
    assert refs == {"S1.2", "S4.2"}


def test_two_controls_with_genuinely_different_elements_do_not_collide():
    a = {"control_id": "A", "title": "One", "elements": [{"id": "e1", "text": "Records are kept."}]}
    b = {"control_id": "B", "title": "Two", "elements": [{"id": "e1", "text": "An owner is named."}]}
    assert not [f for f in audit_library([a, b])["findings"] if f["code"] == "TEMPLATED_SET"]


def test_findings_carry_their_framework():
    """Control ids contain dots; splitting on the first one mapped ISO and NIST to '?'."""
    a = audit_library(_lib())
    assert "?" not in a["by_framework"]
    assert set(a["by_framework"]) <= {"MAS", "MGF Agentic", "SAFR", "NIST AI RMF", "ISO 42001"}


# ------------------------------------------------------------------ the live library

def test_the_repaired_defects_stay_repaired():
    a = audit_library(_lib())
    assert a["by_code"].get("TEMPLATE_WRAPPED", 0) == 0
    assert a["by_code"].get("EMPTY_ELEMENT", 0) == 0
    assert a["by_code"].get("TEST_PROCEDURE", 0) == 0
    assert a["by_code"].get("DUPLICATE_OBLIGATION", 0) == 0


def test_the_remaining_errors_are_safr_templating_only():
    """Recorded as a known, scoped defect rather than left implicit.

    17 SAFR controls carry archetype element sets. Repairing them needs decomposition from the
    SAFR white paper, which nothing mechanical can supply — generating replacements automatically
    is how the defect arrived.
    """
    a = audit_library(_lib())
    errors = [f for f in a["findings"] if f["severity"] == "error"]
    assert {f["code"] for f in errors} == {"TEMPLATED_SET"}
    assert {f["framework"] for f in errors} == {"SAFR"}


def test_mas_mgf_iso_and_nist_have_no_decomposition_errors():
    a = audit_library(_lib())
    for fw in ("MAS", "MGF Agentic", "ISO 42001", "NIST AI RMF"):
        errs = [f for f in a["findings"]
                if f.get("framework") == fw and f["severity"] == "error"]
        assert not errs, f"{fw}: {errs[:3]}"
