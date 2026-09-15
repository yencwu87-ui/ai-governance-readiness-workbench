"""GE-110b.1 — a corpus can be valid and still incapable of measuring anything."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.corpus_adequacy import characterise, characterise_path, parse_labels, report

MD = """
### `x_a.md` → **partial**

| element | | where |
|---|---|---|
| `e1` | N | shared note |
| `e2` | Y | shared note |

---

### `x_b.md` → **none**

| element | | where |
|---|---|---|
| `e1` | N | shared note |
| `e2` | N | shared note |
"""


def test_labels_parse_into_cases_and_verdicts():
    got = parse_labels(MD)
    assert set(got) == {"x_a.md", "x_b.md"}
    assert got["x_a.md"]["label"] == "partial"
    assert got["x_a.md"]["verdicts"]["e2"][0] == "Y"


def test_a_missing_outcome_is_named():
    c = characterise(parse_labels(MD))
    assert "full" in c["missing_outcomes"]


def test_the_degenerate_baseline_is_computed():
    """The number to read first: what an assessor scores by ignoring the evidence."""
    c = characterise(parse_labels(MD))
    assert c["degenerate_answer"] == "N"
    assert c["degenerate_baseline"] == 0.75


def test_an_element_no_case_evidences_is_flagged():
    c = characterise(parse_labels(MD))
    assert "e1" in c["never_met_elements"]


def test_near_identical_cases_are_measured_not_assumed():
    c = characterise(parse_labels(MD))
    assert c["min_pairwise_distance"] == 1


def test_shared_justification_across_cases_is_flagged():
    """Per-element text is not per-case provenance."""
    c = characterise(parse_labels(MD))
    assert set(c["elements_with_shared_justification"]) == {"e1", "e2"}


def test_distinct_justification_is_not_flagged():
    md = MD.replace("| `e2` | Y | shared note |", "| `e2` | Y | a-specific note |", 1)
    c = characterise(parse_labels(md))
    assert "e2" not in c["elements_with_shared_justification"]


def test_the_declared_contract_governs_the_element_list():
    """Elements the contract declares but no case mentions are unexercised, not absent."""
    c = characterise(parse_labels(MD),
                     elements=[{"id": "e1"}, {"id": "e2"}, {"id": "e3"}])
    assert c["n_elements"] == 3
    assert "e3" in c["unexercised_elements"]


def test_nothing_here_blocks():
    """Adequacy reports; it does not gate. Which claim a corpus can support is the caller's call."""
    c = characterise(parse_labels(MD))
    assert "status" not in c and "executable" not in c


def test_it_runs_on_the_real_corpora():
    for control in ("M3.6", "M3.12"):
        p = ROOT / "eval" / "corpus" / control / "LABELS.md"
        if not p.exists():
            continue
        c = characterise_path(p)
        assert c["n_cases"] >= 1
        assert isinstance(report(c), str)


def test_m36_is_recorded_as_inadequate_today():
    """Pins the finding so a later 'fix' that does not change the corpus cannot hide it."""
    c = characterise_path(ROOT / "eval" / "corpus" / "M3.6" / "LABELS.md")
    assert "full" in c["missing_outcomes"]
    assert c["min_pairwise_distance"] == 1
    assert c["degenerate_baseline"] >= 0.6
