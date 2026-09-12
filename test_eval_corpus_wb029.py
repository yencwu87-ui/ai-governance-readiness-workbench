"""EVL-01 / EVL-02 / EVL-06 corpus adapters (WB-029).

The matrix is ground truth and the label is a consequence, so the tests are
mostly about derivation: n/a excluded rather than counted against, lane_b
excluded, "?" making a label unsound rather than silently scored.

The case that produced a wrong answer before is the one worth naming: M3.6_a
carried `full` for a week while failing three elements. Derivation from the
matrix is what makes that impossible; test_partial_when_some_elements_fail is
that case in miniature.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

import eval_adapters as ea


M3_12 = """
control: M3.12
documents: [M3.12_a, M3.12_b, M3.12_c]
elements:
  - id: e0
    lane: b
    text: register integrity
    a: "n/a"
    b: "n/a"
    c: "n/a"
    where: not judged from documents
  - id: e1
    text: changes raised as changes
    a: "Y"
    b: "Y"
    c: "N"
    where: section 'Retraining treated as change'
  - id: e2
    text: authorisation before production action
    a: "Y"
    b: "N"
    c: "N"
    where: section 'Approval before implementation'
"""


def _corpus(tmp_path: Path, control: str, body: str) -> Path:
    d = tmp_path / control
    d.mkdir(parents=True)
    (d / "elements.yaml").write_text(textwrap.dedent(body).strip() + "\n")
    return tmp_path


# --- label derivation -------------------------------------------------------

def _els(body=M3_12):
    return yaml.safe_load(body)["elements"]


def test_full_when_every_applicable_element_is_evidenced():
    assert ea.derive_label("a", _els())["level"] == "full"


def test_partial_when_some_elements_fail():
    assert ea.derive_label("b", _els())["level"] == "partial"


def test_none_when_no_element_is_evidenced():
    assert ea.derive_label("c", _els())["level"] == "none"


def test_lane_b_elements_are_excluded_from_the_label():
    d = ea.derive_label("a", _els())
    assert d["elements_applicable"] == 2, "e0 is lane_b and must not be counted"


def test_not_applicable_is_excluded_rather_than_counted_against():
    els = [{"id": "e1", "a": "Y"}, {"id": "e2", "a": "n/a"}]
    d = ea.derive_label("a", els)
    assert d["level"] == "full", "an unmet applies_when must not prevent full"
    assert d["elements_applicable"] == 1


def test_undecided_element_makes_the_label_unsound():
    els = [{"id": "e1", "a": "Y"}, {"id": "e2", "a": "?"}]
    d = ea.derive_label("a", els)
    assert d["elements_undecided"] == 1
    assert d["label_unsound"] is True, "a ? is a finding, not an oversight"


def test_document_with_nothing_in_scope_has_no_label():
    d = ea.derive_label("a", [{"id": "e1", "a": "n/a"}])
    assert d["level"] is None
    assert d["label_unsound"] is True


def test_missing_column_is_treated_as_undecided_not_as_no():
    d = ea.derive_label("z", _els())
    assert d["elements_undecided"] == 2
    assert d["label_unsound"] is True


# --- EVL-01: completeness ---------------------------------------------------

def test_complete_triple_is_not_flagged(tmp_path):
    root = _corpus(tmp_path, "M3.12", M3_12)
    rows = ea.corpus_case_rows(root, overlay={})
    assert len(rows) == 3
    assert not any(r["incomplete_set"] for r in rows)
    assert sorted(r["level"] for r in rows) == ["full", "none", "partial"]


def test_missing_level_flags_every_row_of_that_control(tmp_path):
    body = M3_12.replace("documents: [M3.12_a, M3.12_b, M3.12_c]",
                         "documents: [M3.12_a, M3.12_b]")
    root = _corpus(tmp_path, "M3.12", body)
    rows = ea.corpus_case_rows(root, overlay={})
    assert all(r["incomplete_set"] for r in rows), \
        "EVL-01 names the control whichever row it reports"


def test_controls_are_independent(tmp_path):
    _corpus(tmp_path, "M3.12", M3_12)
    _corpus(tmp_path, "M3.6", M3_12.replace("M3.12", "M3.6").replace(
        "documents: [M3.6_a, M3.6_b, M3.6_c]", "documents: [M3.6_a, M3.6_b]"))
    rows = ea.corpus_case_rows(tmp_path, overlay={})
    flagged = {r["control_id"] for r in rows if r["incomplete_set"]}
    assert "M3.12" not in flagged


# --- EVL-02: requirement binding -------------------------------------------

def test_unbound_case_is_broken_but_not_stale(tmp_path):
    root = _corpus(tmp_path, "M3.12", M3_12)
    r = ea.corpus_case_rows(root, overlay={})[0]
    assert r["requirement_sha"] is None
    assert r["requirement_sha_mismatch"] is False, "absent is not a mismatch"
    assert r["requirement_binding_broken"] is True


def test_matching_sha_is_neither_stale_nor_broken(tmp_path):
    overlay = {"controls": {"M3.12": {"requirement": "text", "elements": []}}}
    live = ea.requirement_sha("M3.12", overlay)
    root = _corpus(tmp_path, "M3.12", f"requirement_sha: {live}\n" + M3_12)
    r = ea.corpus_case_rows(root, overlay=overlay)[0]
    assert r["requirement_sha_mismatch"] is False
    assert r["requirement_binding_broken"] is False


def test_changed_requirement_makes_cases_stale(tmp_path):
    overlay = {"controls": {"M3.12": {"requirement": "text", "elements": []}}}
    live = ea.requirement_sha("M3.12", overlay)
    root = _corpus(tmp_path, "M3.12", f"requirement_sha: {live}\n" + M3_12)
    changed = {"controls": {"M3.12": {"requirement": "text, amended", "elements": []}}}
    rows = ea.corpus_case_rows(root, overlay=changed)
    assert all(r["requirement_sha_mismatch"] for r in rows)


def test_sha_is_stable_under_reformatting():
    a = {"controls": {"M3.12": {"requirement": "text", "elements": [{"id": "e1"}]}}}
    b = {"controls": {"M3.12": {"elements": [{"id": "e1"}], "requirement": "text"}}}
    assert ea.requirement_sha("M3.12", a) == ea.requirement_sha("M3.12", b), \
        "key order is formatting, not a requirement change"


def test_sha_is_none_for_a_control_the_overlay_does_not_name():
    assert ea.requirement_sha("M1.1", {"controls": {}}) is None


# --- EVL-06: provenance -----------------------------------------------------

def test_absent_decided_by_is_unattributed_not_defaulted(tmp_path):
    root = _corpus(tmp_path, "M3.12", M3_12)
    rows = ea.corpus_element_rows(root)
    assert {r["decided_by"] for r in rows} == {"unattributed"}


def test_decided_by_is_carried_through(tmp_path):
    body = M3_12.replace("    text: changes raised as changes",
                         "    decided_by: claude-unconfirmed\n    text: changes raised as changes")
    root = _corpus(tmp_path, "M3.12", body)
    rows = ea.corpus_element_rows(root)
    unconfirmed = [r for r in rows if r["decided_by"] == "claude-unconfirmed"]
    assert len(unconfirmed) == 3, "one row per document for that element"


def test_element_rows_cover_every_document_and_element(tmp_path):
    root = _corpus(tmp_path, "M3.12", M3_12)
    assert len(ea.corpus_element_rows(root)) == 3 * 3


def test_citation_presence_is_recorded(tmp_path):
    body = M3_12.replace("    where: section 'Approval before implementation'", "    where: ''")
    root = _corpus(tmp_path, "M3.12", body)
    rows = ea.corpus_element_rows(root)
    assert any(not r["has_citation"] for r in rows), \
        "a bare Y cannot be confirmed in under a minute; the row has to say so"


# --- robustness -------------------------------------------------------------

def test_empty_corpus_returns_no_rows(tmp_path):
    assert ea.corpus_case_rows(tmp_path, overlay={}) == []
    assert ea.corpus_element_rows(tmp_path) == []


def test_incomplete_matrix_file_is_skipped(tmp_path):
    d = tmp_path / "M9.9"
    d.mkdir()
    (d / "elements.yaml").write_text("control: M9.9\n")
    assert ea.corpus_case_rows(tmp_path, overlay={}) == []
