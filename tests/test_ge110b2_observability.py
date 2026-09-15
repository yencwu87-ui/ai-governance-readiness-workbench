"""GE-110b.2 — not every undiscriminating element is a corpus gap."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.corpus_adequacy import characterise, classify_gaps, discrimination_target, parse_labels

MD = """
### `x_a.md` → **none**

| element | | where |
|---|---|---|
| `e1` | N | n |
| `e8` | n/a | n |
| `e14` | N | n |

---

### `x_b.md` → **none**

| element | | where |
|---|---|---|
| `e1` | N | n |
| `e8` | n/a | n |
| `e14` | N | n |
"""

ELS = [{"id": "e1", "observability": "ordinary"},
       {"id": "e8", "observability": "conditional", "precondition": "high_risk_materiality"},
       {"id": "e14", "observability": "out_of_band",
        "observability_note": "held outside any single validation pack"}]


def test_three_reasons_for_undiscriminating_are_kept_apart():
    split = classify_gaps(characterise(parse_labels(MD), elements=ELS), ELS)
    assert split["real_gaps"] == ["e1"]
    assert split["precondition_never_held"] == ["e8"]
    assert split["outside_this_evidence_class"] == ["e14"]


def test_only_real_gaps_are_targets_for_new_cases():
    """Forcing a case to make an out-of-band element decidable is how a corpus becomes fiction."""
    t = discrimination_target(characterise(parse_labels(MD), elements=ELS), ELS)
    assert t["needs_a_discriminating_observation"] == ["e1"]
    assert "e14" not in t["needs_a_discriminating_observation"]
    assert "e8" not in t["needs_a_discriminating_observation"]


def test_an_out_of_band_element_is_reported_as_a_capability_gap():
    split = classify_gaps(characterise(parse_labels(MD), elements=ELS), ELS)
    cap = split["capability_gaps"]
    assert len(cap) == 1 and cap[0]["element"] == "e14"
    assert "other than the evidence bundle" in cap[0]["needs"]


def test_an_unclassified_element_stays_a_target_rather_than_being_excused():
    els = [{"id": "e1"}]
    md = MD.replace("| `e8` | n/a | n |\n", "").replace("| `e14` | N | n |\n", "")
    t = discrimination_target(characterise(parse_labels(md), elements=els), els)
    assert "e1" in t["needs_a_discriminating_observation"]


def test_the_real_contract_carries_the_classification():
    doc = yaml.safe_load((ROOT / "eval/corpus/M3.6/elements.yaml").read_text(encoding="utf-8"))
    kinds = {e["id"]: e.get("observability") for e in doc["elements"]}
    assert kinds["e14"] == "out_of_band"
    assert kinds["e1"] == "ordinary"
    assert all(kinds[e] == "conditional" for e in ("e4", "e5", "e8", "e9", "e10", "e11"))


def test_e5_and_e8_do_not_share_a_precondition():
    """The contract distinguishes them and the classification must not collapse them.

    e5 conditions on "where relevant to the AI use case"; e8 on "For AI assessed as high risk
    materiality". Deriving fairness applicability from risk tier would make the corpus test a
    rule the requirement does not contain.
    """
    doc = yaml.safe_load((ROOT / "eval/corpus/M3.6/elements.yaml").read_text(encoding="utf-8"))
    pre = {e["id"]: e.get("precondition") for e in doc["elements"]}
    assert pre["e5"] != pre["e8"]
    assert pre["e8"] == pre["e9"] == "high_risk_materiality"
    assert pre["e5"] == "use_case_impact_relevance"
