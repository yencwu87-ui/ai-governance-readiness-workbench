"""Helpers for factual, verifiable challenge pointers with line/record locators."""
from __future__ import annotations
import re

SOURCE_RE = re.compile(r"--- Source:\s*(.+?)\s*---\n?(.*?)(?=\n--- Source:|\Z)", re.S)


def parse_evidence_sources(evidence_text: str) -> dict[str, str]:
    """Return {source_label: source_text}; manual text falls under reviewer_supplied."""
    text = evidence_text or ""
    found = {m.group(1).strip(): m.group(2).strip() for m in SOURCE_RE.finditer(text)}
    if found:
        return found
    return {"reviewer_supplied": text.strip()} if text.strip() else {}


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _iter_location_candidates(body: str):
    """Yield normalised lines with human-useful 1-based line numbers and column starts."""
    for lineno, line in enumerate(body.splitlines(), 1):
        yield lineno, line


def locate_quote(quote: str, sources: dict[str, str]) -> dict | None:
    """Locate quote and return a stable source/line locator plus the original quote."""
    q = normalise(quote)
    if not q:
        return None
    for source, body in sources.items():
        # Prefer a single-line match so the pointer is directly actionable.
        for lineno, line in _iter_location_candidates(body):
            if q in normalise(line):
                return {
                    "source": source,
                    "locator": f"line:{lineno}",
                    "quote": quote.strip(),
                }
        # Fall back to a contiguous multi-line match while still providing the start line.
        lines = body.splitlines()
        for i in range(len(lines)):
            joined = normalise(lines[i])
            if q and q in joined:
                return {"source": source, "locator": f"line:{i+1}", "quote": quote.strip()}
            for j in range(i + 1, min(len(lines), i + 4)):
                joined = normalise(" ".join(lines[i:j+1]))
                if q and q in joined:
                    return {"source": source, "locator": f"lines:{i+1}-{j+1}", "quote": quote.strip()}
    return None


def build_pointer(quote: str, sources: dict[str, str], *, claim: str = "") -> dict | None:
    hit = locate_quote(quote, sources)
    if not hit:
        return None
    hit["fact"] = quote.strip()
    if claim:
        hit["what_it_supports"] = claim.strip()
    return hit


# --------------------------------------------------------------------------------------
# WB-108 — pointers for challenges that have no quote to make.
#
# `build_pointer` requires a quote copied verbatim from the evidence. That gate is right for
# what it covers and it silently excluded three kinds of challenge that make up most of real
# audit work:
#
#   absence      "your read says approvals are documented; no approver is named anywhere here"
#                The one string you can never copy out of the evidence is the missing one.
#   reasoning    "the evidence supports X, you concluded Y, X does not get you to Y"
#                The attack is on the inference. Any quote it could offer is the one already
#                cited, so it either restates the reviewer or fails validation.
#   scope        "this is one change record and your read generalises to the period"
#
# What survived the old gate was the one kind that always has a quote handy — pointing at
# something the evidence does say — which reads as a restatement of the reviewer's own reading.
#
# These two verifiers keep the discipline and drop only the assumption that the anchor must
# always be a quotation from the evidence. Both are checked in code, not taken on the model's
# word, and the absence check is the stricter of the two: "this string does not occur" is a fact
# the machine establishes itself rather than one it accepts from a language model.

def verify_absence(artefact: str, sources: dict[str, str], declared: list[str] | None = None,
                   *, min_terms: int = 2) -> dict | None:
    """Verify that a named artefact genuinely has no candidate in the evidence.

    Returns a pointer recording what was searched for and what was searched, or None when the
    claim of absence is false — i.e. when the artefact IS present, so the challenge must not
    stand.

    Two guards, because an unfalsifiable absence claim is worse than no challenge at all:

      * the artefact must be one the control declares, when a declared list is supplied. Without
        that, a challenger could assert the absence of anything it invented and always be right.
      * the match uses the same shared-stem rule as the completeness pass, so "absent here" and
        "absent in the gap scan" mean the same thing. Two different notions of absence in one
        system would let a challenge contradict the scan with neither being wrong.
    """
    name = (artefact or "").strip()
    if not name:
        return None
    if declared is not None:
        declared_norm = {normalise(d) for d in declared}
        if normalise(name) not in declared_norm and not any(
                normalise(name) in d or d in normalise(name) for d in declared_norm if d):
            return None
    try:
        from governance.completeness import match_artefact
    except Exception:
        return None
    hit = match_artefact(name, dict(sources or {}), min_terms=min_terms)
    if hit["status"] != "absent":
        return None
    return {
        "kind": "absence",
        "artefact": name,
        "searched_terms": hit["terms"],
        "documents_searched": sorted(sources or {}),
        "document_count": len(sources or {}),
        "fact": f"no document in the supplied evidence is a candidate for {name!r}",
        "verified_by": "deterministic_artefact_match",
    }


def verify_reviewer_pointer(quote: str, reviewer_read: dict | None,
                            *, claim: str = "") -> dict | None:
    """Verify a quote taken from the reviewer's own reading, not from the evidence.

    This is what makes a reasoning challenge expressible. The reviewer's reason text is already
    in the challenger's prompt, but the schema gave it no way to point at it, so an attack on
    the reviewer's inference had no admissible anchor and was discarded.

    Grounding it in the reviewer's own words rather than in the evidence keeps the rule that
    nothing is assertable without a verifiable anchor — it just recognises that when you are
    challenging a conclusion, the thing being challenged is the conclusion.
    """
    q = normalise(quote or "")
    if not q:
        return None
    read = reviewer_read or {}
    fields = {k: str(read.get(k) or "") for k in ("reason", "rationale", "note", "summary")}
    for field, body in fields.items():
        if body and q in normalise(body):
            return {
                "kind": "reviewer_claim",
                "source": f"reviewer_read.{field}",
                "quote": (quote or "").strip(),
                "fact": (quote or "").strip(),
                **({"what_it_supports": claim.strip()} if claim else {}),
                "verified_by": "substring_of_reviewer_read",
            }
    return None
