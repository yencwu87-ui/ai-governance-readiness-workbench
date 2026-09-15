"""WB-038 — choosing an evidence folder without typing a path.

Three ways in, because none of them works everywhere:

  browse    An in-app directory browser. Pure Python, no OS dependency, works whether the
            workbench runs on this machine or on a server. Always available, so it is the
            fallback the other two degrade to.
  native    The operating system's own folder dialog, via osascript / zenity / PowerShell.
            Only correct when the browser and the Streamlit server are the same machine —
            on a remote deployment the dialog opens on the SERVER, invisibly, and hangs.
            `local_runtime()` is what decides whether to offer it.
  paste     The existing text box. Kept, because pasting a path is still the fastest route
            for anyone who already has one.

Nothing here reads file contents or recurses. It lists directory names so a person can point
at one, and the scanner does the rest — including its own self-scan refusal, which this module
deliberately does not duplicate.
"""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

#: The native dialog is a blocking OS call. If the user walks away from it, the Streamlit run
#: should not be held open indefinitely.
NATIVE_TIMEOUT_S = 120

#: Directories that are never useful to scan and clutter the browser.
_HIDE = {"__pycache__", "node_modules", ".git", ".venv", "venv", ".cache", ".pytest_cache"}


def home() -> Path:
    return Path.home()


def safe_path(raw: str | os.PathLike | None) -> Path | None:
    """An existing directory, or None. Never raises on a malformed or unreadable path."""
    if not raw:
        return None
    try:
        p = Path(raw).expanduser()
        return p if p.is_dir() else None
    except (OSError, ValueError, RuntimeError):
        return None


def list_subdirs(path: str | os.PathLike, show_hidden: bool = False) -> list[str]:
    """Immediate subdirectory names, sorted case-insensitively.

    Returns [] rather than raising when the directory cannot be read — a permission error on
    one folder should narrow what the browser offers, not end the session.
    """
    p = safe_path(path)
    if p is None:
        return []
    out = []
    try:
        for entry in os.scandir(p):
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = entry.name
            if name in _HIDE:
                continue
            if not show_hidden and name.startswith("."):
                continue
            out.append(name)
    except (OSError, PermissionError):
        return []
    return sorted(out, key=str.lower)


def parent_of(path: str | os.PathLike) -> str | None:
    """The parent directory, or None at the filesystem root."""
    p = safe_path(path)
    if p is None:
        return None
    parent = p.parent
    return str(parent) if parent != p else None


def breadcrumbs(path: str | os.PathLike, max_parts: int = 4) -> list[tuple[str, str]]:
    """[(label, absolute_path)] from an ancestor down to `path`, trimmed to the last
    `max_parts` so a deep path does not wrap across the column."""
    p = safe_path(path)
    if p is None:
        return []
    parts: list[tuple[str, str]] = []
    cur = p
    while True:
        parts.append((cur.name or str(cur), str(cur)))
        nxt = cur.parent
        if nxt == cur:
            break
        cur = nxt
    parts.reverse()
    return parts[-max_parts:] if len(parts) > max_parts else parts


def local_runtime() -> bool:
    """Is the browser almost certainly on the same machine as this process?

    A native folder dialog opened by a remote server is not merely useless — it blocks the
    server on a dialog nobody can see. Erring toward False costs a convenience; erring toward
    True costs a hung session, so every signal of a hosted deployment disables it.
    """
    if os.environ.get("WB_DISABLE_NATIVE_PICKER"):
        return False
    for var in ("STREAMLIT_SERVER_HEADLESS", "DYNO", "KUBERNETES_SERVICE_HOST",
                "CODESPACES", "GITPOD_WORKSPACE_ID", "AWS_EXECUTION_ENV"):
        if os.environ.get(var):
            return False
    if os.path.exists("/.dockerenv"):
        return False
    try:
        from streamlit import config as _cfg
        addr = str(_cfg.get_option("browser.serverAddress") or "localhost")
        if addr not in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return False
    except Exception:
        pass
    if platform.system() == "Darwin":
        return True
    if platform.system() == "Windows":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _native_command(start: str | None) -> list[str] | None:
    system = platform.system()
    if system == "Darwin":
        default = f' default location POSIX file "{start}"' if start else ""
        return ["osascript", "-e",
                f'POSIX path of (choose folder with prompt "Choose the evidence folder"{default})']
    if system == "Windows":
        ps = ("Add-Type -AssemblyName System.Windows.Forms;"
              "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
              "$d.Description = 'Choose the evidence folder';"
              "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath }")
        return ["powershell", "-NoProfile", "-Command", ps]
    for binary, args in (("zenity", ["--file-selection", "--directory",
                                     "--title=Choose the evidence folder"]),
                         ("kdialog", ["--getexistingdirectory", start or str(home())])):
        if _which(binary):
            return [binary, *args]
    return None


def _which(binary: str) -> bool:
    from shutil import which
    return which(binary) is not None


def native_available(start: str | None = None) -> bool:
    return local_runtime() and _native_command(start) is not None


def pick_folder_native(start: str | None = None) -> tuple[str | None, str | None]:
    """Open the OS folder dialog. Returns (path, error).

    Both may be None: the user cancelled, which is neither a path nor a failure and must not
    be reported as one.
    """
    cmd = _native_command(start)
    if cmd is None:
        return None, "No folder dialog is available on this system."
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=NATIVE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, f"The folder dialog was open for more than {NATIVE_TIMEOUT_S}s with no choice made."
    except (OSError, ValueError) as e:
        return None, f"Could not open the folder dialog ({type(e).__name__}: {e})."
    chosen = (r.stdout or "").strip()
    if not chosen:
        return None, None                      # cancelled
    p = safe_path(chosen)
    if p is None:
        return None, f"That is not a readable directory: {chosen}"
    return str(p), None


def remember(recent: list[str], path: str, limit: int = 5) -> list[str]:
    """Most-recent-first, de-duplicated, capped. Pure so the app does not hand-roll it."""
    out = [path] + [p for p in recent if p != path]
    return out[:limit]
