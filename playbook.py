"""Load control libraries from the AI Governance Playbook workbook and write results back."""
from __future__ import annotations

import datetime as dt
import os
import warnings
from dataclasses import dataclass, asdict, field
from functools import lru_cache
from pathlib import Path

from openpyxl import load_workbook

warnings.filterwarnings("ignore", message="Data Validation extension")

# sheet name -> (id column, title column, requirement column, owner column, crosswalk columns)
LIBRARIES = {
    "MAS": ("Control Library - MAS", "MAS ref", "MAS expectation area", "Primary MAS source", "Owner (role)", ["ISO 42001", "NIST AI RMF"]),
    "MGF Agentic": ("Control Library - MGF Agentic", "MGF Control ID", "Control / Recommended Measure", "Objective — what it bounds", "Owner (role)", ["MAS AIRG theme", "ISO/IEC 42001 Annex A"]),
    "SAFR": ("Control Library - SAFR", "SAFR Control ID", "Control / recommended measure", "Objective — what it bounds", "Owner (role)", ["MAS AIRG theme", "ISO/IEC 42001 Annex A"]),
    "ISO 42001": ("Control Library - ISO 42001", "Control ID", "Control Title", "Requirement (summary)", "Owner (role)", []),
    "NIST AI RMF": ("Control Library - NIST AI RMF", "Subcategory", "Category", "Subcategory outcome", "Owner (role)", []),
}
WRITEBACK_COLS = ["Status", "Maturity (1-5)", "Evidence / artifact", "Last reviewed", "Gap / notes"]

# Expected artefacts per control. The same header appears on every library sheet, so this needs
# no per-library mapping. WB-022: the column has been populated since the workbook was built and
# never reached the assessor. It matters most for MAS, where the requirement column is only the
# control title, so the model was being asked to judge sufficiency against a heading.
ARTEFACT_COL = "Evidence / artifact"

# ---------------------------------------------------------------------------
# Requirement overlay (WB-0nn)
#
# The MAS sheet has no requirement column. LIBRARIES maps `req` to "MAS expectation area",
# which is a heading, so all 30 MAS controls loaded as "Expectation: <title>. Source: <cite>"
# and the assessor was judging sufficiency against a control title. The overlay supplies the
# missing requirement text and the elements it decomposes into.
#
# Kept out of the workbook deliberately: write_back overwrites the artefact column, so
# load-bearing text on a control sheet has a known failure mode. A YAML file beside the
# control packs is also reviewable in a diff, which a spreadsheet cell is not.
#
# Searched rather than hardcoded, because the file has moved once already. Set
# WORKBENCH_REQUIREMENTS to override.
#
# requirements/mas.yaml is first because it is the authoritative file — the one the corpus
# LABELS.md names as the definition and the one carrying the full element set. The others are
# earlier drafts kept for reference. Ordering alone is not enough, though: a superseded draft
# that still parses is exactly what a search finds, and reading the wrong one produces a run
# that looks correct while measuring against the wrong requirement. So when more than one
# candidate exists the loader says which it took and what it ignored, once per process.
# ---------------------------------------------------------------------------
OVERLAY_ENV = "WORKBENCH_REQUIREMENTS"
OVERLAY_CANDIDATES = (
    "requirements/mas.yaml",
    "requirements/mas_requirements.yaml",
    "controls/mas_requirements.yaml",
    "mas_requirements.yaml",
)
_HERE = Path(__file__).resolve().parent
_announced = set()


def overlay_candidates_present() -> list[Path]:
    """Every candidate that exists, in precedence order. More than one means a stale draft
    is sitting where the loader looks."""
    return [_HERE / rel for rel in OVERLAY_CANDIDATES if (_HERE / rel).exists()]


def overlay_path() -> Path | None:
    env = os.environ.get(OVERLAY_ENV)
    if env:
        p = Path(env)
        return p if p.exists() else None
    found = overlay_candidates_present()
    if not found:
        return None
    if len(found) > 1 and str(found[0]) not in _announced:
        _announced.add(str(found[0]))
        others = ", ".join(str(p.relative_to(_HERE)) for p in found[1:])
        warnings.warn(
            f"more than one requirement overlay is present: using "
            f"{found[0].relative_to(_HERE)}, ignoring {others}. Delete or move the superseded "
            f"file — a draft that still parses will be found by any search-based loader.")
    return found[0]


@lru_cache(maxsize=4)
def _load_overlay(path_str: str, mtime: float) -> dict:
    import yaml
    return yaml.safe_load(Path(path_str).read_text(encoding="utf-8")) or {}


def load_overlay() -> dict:
    """The parsed overlay, or {} when there is none. Cached on path and mtime, so editing
    the YAML takes effect on the next load without restarting the app."""
    p = overlay_path()
    if not p:
        return {}
    try:
        return _load_overlay(str(p), p.stat().st_mtime)
    except Exception as e:  # a malformed overlay must not take the workbench down
        warnings.warn(f"requirement overlay at {p} could not be read ({e}); using the workbook as-is")
        return {}


def overlay_settings() -> dict:
    s = (load_overlay().get("settings") or {})
    return {
        # Replace the workbook's artefact string with the elements, or append to it. Appending
        # risks the model treating the artefact name as a separate requirement.
        "elements_replace_artefacts": bool(s.get("elements_replace_artefacts", True)),
        # Which element scopes the assessor evaluates. An element with no scope is `model`:
        # scope only has to be declared where it is not the ordinary case.
        "element_scopes": tuple(s.get("element_scopes") or ("model",)),
        # Put the boundary in the prompt. Off by default — it has never been probed.
        "prompt_boundary": bool(s.get("prompt_boundary", False)),
    }


def scoped_elements(control_id: str) -> list[dict]:
    """The overlay elements for one control that are in scope for assessment.

    `conditional_elements` are never returned: they apply only to a model class (genai,
    agentic) that the assessor cannot determine from the evidence, so including them would
    mark absent something the model was never in a position to find.
    """
    spec = (load_overlay().get("controls") or {}).get(control_id) or {}
    scopes = overlay_settings()["element_scopes"]
    return [e for e in (spec.get("elements") or [])
            if str(e.get("scope", "model")).lower() in scopes]


@dataclass
class Control:
    key: str
    lib: str
    id: str
    title: str
    req: str
    owner: str
    maps: str
    row: int  # 1-based worksheet row, used for write-back
    artefacts: str = ""  # WB-022: expected artefacts, as declared on the control row
    # WB-0nn: overlay elements in scope, as (id, text). Defaulted so positional construction
    # elsewhere still works, same as artefacts was.
    elements: tuple = ()
    boundary: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def _header_map(ws, header_row=3):
    return {str(c.value).strip(): c.column for c in ws[header_row] if c.value}


def _apply_overlay(c: Control) -> Control:
    """Replace req/artefacts from the overlay where it names this control."""
    spec = (load_overlay().get("controls") or {}).get(c.id)
    if not spec:
        return c
    req = " ".join(str(spec.get("requirement", "")).split())
    if req:
        c.req = req
    els = scoped_elements(c.id)
    if els:
        c.elements = tuple((str(e.get("id", "")), " ".join(str(e.get("text", "")).split())) for e in els)
        texts = [t for _i, t in c.elements]
        # assessor._artefacts() splits on ";" and newline, so joining this way puts the
        # elements through the existing checklist path with no change to assessor.py.
        joined = "; ".join(texts)
        s = overlay_settings()
        c.artefacts = joined if s["elements_replace_artefacts"] else (
            (c.artefacts + "; " + joined) if c.artefacts else joined)
    c.boundary = dict(spec.get("boundary") or {})
    return c


def load_controls(path_or_file) -> dict[str, list[Control]]:
    wb = load_workbook(path_or_file, read_only=False, data_only=True)
    ov = load_overlay()
    ov_lib = ov.get("library")
    out: dict[str, list[Control]] = {}
    for lib, (sheet, id_col, title_col, req_col, owner_col, xw) in LIBRARIES.items():
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        h = _header_map(ws)
        if id_col not in h:
            continue
        rows = []
        for r in range(4, ws.max_row + 1):
            cid = ws.cell(r, h[id_col]).value
            if not cid:
                continue
            get = lambda name: str(ws.cell(r, h[name]).value or "").strip() if name in h else ""
            maps = " | ".join(f"{c}: {get(c)}" for c in xw if get(c))
            req = get(req_col)
            if lib == "MAS":
                # Fallback only. Any MAS control the overlay names has this replaced below;
                # one it does not name still loads as a heading, which is a gap in the
                # overlay rather than a working requirement.
                req = f"Expectation: {get(title_col)}. Source: {req}"
            c = Control(f"{lib}::{str(cid).strip()}", lib, str(cid).strip(), get(title_col), req,
                        get(owner_col), maps, r, get(ARTEFACT_COL))
            if lib == ov_lib:
                c = _apply_overlay(c)
            rows.append(c)
        out[lib] = rows
    return out


def overlay_coverage(controls: dict[str, list[Control]]) -> dict:
    """Which controls in the overlay's library still carry a heading instead of a requirement.

    Surfaced rather than silently tolerated: a score computed over controls whose requirement
    is a title is not measuring the assessor, and the run needs to say so.
    """
    ov = load_overlay()
    lib = ov.get("library")
    if not lib or lib not in controls:
        return {"library": lib, "total": 0, "with_requirement": 0, "missing": []}
    named = set((ov.get("controls") or {}).keys())
    rows = controls[lib]
    missing = [c.id for c in rows if c.id not in named]
    return {"library": lib, "total": len(rows), "with_requirement": len(rows) - len(missing),
            "missing": sorted(missing)}


def write_back(src_path_or_file, dst_path: str, controls: dict[str, list[Control]], decisions: dict, ai: dict, evidence: dict) -> int:
    """Write accepted decisions into a copy of the workbook. Returns number of rows updated.

    WB-0nn: the artefact column is no longer overwritten where it holds declared artefacts.
    It was being replaced with the supplied evidence text, which destroyed the expected-artefact
    declarations in every exported workbook — the same column WB-022 made load-bearing in the
    prompt. Evidence now goes there only when the row declares no artefacts; otherwise it is
    appended to Gap / notes, which is free text by design.
    """
    wb = load_workbook(src_path_or_file)
    n = 0
    for lib, rows in controls.items():
        ws = wb[LIBRARIES[lib][0]]
        h = _header_map(ws)
        for c in rows:
            d = decisions.get(c.key)
            if not d:
                continue
            a = ai.get(c.key, {})
            ev = evidence.get(c.key, {})
            ev_text = (ev.get("file_name") or "") + (" — " if ev.get("file_name") and ev.get("text") else "") + (ev.get("text") or "")[:500]
            notes = "; ".join(a.get("gaps", [])) + (f" | Reviewer: {d['note']}" if d.get("note") else "") + f" | Recorded by {d['reviewer']}"
            declared = bool(str(ws.cell(c.row, h[ARTEFACT_COL]).value or "").strip()) if ARTEFACT_COL in h else False
            if declared:
                notes += f" | Evidence supplied: {ev_text}" if ev_text else ""
            vals = {
                "Status": {"full": "Evidenced", "partial": "Partially evidenced", "none": "Not evidenced"}[d["sufficiency"]],
                "Maturity (1-5)": d["maturity"],
                "Last reviewed": dt.date.fromisoformat(d["at"][:10]),
                "Gap / notes": notes,
            }
            if not declared:
                vals["Evidence / artifact"] = ev_text
            for col, v in vals.items():
                if col in h:
                    ws.cell(c.row, h[col]).value = v
            n += 1
    wb.save(dst_path)
    return n
