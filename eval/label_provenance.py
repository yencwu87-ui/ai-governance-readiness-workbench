"""GE-110b.1 — provenance for each case × element judgement.

The defect, and why it is in the schema rather than the renderer
---------------------------------------------------------------
`elements.yaml` is element-major::

    - id: e4
      text: Pre-deployment review is performed by parties not involved in development…
      a: Y
      b: N
      c: N
      decided_by: claude-unconfirmed
      where: "_a §1 and §5 say Independent Model Validation reviewed the candidate…"

One `where`, one `decided_by`, three verdicts. So case `a` was judged Y and case `b` was judged
N on the same element, and the record carries a single sentence for both. `LABELS.md` then
repeats that sentence into every case row, which is what `corpus_adequacy` flags.

No renderer change fixes this. The justification for `a: Y` does not exist anywhere to render.

The atom
--------
The unit of record is a judgement, not an element::

    judgements:
      - case: a
        element: e4
        verdict: Y
        justification: "§1 and §5 name Independent Model Validation under Group Risk…"
        source_refs: ["M3.6_a.md#§1", "M3.6_a.md#§5"]
        labelled_by: "wu yenching"
        labelled_at: "2026-09-14"

The element columns stay as the compact view and remain what `derive()` reads, so nothing
downstream breaks. `judgements` is authoritative for provenance where it exists.

What migration must not do
--------------------------
Copying the shared element note into each case would produce a file that looks like it has
per-case provenance and does not. `migrate` marks anything carried over as
``provenance: inherited_from_element`` — visibly not a per-case judgement — so
`corpus_adequacy` keeps flagging it until a person actually re-argues it. A repair that hides
the defect it repairs is worse than the defect.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "ge110b.label-provenance.1"

#: A judgement whose justification was carried over from the element row rather than written
#: for this case. Present so the gap stays visible after migration.
INHERITED = "inherited_from_element"
PER_CASE = "per_case"

#: The only provenance that may be used as calibration data.
#:
#: GE-110b.1 invariant: `inherited_from_element` ≠ case-specific adjudication. An inherited note
#: is fine for migration and for rendering — it keeps the legacy record readable — but it is a
#: sentence about an element, and calibrating an evaluator against it would be calibrating
#: against a claim nobody made about that case.
#:
#: The bar is deliberately higher than "someone typed something in the right cell". A judgement
#: is admissible only when it carries all four: a justification written for this case, at least
#: one source reference into the document, a named human, and a date. `claude-unconfirmed` and
#: `unrecorded` are explicitly not names — the corpus has carried `claude-unconfirmed` since the
#: beginning, and a bar that accepted it would let the instrument calibrate itself.
ADJUDICATED = "adjudicated_case_specific"

#: Labeller strings that identify nobody at all.
NON_ATTRIBUTIONS = {"", "unrecorded", "claude-unconfirmed", "pending-human-relabel-2026-09-14",
                    "unknown", "tbd", "n/a"}

#: Who adjudicated. GE-110b.2: the previous check tried to infer personhood from the labeller
#: string and said so in its own docstring — "does not name a person". It let `GPT-5.6 Luna`
#: through, because a model name looks exactly like a person's name and no string test can tell
#: them apart. Inferring an attribute the record could simply state is the same error as
#: inferring a workbook's producer from its filename, which GE-110 already refused to do.
#:
#: So the record states it. `adjudicator_kind` is required, and its absence is a rejection rather
#: than a default — defaulting to `human` would launder every legacy row, and defaulting to `ai`
#: would misattribute future human work.
ADJUDICATOR_KINDS = {"human", "ai"}

#: An AI adjudicating evidence it did not author, against a frozen artefact, is a real
#: improvement on one party holding both halves. It is not human ground truth. Both are
#: admissible; the grade travels with the corpus so a later reader is never left assuming.
GRADE_HUMAN = "human_adjudicated"
GRADE_AI = "ai_adjudicated_candidate"
GRADE_MIXED = "mixed_adjudication"

_CASE_KEYS = ("a", "b", "c", "d", "e", "f")


def _case_keys(element: dict) -> list[str]:
    return [k for k in _CASE_KEYS if k in element]


def judgement_key(case: str, element: str) -> str:
    return f"{case}:{element}"


def index(judgements: Iterable[dict]) -> dict[str, dict]:
    return {judgement_key(str(j.get("case")), str(j.get("element"))): dict(j)
            for j in (judgements or []) if j.get("case") and j.get("element")}


def migrate(doc: dict, *, today: str | None = None) -> dict:
    """Add a `judgements` block derived from the element columns.

    Verdicts are copied because they are real. Justifications are copied but marked
    `inherited_from_element`, because a sentence written about an element is not a reason this
    case was judged that way. `labelled_by` carries the element's `decided_by` unchanged,
    including `claude-unconfirmed` — migration does not upgrade anyone's authority.
    """
    today = today or dt.date.today().isoformat()
    existing = index(doc.get("judgements") or [])
    out = list(doc.get("judgements") or [])
    for e in doc.get("elements") or []:
        eid = str(e.get("id") or "")
        if not eid:
            continue
        note = str(e.get("where") or e.get("why") or e.get("note") or "").strip()
        who = str(e.get("decided_by") or "").strip() or "unrecorded"
        for k in _case_keys(e):
            if judgement_key(k, eid) in existing:
                continue
            out.append({
                "case": k,
                "element": eid,
                "verdict": str(e.get(k, "")).strip(),
                "justification": note,
                "provenance": INHERITED if note else "absent",
                "source_refs": [],
                "labelled_by": who,
                "labelled_at": today,
            })
    merged = dict(doc)
    merged["judgements"] = out
    merged.setdefault("provenance_schema", SCHEMA)
    return merged


def validate(doc: dict) -> list[dict]:
    """Findings about the provenance record. Reports; never blocks.

    A corpus with inherited provenance is still usable for characterisation — it just cannot
    support a claim that each judgement was individually argued.
    """
    out: list[dict] = []
    elements = {str(e.get("id")): e for e in (doc.get("elements") or [])}
    js = doc.get("judgements") or []
    if not js:
        return [{"code": "NO_JUDGEMENT_RECORDS", "severity": "warning",
                 "message": "no per-judgement provenance; justification is per-element only, so "
                            "a stored verdict cannot be re-argued from its own record"}]

    seen: set[str] = set()
    for j in js:
        key = judgement_key(str(j.get("case")), str(j.get("element")))
        if key in seen:
            out.append({"code": "DUPLICATE_JUDGEMENT", "severity": "error",
                        "message": f"{key} recorded more than once", "key": key})
        seen.add(key)
        if str(j.get("element")) not in elements:
            out.append({"code": "JUDGEMENT_ON_UNDECLARED_ELEMENT", "severity": "error",
                        "message": f"{key} judges an element the contract does not declare",
                        "key": key})
        if not str(j.get("labelled_by") or "").strip():
            out.append({"code": "UNATTRIBUTED_JUDGEMENT", "severity": "error",
                        "message": f"{key} names nobody — a label with no author cannot be "
                                   f"challenged", "key": key})
        if j.get("provenance") == INHERITED:
            out.append({"code": "INHERITED_JUSTIFICATION", "severity": "warning",
                        "message": f"{key} carries the element's note rather than a reason "
                                   f"written for this case", "key": key})
        v = str(j.get("verdict") or "").strip()
        declared = elements.get(str(j.get("element")), {})
        col = str(declared.get(str(j.get("case")), "")).strip()
        if col and v and col != v:
            out.append({"code": "JUDGEMENT_COLUMN_MISMATCH", "severity": "error",
                        "message": f"{key} records {v!r} but the element column says {col!r} — "
                                   f"two answers to one question", "key": key})

    for eid, e in elements.items():
        for k in _case_keys(e):
            if judgement_key(k, eid) not in seen:
                out.append({"code": "MISSING_JUDGEMENT_RECORD", "severity": "warning",
                            "message": f"{judgement_key(k, eid)} has a verdict in the element "
                                       f"columns but no judgement record"})
    return out


def admissibility(judgement: dict) -> tuple[bool, str]:
    """(admissible_for_calibration, reason). The invariant, as one function.

    Every other consumer asks this rather than testing `provenance` itself, so the bar lives in
    one place and cannot drift between the harness, the renderer and the validator.
    """
    prov = str(judgement.get("provenance") or "")
    if prov == INHERITED:
        return False, "inherited_from_element is not a case-specific adjudication"
    if prov != ADJUDICATED:
        return False, f"provenance is {prov or 'absent'!r}, not {ADJUDICATED}"
    if not str(judgement.get("justification") or "").strip():
        return False, "no justification"
    if not [x for x in (judgement.get("source_refs") or []) if str(x).strip()]:
        return False, "no source reference into the document"
    who = str(judgement.get("labelled_by") or "").strip()
    if who.lower() in NON_ATTRIBUTIONS:
        return False, f"labelled_by {who or 'empty'!r} identifies nobody"
    kind = str(judgement.get("adjudicator_kind") or "").strip().lower()
    if kind not in ADJUDICATOR_KINDS:
        return False, (f"adjudicator_kind is {kind or 'absent'!r}; must be one of "
                       f"{sorted(ADJUDICATOR_KINDS)} — it is stated, never inferred from the name")
    if not str(judgement.get("labelled_at") or "").strip():
        return False, "no date"
    return True, ""


def calibration_admissible(doc: dict) -> dict[str, Any]:
    """Which judgements may be used as calibration data, and why the rest may not.

    Scoped by `calibration_cases` when the document names one. A corpus accumulates generations —
    the M3.6 file holds the superseded a/b/c judgements alongside the adjudicated d/e/f/g set —
    and the older rows stay in the file because deleting a judgement to pass a gate is the
    behaviour this whole layer exists to prevent. Naming the calibration set is how a superseded
    generation is retired without being erased; without it the gate would either fail forever or
    invite someone to delete history.
    """
    cases = doc.get("calibration_cases")
    js = [j for j in (doc.get("judgements") or [])
          if not cases or str(j.get("case")) in set(cases)]
    ok, rejected = [], []
    for j in js:
        good, why = admissibility(j)
        (ok if good else rejected).append(
            {"case": j.get("case"), "element": j.get("element"),
             **({} if good else {"reason": why})})
    kinds = {str(j.get("adjudicator_kind") or "").strip().lower()
             for j in js if str(j.get("adjudicator_kind") or "").strip()}
    grade = (GRADE_HUMAN if kinds == {"human"}
             else GRADE_AI if kinds == {"ai"}
             else GRADE_MIXED if kinds else None)
    return {"schema": SCHEMA, "n_judgements": len(js), "admissible": len(ok),
            "inadmissible": len(rejected), "rejected": rejected[:50],
            "adjudicator_kinds": sorted(kinds), "grade": grade,
            "human_adjudicated": grade == GRADE_HUMAN,
            "ready": bool(js) and not rejected}


class NotCalibrationData(RuntimeError):
    """Raised instead of measuring. Carries the report."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__(
            f"corpus is not calibration data — {report['inadmissible']} of "
            f"{report['n_judgements']} judgement(s) are not case-specific adjudications")


def assert_calibration_data(doc: dict) -> dict[str, Any]:
    """Gate for the measurement harness. Raises rather than returning a status nobody reads.

    Same shape as `contract_integrity.assert_executable`, and for the same reason: a migrated
    corpus is structurally complete and looks ready. Without this, the first measurement run
    would quietly calibrate against 42 inherited notes and report a number.
    """
    report = calibration_admissible(doc)
    if not report["ready"]:
        raise NotCalibrationData(report)
    return report


def summary(doc: dict) -> dict[str, Any]:
    js = doc.get("judgements") or []
    per_case = sum(1 for j in js if j.get("provenance") in (PER_CASE, ADJUDICATED))
    adjudicated = sum(1 for j in js if j.get("provenance") == ADJUDICATED)
    inherited = sum(1 for j in js if j.get("provenance") == INHERITED)
    adm = calibration_admissible(doc)
    return {
        "schema": SCHEMA,
        "n_judgements": len(js),
        "per_case": per_case,
        "adjudicated": adjudicated,
        "inherited": inherited,
        "absent": len(js) - per_case - inherited,
        "fully_argued": bool(js) and per_case == len(js),
        # Structural completeness and calibration readiness are different facts and are
        # reported separately. A migrated corpus is the first without being the second.
        "calibration_ready": adm["ready"],
        "calibration_admissible": adm["admissible"],
        "grade": adm["grade"],
        "adjudicator_kinds": adm["adjudicator_kinds"],
        "labellers": sorted({str(j.get("labelled_by") or "unrecorded") for j in js}),
    }


def justification_for(doc: dict, case: str, element: str) -> tuple[str, str]:
    """(text, provenance). Falls back to the element note, labelled as inherited."""
    j = index(doc.get("judgements") or []).get(judgement_key(case, element))
    if j and str(j.get("justification") or "").strip():
        return str(j["justification"]).strip(), str(j.get("provenance") or PER_CASE)
    for e in doc.get("elements") or []:
        if str(e.get("id")) == element:
            note = str(e.get("where") or e.get("why") or e.get("note") or "").strip()
            return note, INHERITED if note else "absent"
    return "", "absent"


def migrate_file(path: str | Path, *, today: str | None = None) -> dict[str, Any]:
    import yaml
    p = Path(path)
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    before = len(doc.get("judgements") or [])
    merged = migrate(doc, today=today)
    header = ""
    raw = p.read_text(encoding="utf-8")
    if raw.startswith("#"):
        lines = raw.splitlines(keepends=True)
        header = "".join(l for l in lines if l.startswith("#") or not l.strip())[:  # noqa: E203
                        sum(len(l) for l in lines if l.startswith("#") or not l.strip())]
        header = "".join(l for l in lines[:next((i for i, l in enumerate(lines)
                                                 if l.strip() and not l.startswith("#")), 0)])
    p.write_text(header + yaml.safe_dump(merged, sort_keys=False, allow_unicode=True,
                                         width=100), encoding="utf-8")
    return {"path": str(p), "added": len(merged["judgements"]) - before,
            "summary": summary(merged)}
