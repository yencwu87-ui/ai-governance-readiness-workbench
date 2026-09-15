import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.control_evaluator import evaluate_governed_control
from plugins.validation_pack import ValidationPackPlugin
from services.governance_service import contract_hash
from types import SimpleNamespace
import json


def _control():
    return SimpleNamespace(
        id="M3.6", lib="MAS", title="M3.6",
        req="M3.6 validation requirements",
        elements=[f"e{i}" for i in range(1, 15)],
        boundary={},
    )


def test_validation_pack_plugin_emits_canonical_observations_and_m36_evaluates():
    path = ROOT / "eval" / "observation_fixtures" / "M3.6_g_observations.json"
    obs = ValidationPackPlugin().collect({"id": "M3.6_g", "path": str(path)})
    assert obs
    assert all(o.schema == "ge111.observation.1" for o in obs)
    assert all(o.content_hash for o in obs)
    result = evaluate_governed_control(
        control_id="M3.6", resource_id="M3.6_g",
        observations=obs, contract_hash=contract_hash(_control()),
    )
    assert result.status in {"PASS", "FAIL", "STALE", "NOT_TESTABLE", "ERROR"}
    assert len(result.element_results) == 13
    assert result.observation_refs == tuple(o.observation_id for o in obs)
