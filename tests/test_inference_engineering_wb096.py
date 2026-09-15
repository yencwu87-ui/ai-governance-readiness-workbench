from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inference.policy import TaskSignals, build_plan
from governance.control_contract import requirement_context
from governance.element_contract import element_testing_context, validate_elements


def test_m36_has_atomic_element_contract():
    ctx = requirement_context("M3.6", "MAS")
    assert [e["id"] for e in ctx["elements"]] == [f"e{i}" for i in range(1, 15)]
    assert all(len(e["text"].split()) >= 5 for e in ctx["elements"])


def test_m36_verification_metadata_cannot_create_extra_elements():
    ctx = requirement_context("M3.6", "MAS")
    hints = element_testing_context("M3.6", "MAS")
    assert set(hints) == {e["id"] for e in ctx["elements"]}


def test_difficulty_escalates_on_disagreement_and_failures(monkeypatch):
    monkeypatch.setenv("WB_MODEL_STRONG", "qwen2.5:14b")
    plan = build_plan(TaskSignals(role="challenge", control_id="M3.6", reviewer_disagreement=True, prior_failures=1))
    assert plan.tier == "critical"
    assert plan.model == "qwen2.5:14b"


def test_plugin_registry_exposes_capabilities():
    from plugins.registry import list_plugins
    github = next(x for x in list_plugins() if x["id"] == "github")
    assert "observe.branch_protection" in github["capabilities"]
    assert github["side_effects"] == ["read_only"]


def test_element_scoped_retrieval_does_not_expand_governed_element_set():
    from governance.knowledge_resolver import resolve
    from governance.element_registry import elements_for
    class C:
        id = "M3.6"
        lib = "MAS"
        req = "Independent validation"
    b = resolve(C(), "validation report", role="assessor", force_web=False, element_ids=["e7"])
    assert b["element_scope"] == ["e7"]
    assert set(b["elements"]) == {"e7"}
    assert b["elements"]["e7"]["element_key"] == "M3.6.R1.e7"
    assert [e["element_id"] for e in elements_for("M3.6", "MAS")] == [f"e{i}" for i in range(1, 15)]
