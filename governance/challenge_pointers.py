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
