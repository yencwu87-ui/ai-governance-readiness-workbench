"""WB-038 — folder browsing helpers.

Everything testable here is pure: listing, walking and remembering. The native dialog is
exercised only through its command construction and its failure paths, because opening a real
OS dialog in a test would block forever.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import folder_picker as fp  # noqa: E402


@pytest.fixture
def tree(tmp_path):
    for d in ("alpha", "Beta", "gamma", ".hidden", "__pycache__", "node_modules"):
        (tmp_path / d).mkdir()
    (tmp_path / "alpha" / "nested").mkdir()
    (tmp_path / "a_file.txt").write_text("not a directory")
    return tmp_path


# ---------------- listing ----------------

def test_lists_only_directories_case_insensitively(tree):
    assert fp.list_subdirs(tree) == ["alpha", "Beta", "gamma"]


def test_noise_directories_are_never_listed(tree):
    assert "__pycache__" not in fp.list_subdirs(tree, show_hidden=True)
    assert "node_modules" not in fp.list_subdirs(tree, show_hidden=True)


def test_hidden_directories_are_opt_in(tree):
    assert ".hidden" not in fp.list_subdirs(tree)
    assert ".hidden" in fp.list_subdirs(tree, show_hidden=True)


def test_an_unreadable_or_missing_directory_narrows_the_browser_rather_than_raising(tmp_path):
    assert fp.list_subdirs(tmp_path / "does-not-exist") == []
    assert fp.list_subdirs(None) == []
    assert fp.list_subdirs("") == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_permission_denied_returns_empty_not_an_exception(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "inside").mkdir()
    locked.chmod(0o000)
    try:
        assert fp.list_subdirs(locked) == []
    finally:
        locked.chmod(0o755)


# ---------------- walking ----------------

def test_safe_path_rejects_files_and_nonsense(tree):
    assert fp.safe_path(tree) is not None
    assert fp.safe_path(tree / "a_file.txt") is None
    assert fp.safe_path("\0bad") is None
    assert fp.safe_path(None) is None


def test_parent_of_stops_at_the_root():
    assert fp.parent_of("/") is None
    assert fp.parent_of(Path.home()) is not None


def test_breadcrumbs_end_at_the_current_folder_and_are_trimmed(tree):
    deep = tree / "alpha" / "nested"
    crumbs = fp.breadcrumbs(deep, max_parts=2)
    assert len(crumbs) == 2
    assert crumbs[-1][1] == str(deep)
    assert crumbs[-1][0] == "nested"


def test_every_breadcrumb_target_is_a_real_directory(tree):
    for _, target in fp.breadcrumbs(tree / "alpha" / "nested"):
        assert fp.safe_path(target) is not None


# ---------------- recent ----------------

def test_remember_is_most_recent_first_deduplicated_and_capped():
    r = []
    for p in ("/a", "/b", "/c", "/a"):
        r = fp.remember(r, p, limit=3)
    assert r == ["/a", "/c", "/b"]


# ---------------- the native dialog ----------------

def test_native_is_refused_on_anything_that_looks_hosted(monkeypatch):
    """A dialog opened by a remote server blocks on a window nobody can see. Every signal of
    a hosted deployment has to disable it — a lost convenience beats a hung session."""
    for var in ("STREAMLIT_SERVER_HEADLESS", "DYNO", "KUBERNETES_SERVICE_HOST",
                "CODESPACES", "GITPOD_WORKSPACE_ID", "WB_DISABLE_NATIVE_PICKER"):
        monkeypatch.setenv(var, "1")
        assert fp.local_runtime() is False, var
        monkeypatch.delenv(var)


def test_native_is_refused_when_served_to_another_host(monkeypatch):
    monkeypatch.setattr(fp.platform, "system", lambda: "Darwin")

    class _Cfg:
        @staticmethod
        def get_option(_):
            return "workbench.internal.example.com"
    monkeypatch.setitem(sys.modules, "streamlit", type("m", (), {"config": _Cfg})())
    assert fp.local_runtime() is False


def test_cancelling_the_dialog_is_not_an_error(monkeypatch):
    monkeypatch.setattr(fp.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(fp.subprocess, "run",
                        lambda *a, **k: type("r", (), {"stdout": "", "stderr": ""})())
    path, err = fp.pick_folder_native()
    assert path is None and err is None


def test_a_timed_out_dialog_reports_and_does_not_raise(monkeypatch):
    monkeypatch.setattr(fp.platform, "system", lambda: "Darwin")

    def boom(*a, **k):
        raise fp.subprocess.TimeoutExpired(cmd="osascript", timeout=fp.NATIVE_TIMEOUT_S)
    monkeypatch.setattr(fp.subprocess, "run", boom)
    path, err = fp.pick_folder_native()
    assert path is None and "no choice made" in err


def test_a_returned_path_that_is_not_a_directory_is_rejected(monkeypatch, tree):
    monkeypatch.setattr(fp.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(fp.subprocess, "run",
                        lambda *a, **k: type("r", (), {"stdout": str(tree / "a_file.txt")})())
    path, err = fp.pick_folder_native()
    assert path is None and "not a readable directory" in err


def test_a_chosen_directory_comes_back_normalised(monkeypatch, tree):
    monkeypatch.setattr(fp.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(fp.subprocess, "run",
                        lambda *a, **k: type("r", (), {"stdout": f"{tree}/alpha/\n"})())
    path, err = fp.pick_folder_native()
    assert err is None and path == str(tree / "alpha")


@pytest.mark.parametrize("system", ["Darwin", "Windows"])
def test_a_command_exists_for_each_desktop_platform(monkeypatch, system):
    monkeypatch.setattr(fp.platform, "system", lambda: system)
    assert fp._native_command(None) is not None


def test_no_command_on_a_headless_linux_box(monkeypatch):
    monkeypatch.setattr(fp.platform, "system", lambda: "Linux")
    monkeypatch.setattr(fp, "_which", lambda b: False)
    assert fp._native_command(None) is None
    assert fp.native_available() is False
