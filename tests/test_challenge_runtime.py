"""Runtime containment tests for interactive challenger transport failures."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_challenge_timeout_becomes_blocked_envelope(monkeypatch):
    import challenge as C

    monkeypatch.setattr(C, "_run_claim_vet", lambda *a, **k: ([], None))
    monkeypatch.setattr(C, "_challenge_llm", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("Ollama request timed out after 75s")
    ))

    control = {"id": "M3.6", "lib": "MAS", "title": "M3.6", "req": "requirement"}
    out = C.challenge(control, "evidence", {"sufficiency": "partial", "reason": "read"})

    assert out["validation_status"] == "blocked"
    assert out["produced_a_result"] is False
    assert out["challenges"] == []
    assert "timed out" in out["validation_error"]
