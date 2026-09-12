"""EVL-03 / EVL-04 overlay adapters (WB-029).

The cases that matter are the ones that produced a wrong answer before:

  - two overlay candidates present, the loader takes the first and warns. A
    warning is not a verdict, so EVL-03 has to count them.
  - a MAS control the overlay does not name still loads as a heading, and the
    assessor judges sufficiency against a control title. EVL-04 has to name it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import eval_adapters as ea


class FakeControl:
    def __init__(self, cid):
        self.id = cid


def _controls(ids):
    return {"MAS": [FakeControl(i) for i in ids]}


# --- EVL-03: overlay candidates --------------------------------------------

def test_single_candidate_is_marked_loaded():
    p = Path("requirements/mas.yaml")
    rows = ea.overlay_candidate_rows(candidates=[p], loaded=p)
    assert len(rows) == 1
    assert rows[0]["is_loaded"] is True


def test_two_candidates_are_both_returned_and_only_one_is_loaded():
    first = Path("requirements/mas.yaml")
    stale = Path("requirements/mas_requirements.yaml")
    rows = ea.overlay_candidate_rows(candidates=[first, stale], loaded=first)
    assert len(rows) == 2, "EVL-03 counts rows; a second candidate must not be collapsed away"
    assert [r["is_loaded"] for r in rows] == [True, False]


def test_no_candidates_returns_no_rows():
    assert ea.overlay_candidate_rows(candidates=[], loaded=None) == []


def test_loaded_match_is_path_based_not_string_based():
    rows = ea.overlay_candidate_rows(
        candidates=[Path("requirements/./mas.yaml")], loaded=Path("requirements/mas.yaml"))
    assert rows[0]["is_loaded"] is True


# --- EVL-04: requirement coverage ------------------------------------------

def test_named_controls_have_requirements(monkeypatch):
    monkeypatch.setattr(ea.playbook, "overlay_coverage",
                        lambda c: {"library": "MAS", "total": 2, "with_requirement": 2, "missing": []})
    rows = ea.overlay_coverage_rows(_controls(["M3.6", "M3.12"]))
    assert all(r["has_requirement"] for r in rows)


def test_unnamed_control_is_reported_as_heading_only(monkeypatch):
    monkeypatch.setattr(ea.playbook, "overlay_coverage",
                        lambda c: {"library": "MAS", "total": 3, "with_requirement": 2,
                                   "missing": ["M1.1"]})
    rows = ea.overlay_coverage_rows(_controls(["M3.6", "M3.12", "M1.1"]))
    bad = [r["control_id"] for r in rows if not r["has_requirement"]]
    assert bad == ["M1.1"]


def test_every_control_yields_exactly_one_row(monkeypatch):
    ids = [f"M{i}" for i in range(30)]
    monkeypatch.setattr(ea.playbook, "overlay_coverage",
                        lambda c: {"library": "MAS", "total": 30, "with_requirement": 0,
                                   "missing": ids})
    rows = ea.overlay_coverage_rows(_controls(ids))
    assert len(rows) == 30, "the evidence floor reads this count; it must be the real population"
    assert not any(r["has_requirement"] for r in rows)


def test_no_overlay_library_yields_no_rows(monkeypatch):
    monkeypatch.setattr(ea.playbook, "overlay_coverage",
                        lambda c: {"library": None, "total": 0, "with_requirement": 0, "missing": []})
    assert ea.overlay_coverage_rows(_controls(["M3.6"])) == []


def test_coverage_rows_refuses_to_load_the_workbook_itself():
    with pytest.raises(ValueError):
        ea.overlay_coverage_rows(None)


# --- reporting --------------------------------------------------------------

def test_summary_names_the_ignored_candidates(monkeypatch):
    first, stale = Path("requirements/mas.yaml"), Path("requirements/mas_requirements.yaml")
    monkeypatch.setattr(ea.playbook, "overlay_candidates_present", lambda: [first, stale])
    monkeypatch.setattr(ea.playbook, "overlay_path", lambda: first)
    s = ea.summary()
    assert s["overlay_candidates_found"] == 2
    assert s["overlay_path"] == str(first)
    assert s["overlay_ignored"] == [str(stale)]
