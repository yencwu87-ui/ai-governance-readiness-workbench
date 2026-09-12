"""WB-025: hand-written requirements overlay the workbook's headings.

Run from repo/ with the venv active:
    pytest test_requirements_overlay_wb025.py -q
"""
from dataclasses import dataclass

import pytest

from requirements_overlay import apply_overlay, load_overlay

yaml = pytest.importorskip("yaml")


@dataclass
class C:
    lib: str
    id: str
    req: str
    artefacts: str = ""


def _controls():
    return {"MAS": [C("MAS", "M3.12", "Expectation: Change management. Source: P017", "Change records"),
                    C("MAS", "M1.1", "Expectation: Board accountability.", "Board mandate"),
                    C("MAS", "M3.6  \u2605", "Expectation: Validation.", "Validation & test reports")],
            "SAFR": [C("SAFR", "S1.1", "Ensure every acting agent is registered", "")]}


YAML = """
version: 1
library: MAS
controls:
  M3.12:
    requirement: >
      Changes are authorised before implementation and what reached production is what was
      approved.
    elements:
      - id: e1
        text: Model changes are raised as changes, including retraining
        scope: model
      - id: e2
        text: A validation standard exists as policy
        scope: programme
    boundary:
      none: No change records
      partial: Records exist but authorisation does not
      full: All elements evidenced
  M1.1:
    requirement: "TODO — not written yet"
    elements: []
  M9.9:
    requirement: A control that is not in the workbook
    elements: []
settings:
  elements_replace_artefacts: true
  prompt_boundary: false
  element_scopes: [model]
"""


def _overlay(text=YAML, tmp_path=None, **settings):
    d = yaml.safe_load(text)
    d["settings"].update(settings)
    d.setdefault("settings", {})
    return d


def test_requirement_replaces_the_workbook_heading():
    cs = _controls()
    apply_overlay(cs, _overlay())
    assert cs["MAS"][0].req.startswith("Changes are authorised")
    assert "Expectation:" not in cs["MAS"][0].req


def test_elements_replace_the_artefact_string():
    cs = _controls()
    apply_overlay(cs, _overlay())
    assert cs["MAS"][0].artefacts == "Model changes are raised as changes, including retraining"


def test_programme_scoped_elements_are_excluded_by_default():
    cs = _controls()
    apply_overlay(cs, _overlay())
    assert "validation standard" not in cs["MAS"][0].artefacts


def test_programme_elements_included_when_scope_is_widened():
    cs = _controls()
    apply_overlay(cs, _overlay(element_scopes=["model", "programme"]))
    assert "validation standard" in cs["MAS"][0].artefacts


def test_todo_placeholder_leaves_the_control_alone():
    """A placeholder is not a requirement. Better to keep the heading than to assess against
    the word TODO."""
    cs = _controls()
    apply_overlay(cs, _overlay())
    assert cs["MAS"][1].req.startswith("Expectation:")
    assert cs["MAS"][1].artefacts == "Board mandate"


def test_other_libraries_are_untouched():
    cs = _controls()
    apply_overlay(cs, _overlay())
    assert cs["SAFR"][0].req == "Ensure every acting agent is registered"


def test_starred_control_ids_match():
    cs = _controls()
    d = _overlay()
    d["controls"]["M3.6"] = {"requirement": "Models are validated independently.",
                             "elements": [{"id": "e1", "text": "Results exist", "scope": "model"}]}
    apply_overlay(cs, d)
    assert cs["MAS"][2].req == "Models are validated independently."


def test_boundary_is_appended_only_when_enabled():
    cs = _controls()
    apply_overlay(cs, _overlay(prompt_boundary=True))
    assert "How far the evidence must go" in cs["MAS"][0].req
    cs2 = _controls()
    apply_overlay(cs2, _overlay())
    assert "How far the evidence must go" not in cs2["MAS"][0].req


def test_summary_reports_named_but_unmatched_controls():
    cs = _controls()
    s = apply_overlay(cs, _overlay())
    assert s["applied"] == 1          # M3.12 only; M1.1 is a TODO
    assert "M9.9" in s["unmatched"]


def test_missing_file_is_not_an_error():
    assert load_overlay("controls/does_not_exist.yaml") == {}
    cs = _controls()
    assert apply_overlay(cs, {})["applied"] == 0
    assert cs["MAS"][0].req.startswith("Expectation:")
