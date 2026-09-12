from pathlib import Path
import json
import pytest

from challenge_dossier import create_dossier, respond, append, latest_dossier


def _dossier():
    return create_dossier(
        control_id="M3.12", control_title="Change control", reviewer="Reviewer",
        blind={"sufficiency": "partial", "maturity": 3, "reason": "Verification is not evidenced."},
        challenges=[{
            "severity": "high", "confidence": "high", "observation": "Reviewer read Full.",
            "evidence_basis": ["approval exists"], "requirement_basis": ["verification required"],
            "knowledge_basis": [{"memory_id": "GOV-MEM-1", "role": "precedent"}],
            "inference": "Approval does not prove verification.",
            "challenge": "Show post-implementation verification.", "recommended_action": "request_evidence"
        }], challenger_model="test-model", knowledge=[{"memory_id": "GOV-MEM-1"}],
        reasoning_schema="v0.4.structured-challenge.1",
    )


def test_dossier_starts_open():
    d = _dossier()
    assert d["status"] == "open"
    assert d["challenges"][0]["response"] is None


def test_response_closes_single_challenge():
    d = respond(_dossier(), 1, response="evidence_provided", reviewer="Reviewer", note="Provided verification record.", evidence=["VR-001"])
    assert d["status"] == "closed"
    assert d["challenges"][0]["response"]["disposition"] == "evidence_provided"
    assert d["challenges"][0]["response"]["evidence"] == ["VR-001"]


def test_non_evidence_response_requires_note():
    with pytest.raises(ValueError):
        respond(_dossier(), 1, response="reject", reviewer="Reviewer", note="")


def test_append_and_latest(tmp_path: Path):
    path = tmp_path / "challenge_dossiers.jsonl"
    d1 = _dossier()
    append(d1, path)
    d2 = respond(d1, 1, response="accept", reviewer="Reviewer", note="Challenge accepted.")
    append(d2, path)
    got = latest_dossier("M3.12", path)
    assert got["status"] == "closed"
