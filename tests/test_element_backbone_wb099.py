from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.element_registry import elements_for, get, validate_pointer
from governance.element_graph import make_envelope, attach_observation, attach_test


def test_element_registry_is_canonical_and_addressable():
    es = elements_for("M3.6", "MAS")
    assert [e["element_id"] for e in es] == [f"e{i}" for i in range(1, 15)]
    assert get("M3.6", "e7", "MAS")["element_key"] == "M3.6.R1.e7"
    assert validate_pointer("M3.6", "e7", "MAS")[0]
    assert not validate_pointer("M3.6", "e99", "MAS")[0]


def test_element_envelope_preserves_same_foreign_key_across_stages():
    env = make_envelope("M3.6", "e7", "MAS")
    attach_observation(env, {"observation_id": "obs1"}, capability="validation_record.inspect")
    attach_test(env, {"status": "pass"})
    assert env["element_key"] == "M3.6.R1.e7"
    assert env["observations"][0]["element_key"] == env["element_key"]
    assert env["tests"][0]["element_id"] == "e7"
