from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from governance.triangulation import SourceRegistry, obligation_confidence, assurance_sufficiency, change_state, control_sufficiency

ROOT = Path(__file__).resolve().parents[1]


def test_proposed_source_can_not_establish_live_requiredness():
    reg = SourceRegistry.from_yaml(ROOT / "requirements/triangulation/sources.yaml")
    s = reg.sources["MAS-AIRG-P017-2025"]
    assert s.lifecycle_status == "proposed"
    assert obligation_confidence(s, 1.0) < 0.55


def test_binding_effective_source_can_support_requiredness():
    reg = SourceRegistry.from_yaml(ROOT / "requirements/triangulation/sources.yaml")
    s = reg.sources["MAS-TRM-NOTICES-BASELINE-2024"]
    assert obligation_confidence(s, 1.0) >= 0.55


def test_closed_consultation_has_future_pending_state():
    reg = SourceRegistry.from_yaml(ROOT / "requirements/triangulation/sources.yaml")
    s = reg.sources["MAS-TRM-P012-2026"]
    assert change_state(s) == "consultation_closed_pending_final"


def test_sufficiency_is_not_same_as_element_presence():
    card = {"tod": ["x"], "toe": ["y"], "failure_modes": ["z"], "resolution": ["r"],
            "sufficiency_boundary": ["b"], "test_provenance": ["p"], "change_revalidation": ["c"]}
    out = assurance_sufficiency(card)
    assert out["status"] == "sufficient"
    card.pop("resolution")
    out2 = assurance_sufficiency(card)
    assert out2["status"] == "insufficient"
    assert "resolution" in out2["missing"]


def test_control_triangulation_flags_unmapped_element():
    reg = SourceRegistry.from_yaml(ROOT / "requirements/triangulation/sources.yaml")
    elements = [{"id":"e1","text":"do x","source_obligation_refs":["src.1"],"tod":[1],"toe":[1],"failure_modes":[1],"resolution":[1],"sufficiency_boundary":[1],"test_provenance":[1],"change_revalidation":[1]},
                {"id":"e2","text":"do y","tod":[1],"toe":[1],"failure_modes":[1],"resolution":[1],"sufficiency_boundary":[1],"test_provenance":[1],"change_revalidation":[1]}]
    r = control_sufficiency(elements, [], reg, as_of="2026-09-14", control_id="X")
    assert r["control"]["source_orphans"] == ["e2"]
    assert r["control"]["status"] == "blocked"
