"""Overlay hand-written control requirements onto the controls loaded from the workbook.

The MAS sheet has no requirement column — LIBRARIES maps `req` to "MAS expectation area",
which is a heading — so every MAS control loads as "Expectation: <title>." and the assessor
was judging evidence sufficiency against a control title. This module supplies the missing
text from controls/mas_requirements.yaml.

Deliberately separate from playbook.py: the requirement text is a second-line judgement that
gets reviewed and versioned on its own cadence, and it must stay out of the workbook, where
write_back overwrites the "Evidence / artifact" column.

The overlay is optional. If the file is absent or unreadable the controls load exactly as
before, so a missing requirements file degrades to the old behaviour rather than breaking a
scan. It never applies to a control it does not name.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_PATH = Path("requirements/mas.yaml")

DEFAULT_SETTINGS = {
    "elements_replace_artefacts": True,
    "prompt_boundary": False,
    "element_scopes": ["model"],
}


def load_overlay(path: Path | str = DEFAULT_PATH) -> dict:
    """Read the overlay. Returns {} if the file is missing or will not parse.

    A malformed overlay is reported and ignored rather than raised: a scan that silently uses
    the old headings is recoverable, a scan that will not start is not. The caller can tell the
    difference by checking the return value.
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        import yaml
    except ImportError:
        print(f"!! {p} found but PyYAML is not installed — requirements not applied")
        return {}
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except Exception as e:
        print(f"!! {p} did not parse ({type(e).__name__}) — requirements not applied")
        return {}
    if not isinstance(data.get("controls"), dict):
        print(f"!! {p} has no controls: mapping — requirements not applied")
        return {}
    data.setdefault("settings", {})
    for k, v in DEFAULT_SETTINGS.items():
        data["settings"].setdefault(k, v)
    return data


def _elements_for(entry: dict, scopes: list[str]) -> list[str]:
    """Element texts the Lane A assessor should be asked about.

    Excluded:
      scope not in scopes  - programme-level elements a single document cannot evidence
      lane: b              - tested deterministically by a control pack, not judged from
                             documents. Sending one to the assessor asks a model to infer from
                             prose what a query answers exactly, and the corpus matrix already
                             records it as not applicable. Observed 2026-09-10: M3.12 e0
                             (change register integrity) reached the prompt and produced two
                             wrong ratings, because neither document is a register.

    Elements with no scope count as model-level; elements with no lane count as lane a.
    """
    out = []
    for e in entry.get("elements") or []:
        if not isinstance(e, dict) or not e.get("text"):
            continue
        if e.get("lane", "a") == "b":
            continue
        if e.get("scope", "model") in scopes:
            out.append(" ".join(str(e["text"]).split()))
    return out


def _boundary_text(entry: dict) -> str:
    b = entry.get("boundary") or {}
    parts = [f'{k}: {" ".join(str(b[k]).split())}' for k in ("none", "partial", "full") if b.get(k)]
    return " | ".join(parts)


def apply_overlay(controls_by_lib: dict, overlay: dict) -> dict:
    """Replace req and artefacts on any control the overlay names. Returns a small summary.

    Mutates the Control objects in place — they are plain dataclasses and the caller holds the
    only reference. The summary is returned so a caller can surface how many controls are still
    running on a heading rather than a requirement.
    """
    if not overlay:
        return {"applied": 0, "named": 0, "unmatched": [], "library": None}

    lib_name = overlay.get("library")
    entries = overlay.get("controls") or {}
    s = overlay["settings"]
    scopes = s["element_scopes"]

    seen, applied = set(), 0
    for lib, rows in controls_by_lib.items():
        if lib_name and lib != lib_name:
            continue
        for c in rows:
            cid = c.id.split()[0].rstrip("\u2605").strip()
            entry = entries.get(cid)
            if not isinstance(entry, dict):
                continue
            seen.add(cid)

            req = " ".join(str(entry.get("requirement", "")).split())
            if not req or req.startswith("TODO"):
                continue  # a placeholder is not a requirement; leave the workbook value alone

            if s["prompt_boundary"] and (bt := _boundary_text(entry)):
                req = f"{req}\n\nHow far the evidence must go — {bt}"
            c.req = req

            els = _elements_for(entry, scopes)
            if els:
                c.artefacts = "; ".join(els) if s["elements_replace_artefacts"] \
                    else "; ".join([c.artefacts] + els) if c.artefacts else "; ".join(els)
            applied += 1

    return {"applied": applied, "named": len(entries), "library": lib_name,
            "unmatched": sorted(set(entries) - seen)}


def load_controls_with_requirements(workbook, path: Path | str = DEFAULT_PATH):
    """load_controls() with the overlay applied. Returns (controls_by_lib, summary)."""
    from playbook import load_controls
    by_lib = load_controls(workbook)
    return by_lib, apply_overlay(by_lib, load_overlay(path))
