"""WB-021: the scanner must not read the workbench's own state and outputs as evidence.

Run from repo/ with the venv active:
    pytest test_scan_scope_wb021.py -q
"""
from pathlib import Path

from scanner import DOC_EXT, iter_files, scan_environment


def _tree(root: Path):
    (root / "policies").mkdir()
    (root / "policies" / "ai-policy.md").write_text("The organisation assesses model changes.")
    (root / "data").mkdir()
    (root / "data" / "assessments.json").write_text('{"ai": {}}')
    (root / "data" / "backups").mkdir()
    (root / "data" / "backups" / "assessments-20260909-091032.json").write_text("{}")
    (root / "playbook_assessed_2026-09-07.xlsx").write_bytes(b"PK\x03\x04")
    (root / "graphify-out").mkdir()
    (root / "graphify-out" / "graph.json").write_text("{}")
    (root / "notes.md").write_text("Change records are kept in Jira.")


def test_own_state_and_outputs_are_not_indexed(tmp_path):
    _tree(tmp_path)
    names = {p.name for p in iter_files(str(tmp_path), DOC_EXT)}
    assert names == {"ai-policy.md", "notes.md"}
    assert not any("assessments" in n for n in names)
    assert not any(n.startswith("playbook_assessed_") for n in names)


def test_a_skipped_name_can_still_be_the_scan_root(tmp_path):
    """The skip is relative to the root. Pointing the scanner at sample_evidence/ - or any
    folder whose own name is in SKIP_DIRS - must still scan it."""
    root = tmp_path / "sample_evidence"
    root.mkdir()
    (root / "incident-runbook.md").write_text("Escalation path for model incidents.")
    assert {p.name for p in iter_files(str(root), DOC_EXT)} == {"incident-runbook.md"}


def test_client_folder_under_a_data_path_is_not_excluded(tmp_path):
    """Only components below the scan root are tested, so a client path containing
    'data' no longer silently excludes everything."""
    root = tmp_path / "data" / "acme-evidence"
    root.mkdir(parents=True)
    (root / "controls.md").write_text("Access reviews run quarterly.")
    assert {p.name for p in iter_files(str(root), DOC_EXT)} == {"controls.md"}


def test_environment_scan_uses_the_same_scope(tmp_path):
    _tree(tmp_path)
    (tmp_path / "data" / "secrets.env").write_text("KEY=x")
    (tmp_path / "prompt_v2.txt").write_text("You are an assistant.")
    paths = {s.path for s in scan_environment(str(tmp_path))}
    assert not any(p.startswith("data/") for p in paths)
    assert "prompt_v2.txt" in paths
