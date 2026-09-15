"""Row builders for the EVL-* controls (WB-029).

Four sources, deliberately separate — a control counts rows, so two row kinds in
one source means a bare `max:` counts the wrong population:

    overlay_candidates   one row per requirement-overlay file found on disk (EVL-03)
    overlay_coverage     one row per control in the overlay's library    (EVL-04)
    corpus_cases         one row per corpus document                     (EVL-01, EVL-02)
    corpus_elements      one row per document x element                  (EVL-06)

All pure: they take what they need as arguments and return plain dicts, so they
can be tested without a workbook, a model or a fixed filesystem layout. Harness
registration is the only part that touches caa/ and is not in this file.

Labels are DERIVED from the element matrix, never read from LABELS.md:
all applicable Y = full, some = partial, none = none. "n/a" is excluded from the
label rather than counted against it. A "?" is undecided — it makes the derived
label unsound, so the case is flagged rather than silently scored.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

import playbook

LEVELS = ("none", "partial", "full")
LANE_B = "b"


# ---------------------------------------------------------------------------
# overlay sources (EVL-03, EVL-04)
# ---------------------------------------------------------------------------

def overlay_candidate_rows(candidates: list[Path] | None = None,
                           loaded: Path | None = None) -> list[dict]:
    """One row per overlay file present, in precedence order."""
    if candidates is None:
        candidates = playbook.overlay_candidates_present()
    if loaded is None and candidates:
        loaded = playbook.overlay_path()
    return [{"path": str(p), "is_loaded": loaded is not None and Path(p) == Path(loaded)}
            for p in candidates]


def overlay_coverage_rows(controls: dict | None = None) -> list[dict]:
    """One row per control in the overlay's library."""
    if controls is None:
        raise ValueError(
            "overlay_coverage_rows needs loaded controls; the caller supplies them so "
            "this stays testable without opening the workbook")
    cov = playbook.overlay_coverage(controls)
    lib = cov.get("library")
    if not lib or lib not in controls:
        return []
    missing = set(cov.get("missing") or [])
    return [{"library": lib, "control_id": c.id, "has_requirement": c.id not in missing}
            for c in controls[lib]]


# ---------------------------------------------------------------------------
# corpus sources (EVL-01, EVL-02, EVL-06)
# ---------------------------------------------------------------------------

def requirement_sha(control_id: str, overlay: dict | None = None) -> str | None:
    """The sha of a control's entry in the requirement overlay.

    Canonicalised through yaml.safe_dump with sorted keys, so reformatting the
    file does not read as a requirement change while any edit to the requirement
    text or its elements does.
    """
    if overlay is None:
        overlay = playbook.load_overlay()
    spec = (overlay.get("controls") or {}).get(control_id)
    if not spec:
        return None
    canon = yaml.safe_dump(spec, sort_keys=True, default_flow_style=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def derive_label(doc_key: str, elements: list[dict]) -> dict:
    """Derive one document's label from the element matrix.

    Returns the label plus the counts a reviewer needs to check it, and the two
    conditions that make a label unsound: an undecided element, and a document
    where nothing is in scope.
    """
    applicable, yes, undecided = 0, 0, 0
    for e in elements:
        if str(e.get("lane", "")).lower() == LANE_B:
            continue
        v = str(e.get(doc_key, "?")).strip().lower()
        if v in ("n/a", "na"):
            continue
        applicable += 1
        if v == "y":
            yes += 1
        elif v == "?":
            undecided += 1
    if applicable == 0:
        label = None
    elif yes == applicable:
        label = "full"
    elif yes == 0:
        label = "none"
    else:
        label = "partial"
    return {"level": label, "elements_applicable": applicable, "elements_yes": yes,
            "elements_undecided": undecided, "label_unsound": undecided > 0 or applicable == 0}


def _matrices(corpus_root: str | Path) -> list[tuple[Path, dict]]:
    out = []
    for p in sorted(Path(corpus_root).glob("*/elements.yaml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if data.get("control") and data.get("elements"):
            out.append((p, data))
    return out


def _doc_key(doc: str) -> str:
    """Column key for a document id: M3.12_a -> a."""
    return doc.split("_")[-1] if "_" in doc else doc


def corpus_case_rows(corpus_root: str | Path = "eval/corpus",
                     overlay: dict | None = None) -> list[dict]:
    """One row per corpus document.

    incomplete_set is set on every document of a control whose documents do not
    between them cover none, partial and full — the control is the unit that is
    incomplete, so flagging every row means EVL-01 names the control whichever
    row it reports.

    requirement_binding_broken covers both an absent binding and a stale one. An
    unbound case cannot be known to have been scored against the requirement it
    was authored against, which is the same exposure as a changed one.
    """
    if overlay is None:
        overlay = playbook.load_overlay()
    rows: list[dict] = []
    for path, m in _matrices(corpus_root):
        control_id = str(m["control"])
        docs = list(m.get("documents") or [])
        els = list(m.get("elements") or [])
        live = requirement_sha(control_id, overlay)
        recorded = m.get("requirement_sha")
        derived = [{"case_id": d, **derive_label(_doc_key(d), els)} for d in docs]
        covered = {d["level"] for d in derived if d["level"]}
        incomplete = not set(LEVELS).issubset(covered)
        for d in derived:
            rows.append({
                "control_id": control_id,
                "case_id": d["case_id"],
                "level": d["level"],
                "source_file": str(path),
                "incomplete_set": incomplete,
                "levels_covered": sorted(covered),
                "elements_applicable": d["elements_applicable"],
                "elements_yes": d["elements_yes"],
                "elements_undecided": d["elements_undecided"],
                "label_unsound": d["label_unsound"],
                "requirement_sha": recorded,
                "requirement_sha_live": live,
                "requirement_sha_mismatch": bool(recorded) and recorded != live,
                "requirement_binding_broken": (not recorded) or recorded != live,
            })
    return rows


def corpus_element_rows(corpus_root: str | Path = "eval/corpus") -> list[dict]:
    """One row per document x element, for provenance.

    decided_by is absent from some matrices. Absent is recorded as `unattributed`
    rather than defaulted to a person — an unattributed decision is exactly what
    the control exists to surface.
    """
    rows: list[dict] = []
    for path, m in _matrices(corpus_root):
        control_id = str(m["control"])
        docs = list(m.get("documents") or [])
        for e in m.get("elements") or []:
            lane_b = str(e.get("lane", "")).lower() == LANE_B
            decided_by = str(e.get("decided_by") or "unattributed")
            for doc in docs:
                v = str(e.get(_doc_key(doc), "?")).strip().lower()
                rows.append({
                    "control_id": control_id,
                    "case_id": doc,
                    "element_id": str(e.get("id", "")),
                    "value": v,
                    "lane_b": lane_b,
                    "decided_by": decided_by,
                    "undecided": v == "?",
                    "has_citation": bool(str(e.get("where") or "").strip()),
                    "source_file": str(path),
                })
    return rows


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def summary(controls: dict | None = None, corpus_root: str | Path = "eval/corpus") -> dict:
    cands = overlay_candidate_rows()
    cov = overlay_coverage_rows(controls) if controls is not None else []
    cases = corpus_case_rows(corpus_root)
    els = corpus_element_rows(corpus_root)
    dist: dict[str, int] = {}
    for r in cases:
        dist[str(r["level"])] = dist.get(str(r["level"]), 0) + 1
    return {
        "overlay_candidates_found": len(cands),
        "overlay_path": next((r["path"] for r in cands if r["is_loaded"]), None),
        "overlay_ignored": [r["path"] for r in cands if not r["is_loaded"]],
        "controls_examined": len(cov),
        "controls_without_requirement": sorted(
            r["control_id"] for r in cov if not r["has_requirement"]),
        "cases_examined": len(cases),
        "controls_incomplete": sorted({r["control_id"] for r in cases if r["incomplete_set"]}),
        "distribution_by_label": dist,
        "cases_unbound": sorted(r["case_id"] for r in cases if not r["requirement_sha"]),
        "cases_stale": sorted(r["case_id"] for r in cases if r["requirement_sha_mismatch"]),
        "cases_unsound": sorted(r["case_id"] for r in cases if r["label_unsound"]),
        "elements_examined": len(els),
        "decided_by_distribution": {
            k: sum(1 for r in els if r["decided_by"] == k)
            for k in sorted({r["decided_by"] for r in els})},
    }
