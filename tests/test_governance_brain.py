from types import SimpleNamespace

from governance.knowledge import format_context, retrieve, validate_brain


def test_brain_validates_and_has_unique_ids():
    assert validate_brain() == []
    rows = retrieve("M3.12", "change implementation and verification", "approved ticket with deployment", role="assessor")
    assert rows
    assert rows[0]["memory_id"] in {"GOV-MEM-0001", "GOV-MEM-0002", "GOV-MEM-0003", "GOV-MEM-0004"}
    assert "tier=" in format_context(rows)


def test_assessor_and_challenger_retrieve_different_role_context():
    a = retrieve("M3.12", "change implementation", "approval only", role="assessor")
    c = retrieve("M3.12", "change implementation", "approval only", role="challenger")
    assert any(x["memory_id"] == "GOV-MEM-0001" for x in a)
    assert any(x["memory_id"] == "GOV-MEM-0005" for x in c)


def test_brain_is_context_only_not_rating():
    rows = retrieve("M3.12", "change implementation", "approval only")
    assert all("sufficiency" not in r for r in rows)


def test_brain_is_part_of_assessment_identity():
    from governance.assessment_identity import build_assessment_identity
    a = build_assessment_identity(engine_version="v0.4.0", model="test-model")
    assert "governance/knowledge/brain.yaml" in a["artefact_sha256"]
    assert a["artefact_sha256"]["governance/knowledge/brain.yaml"]
