from pathlib import Path

from eval.label_governance import audit, distribution_readiness

REPO = Path(__file__).parents[1]
SET = REPO / "eval" / "golden_set.jsonl"


def test_current_labels_have_no_obvious_rubric_contradictions():
    report = audit(SET)
    assert report["status"] == "PASS", report["problems"]


def test_current_set_is_distribution_ready():
    report = audit(SET, min_each=5)
    assert report["distribution_status"] == "PASS"
    assert report["label_distribution"] == {"none": 11, "partial": 8, "full": 11}
    assert not report["distribution_readiness"]["missing_or_thin"]


def test_distribution_readiness_requires_all_classes():
    assert distribution_readiness({"none": 5, "partial": 5, "full": 5}, min_each=5)["ready"]
    assert not distribution_readiness({"none": 10, "partial": 5, "full": 1}, min_each=5)["ready"]
