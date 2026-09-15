"""Deterministic evidence-to-element matching for reviewer assistance.

This module never creates a governance verdict. It finds passages in the supplied evidence that
lexically match governed requirement elements and returns *review suggestions*. A reviewer may
apply strong suggestions to the UI draft, but the result still requires explicit human review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from governance.challenge_pointers import parse_evidence_sources

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "must", "shall", "should",
    "organisation", "organization", "maintain", "define", "defined", "ensure", "including",
    "relevant", "applicable", "required", "current", "within", "where", "there", "their",
    "has", "have", "are", "is", "of", "to", "a", "an", "in", "on", "or", "by", "be",
}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9_.-]{2,}", (text or "").lower()) if t not in _STOP]


def _ngrams(tokens: list[str], n: int = 2) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i+n]) for i in range(max(0, len(tokens) - n + 1))}


@dataclass(frozen=True)
class Match:
    element_id: str
    element_text: str
    source: str
    locator: str
    excerpt: str
    score: float
    confidence: str
    rationale: str


def _score(element: str, passage: str) -> float:
    et = _tokens(element)
    pt = _tokens(passage)
    if not et or not pt:
        return 0.0
    es, ps = set(et), set(pt)
    overlap = len(es & ps)
    recall = overlap / len(es)
    precision = overlap / len(ps)
    phrase = len(_ngrams(et) & _ngrams(pt))
    # Recall matters most: an evidence sentence that contains most distinctive element
    # terms is more useful than a generic passage with a high word count.
    score = 0.62 * recall + 0.23 * min(precision * 3.0, 1.0) + 0.15 * min(phrase / 2.0, 1.0)
    return round(min(score, 1.0), 4)


def suggest_element_matches(element_list: Iterable[dict], evidence_text: str, *, min_score: float = 0.42) -> list[dict]:
    """Return one best evidence passage per governed element.

    Only positive matching is suggested. We deliberately never infer `not_evidenced` from a
    missing match, because absence of retrieved text is not proof of absence in the organisation.
    """
    sources = parse_evidence_sources(evidence_text or "")
    suggestions: list[Match] = []
    for element in element_list:
        eid = str(element.get("id") or "").strip()
        etext = " ".join(str(element.get("text") or "").split())
        if not eid or not etext:
            continue
        best: Match | None = None
        for source, body in sources.items():
            lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
            # Evaluate line windows up to three lines; this catches evidence tables and
            # split sentences without making the excerpt too large for a reviewer.
            for i in range(len(lines)):
                for j in range(i + 1, min(i + 3, len(lines)) + 1):
                    excerpt = " ".join(lines[i:j])
                    score = _score(etext, excerpt)
                    if best is None or score > best.score:
                        confidence = "high" if score >= 0.72 else "medium" if score >= 0.55 else "low"
                        best = Match(eid, etext, source, f"lines:{i+1}-{j}", excerpt[:900], score,
                                     confidence, "Lexical evidence match; reviewer confirmation required.")
        if best and best.score >= min_score:
            suggestions.append(best)
    suggestions.sort(key=lambda x: (-x.score, x.element_id))
    return [
        {
            "element_id": s.element_id,
            "element_text": s.element_text,
            "source": s.source,
            "locator": s.locator,
            "excerpt": s.excerpt,
            "match_score": s.score,
            "confidence": s.confidence,
            "rationale": s.rationale,
            "suggested_status": "met",
        }
        for s in suggestions
    ]
