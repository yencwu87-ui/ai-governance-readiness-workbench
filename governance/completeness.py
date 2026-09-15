"""WB-103 — the completeness pass. What the bundle is missing, before anyone forms a view.

This is the PBC round, expressed as code. It answers one question — which of the artefacts this
control declares have no candidate document in the supplied bundle — and it is careful to answer
nothing else.

Three properties it deliberately has, each because the obvious alternative is worse:

  deterministic   No model call. "Declared artefact X has no candidate document" is a matching
                  problem, not a judgement. A model-written gap list cannot be tightened when it
                  over-fires; a rule can, and did — WB-022's first matcher used two-way substring
                  and read a gap saying "Validation & test reports for the specific test cases"
                  as total absence. Tightening that rule moved the corpus probe from 1/6 to 4/6.
                  There is nothing to tighten in a paragraph of model prose.

  no verdicts     It returns `present` / `absent` / `ambiguous` per declared artefact. It never
                  returns a sufficiency, a maturity, or an element verdict. That distinction is
                  the whole reason this can run *before* the reviewer's blind read without
                  anchoring it: a list of what is missing carries no opinion about what is met,
                  so there is no proposal for the reviewer to agree with.

  floor-aware     A bundle too thin to match against returns NOT_TESTABLE rather than reporting
                  every artefact as absent. Zero documents scanned is not evidence of absence,
                  and the policy evidence floor already makes this distinction everywhere else.

What it is not: a scoring pass, a retrieval pass, or a reason to skip the blind read.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

SCHEMA = "wb103.completeness.1"

#: Below this many candidate documents, absence is not a finding — the bundle is the problem.
MIN_DOCUMENTS = 1

#: Words that make a phrase a category label rather than a nameable artefact. A declared
#: artefact of "Change records" is matchable; "as applicable" is not, and reporting it absent
#: would be noise a reviewer has to clear every run.
_UNMATCHABLE = {"etc", "applicable", "relevant", "appropriate", "necessary", "any", "other",
                "including", "e.g", "eg", "ie", "such", "where"}

_STOP = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with", "by", "from",
         "its", "their", "this", "that", "these", "those", "is", "are", "be", "as", "at"}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())


def _terms(text: str) -> list[str]:
    return [t for t in _norm(text).split() if t not in _STOP and len(t) > 2]


def _singular(term: str) -> str:
    """Crude depluralisation. 'records' and 'record' must match; nothing subtler is needed."""
    if term.endswith("ies") and len(term) > 4:
        return term[:-3] + "y"
    if term.endswith("sses") or term.endswith("ses"):
        return term[:-2]
    if term.endswith("s") and not term.endswith("ss"):
        return term[:-1]
    return term


def _stems(text: str) -> set[str]:
    return {_singular(t) for t in _terms(text)}


def declared_artefacts(control) -> list[str]:
    """Expected artefacts from the control row, split the same way the assessor splits them.

    Reuses assessor._artefacts rather than reimplementing it: two splitters that drift apart
    would mean the completeness pass and the prompt disagree about what was declared.
    """
    try:
        from assessor import _artefacts
        return _artefacts(control)
    except Exception:
        raw = (getattr(control, "artefacts", "") or "").replace("\n", ";")
        return [a.strip() for a in raw.split(";") if a.strip()]


def is_matchable(artefact: str) -> tuple[bool, str]:
    """Whether this declared artefact names something a document could be.

    A category label cannot be found or not found, so it is reported as `unmatchable` rather
    than silently counted present or absent. WB-022 found the artefact column often holds a
    category rather than a requirement; that is a fact about the workbook, and the honest
    handling is to say so per row rather than to guess.
    """
    stems = _stems(artefact)
    if not stems:
        return False, "no_matchable_terms"
    if stems <= _UNMATCHABLE:
        return False, "category_label_only"
    if len(stems) == 1 and next(iter(stems)) in _UNMATCHABLE:
        return False, "category_label_only"
    return True, ""


def _documents(chunks: Iterable[Any]) -> dict[str, str]:
    """Collapse scanner chunks into {path: concatenated text}.

    Accepts scanner.Chunk objects or plain dicts/tuples so this can be called from the app, from
    a test, or from a headless run without importing Streamlit anywhere.
    """
    docs: dict[str, list[str]] = {}
    for c in chunks or []:
        if isinstance(c, dict):
            path, text = str(c.get("path") or c.get("source") or ""), str(c.get("text") or "")
        elif isinstance(c, (tuple, list)) and len(c) >= 2:
            path, text = str(c[0]), str(c[1])
        else:
            path, text = str(getattr(c, "path", "")), str(getattr(c, "text", ""))
        if not path:
            continue
        docs.setdefault(path, []).append(text)
    return {p: "\n".join(v) for p, v in docs.items()}


def _filename(path: str) -> str:
    return re.split(r"[\\/]", path)[-1]


def match_artefact(artefact: str, docs: dict[str, str], *, min_terms: int = 2) -> dict[str, Any]:
    """Locate candidate documents for one declared artefact.

    The rule, and why it is this rule rather than substring containment:

      A document is a candidate when it shares at least `min_terms` distinct content stems with
      the artefact name, or — for a one-word artefact — that single stem. Substring matching in
      either direction is what over-fired in WB-022: "reports" appears in almost any governance
      document, and "Change records" is a substring of a sentence denying that change records
      exist.

      Filename evidence is scored but reported separately from body evidence. A file called
      `change_records_Q1.xlsx` is a strong candidate; a body that merely uses the phrase is
      weaker, because a policy describing what change records should contain is not a change
      record. The reviewer is told which kind of hit it was rather than being handed a verdict.
    """
    stems = _stems(artefact)
    need = min(min_terms, len(stems)) if stems else 1
    by_name, by_body = [], []
    for path, text in docs.items():
        name_hits = stems & _stems(_filename(path))
        body_hits = stems & _stems(text)
        if len(name_hits) >= need:
            by_name.append({"path": path, "matched_terms": sorted(name_hits), "where": "filename"})
        elif len(body_hits) >= need:
            by_body.append({"path": path, "matched_terms": sorted(body_hits), "where": "body"})
    candidates = by_name + by_body
    if by_name:
        status = "present"
    elif by_body:
        # Named nowhere, mentioned somewhere. That is not the artefact and it is not nothing.
        status = "ambiguous"
    else:
        status = "absent"
    return {
        "artefact": artefact,
        "status": status,
        "required_terms": need,
        "terms": sorted(stems),
        "candidates": candidates[:8],
        "candidate_count": len(candidates),
        "filename_hits": len(by_name),
        "body_only_hits": len(by_body),
    }


def scan(control, chunks: Iterable[Any], *, min_documents: int = MIN_DOCUMENTS) -> dict[str, Any]:
    """Run the completeness pass for one control over one evidence bundle.

    Returns a record with an explicit `testable` flag. When the bundle is below the document
    floor the per-artefact rows are still returned for transparency, but every status is
    NOT_TESTABLE and `gaps` is empty — because "we found nothing in an empty folder" is not a
    finding about the organisation, it is a finding about the bundle.
    """
    docs = _documents(chunks)
    declared = declared_artefacts(control)
    rows: list[dict[str, Any]] = []
    unmatchable: list[dict[str, str]] = []

    testable = len(docs) >= min_documents
    for artefact in declared:
        ok, why = is_matchable(artefact)
        if not ok:
            unmatchable.append({"artefact": artefact, "reason": why})
            rows.append({"artefact": artefact, "status": "unmatchable", "reason": why,
                         "candidates": [], "candidate_count": 0})
            continue
        if not testable:
            rows.append({"artefact": artefact, "status": "NOT_TESTABLE",
                         "reason": "bundle below the document floor", "candidates": [],
                         "candidate_count": 0})
            continue
        rows.append(match_artefact(artefact, docs))

    gaps = [r["artefact"] for r in rows if r["status"] == "absent"]
    ambiguous = [r["artefact"] for r in rows if r["status"] == "ambiguous"]
    return {
        "schema": SCHEMA,
        "control_id": getattr(control, "id", ""),
        "framework": getattr(control, "lib", ""),
        "declared_count": len(declared),
        "documents_scanned": len(docs),
        "document_floor": min_documents,
        "testable": testable,
        "not_testable_reason": None if testable else (
            f"only {len(docs)} document(s) in the bundle; below the floor of {min_documents}. "
            f"Absence cannot be distinguished from an empty bundle."),
        "artefacts": rows,
        "gaps": gaps,
        "ambiguous": ambiguous,
        "unmatchable": unmatchable,
        "complete": testable and not gaps,
        "bundle_hash": bundle_hash(docs),
    }


def bundle_hash(docs: dict[str, str]) -> str:
    """Identity of the evidence bundle, so a top-up is detectable rather than asserted.

    Hashes paths and content together: adding a file, replacing one, or editing one all change
    it. `core.cycle` uses this to refuse an assessment whose bundle moved after it was bound.
    """
    h = hashlib.sha256()
    for path in sorted(docs):
        h.update(path.encode("utf-8"))
        h.update(hashlib.sha256(docs[path].encode("utf-8")).digest())
    return h.hexdigest()[:16]


def hash_chunks(chunks: Iterable[Any]) -> str:
    return bundle_hash(_documents(chunks))


def chunks_from_evidence(evidence: dict[str, Any]) -> list[dict[str, str]]:
    """Turn the app's evidence record into documents the pass can match against.

    `pipeline.build_evidence` writes one blob with `--- Source: <label> ---` separators, and
    `challenge_pointers.parse_evidence_sources` already knows how to split it. Reusing that
    splitter rather than writing a second one keeps the completeness pass matching over exactly
    the documents the challenger will later be asked to quote from.

    Manually pasted evidence has no separators and arrives as one `reviewer_supplied` document,
    which is correct: one pasted note is one document, and the document floor should see it that
    way rather than counting paragraphs.
    """
    ev = evidence or {}
    try:
        from governance.challenge_pointers import parse_evidence_sources
        sources = parse_evidence_sources(str(ev.get("text") or ""))
    except Exception:
        sources = {"reviewer_supplied": str(ev.get("text") or "")}
    docs = [{"path": label, "text": body} for label, body in sources.items() if body.strip()]
    # An attached file contributes its name even when its text was not inlined, because a
    # filename is the strongest artefact signal the matcher has.
    name = str(ev.get("file_name") or "")
    if name and not any(name in d["path"] for d in docs):
        docs.append({"path": name, "text": str(ev.get("file_text") or "")})
    return docs


def headline(result: dict[str, Any]) -> str:
    """One line for the UI. Never says whether the control is met."""
    if not result.get("testable"):
        return (f"Completeness NOT_TESTABLE — {result['documents_scanned']} document(s) scanned. "
                f"Add evidence before assessing.")
    n = len(result.get("gaps") or [])
    a = len(result.get("ambiguous") or [])
    if not result.get("declared_count"):
        return "This control declares no expected artefacts, so completeness cannot be checked."
    if not n and not a:
        return (f"All {result['declared_count']} declared artefact(s) have a candidate document. "
                f"This says nothing yet about whether the requirement is met.")
    parts = []
    if n:
        parts.append(f"{n} declared artefact(s) have no candidate document")
    if a:
        parts.append(f"{a} named nowhere but mentioned in a document")
    return "; ".join(parts) + "."
