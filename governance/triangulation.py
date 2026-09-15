"""WB-100: requirement triangulation and element sufficiency engine.

The engine distinguishes:
- canonical obligation: what the authoritative instrument actually requires;
- triangulation evidence: authoritative/proposed/guidance/failure material used to
  challenge completeness;
- assurance dimensions: TOD, TOE, failure/near-miss, resolution, sufficiency boundary,
  provenance and change/re-validation.

External material can raise a *candidate* or a *gap*, but cannot promote itself into a
canonical requirement. Promotion is reviewer-governed and version-aware.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
import hashlib
import json
import re
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = (ROOT / "requirements" / "triangulation" / "sources.yaml").resolve()

STATUS = {"proposed", "effective", "superseded", "withdrawn", "expired", "historical"}
NORMATIVE = {"binding", "supervisory", "guidance", "consultation", "industry", "voluntary", "internal"}
TIER_RANK = {"T0": 0, "T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5, "T6": 6}
DIMENSIONS = (
    "tod", "toe", "failure_modes", "resolution", "sufficiency_boundary",
    "test_provenance", "change_revalidation",
)


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm(s: str) -> str:
    s = s or ""
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", s.lower()).strip()


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", _norm(s)) if t not in {
        "the", "and", "for", "that", "with", "from", "are", "this", "should", "must",
        "shall", "may", "where", "such", "their", "into", "before", "after", "have", "has",
        "been", "being", "which", "will", "each", "using", "used", "than", "then", "also",
    }}


def lexical_support(element_text: str, evidence_text: str) -> float:
    a, b = _tokens(element_text), _tokens(evidence_text)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a), 4)


@dataclass(frozen=True)
class SourceState:
    source_id: str
    title: str
    issuer: str
    authority_tier: str
    normative_status: str
    lifecycle_status: str
    publication_date: str
    consultation_end: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    supersedes: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()
    source_uri: str | None = None
    content_sha256: str | None = None
    notes: str | None = None

    def is_live_on(self, as_of: date) -> bool:
        if self.lifecycle_status == "withdrawn":
            return False
        if self.effective_from and as_of < date.fromisoformat(self.effective_from):
            return False
        if self.effective_to and as_of > date.fromisoformat(self.effective_to):
            return False
        if self.lifecycle_status == "proposed" and self.effective_from is None:
            return False
        return self.lifecycle_status == "effective"


class SourceRegistry:
    def __init__(self, sources: Iterable[SourceState]):
        self.sources = {s.source_id: s for s in sources}

    @classmethod
    def from_yaml(cls, path: str | Path = DEFAULT_SOURCES) -> "SourceRegistry":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        items = []
        for x in raw.get("sources", []):
            items.append(SourceState(
                source_id=str(x["source_id"]),
                title=str(x["title"]), issuer=str(x.get("issuer", "")),
                authority_tier=str(x["authority_tier"]),
                normative_status=str(x["normative_status"]),
                lifecycle_status=str(x["lifecycle_status"]),
                publication_date=str(x["publication_date"]),
                consultation_end=x.get("consultation_end"),
                effective_from=x.get("effective_from"),
                effective_to=x.get("effective_to"),
                supersedes=tuple(x.get("supersedes", [])),
                superseded_by=tuple(x.get("superseded_by", [])),
                source_uri=x.get("source_uri"), content_sha256=x.get("content_sha256"),
                notes=x.get("notes"),
            ))
        return cls(items)

    def active(self, *, as_of: str | date) -> list[SourceState]:
        d = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
        return [s for s in self.sources.values() if s.is_live_on(d)]

    def snapshot(self) -> dict[str, Any]:
        return {"sources": [asdict(x) for x in self.sources.values()]}


def authority_score(source: SourceState) -> float:
    rank = TIER_RANK.get(source.authority_tier, 99)
    return max(0.0, 1.0 - min(rank, 6) / 6.0)


def normative_gate(source: SourceState) -> float:
    return {
        "binding": 1.0,
        "supervisory": 0.9,
        "guidance": 0.6,
        "consultation": 0.35,
        "voluntary": 0.25,
        "industry": 0.15,
        "internal": 0.05,
    }.get(source.normative_status, 0.0)


def obligation_confidence(source: SourceState, lexical: float, *, applicability: float = 1.0,
                          conflict_penalty: float = 0.0, as_of: date | None = None) -> float:
    """Evidence confidence, not a legal conclusion.

    Hard gate: proposed / consultation material can never yield canonical requiredness.
    It can only generate a candidate or challenge.
    """
    if as_of and source.effective_from and as_of < date.fromisoformat(source.effective_from):
        temporal = 0.25
    elif source.lifecycle_status == "effective":
        temporal = 1.0
    elif source.lifecycle_status == "superseded":
        temporal = 0.2
    elif source.lifecycle_status == "proposed":
        temporal = 0.35
    else:
        temporal = 0.1
    value = authority_score(source) * normative_gate(source) * temporal * max(0.0, min(1.0, lexical)) * max(0.0, min(1.0, applicability))
    value *= (1.0 - max(0.0, min(1.0, conflict_penalty)))
    return round(value, 4)


def classify_external_finding(source: SourceState, *, lexical: float, supports: bool) -> str:
    conf = obligation_confidence(source, lexical)
    if not supports:
        return "challenge"
    if source.normative_status in {"binding", "supervisory"} and source.lifecycle_status == "effective" and conf >= 0.55:
        return "corroboration"
    if source.lifecycle_status == "proposed":
        return "future_candidate"
    return "supporting_context"


def assurance_sufficiency(card: dict[str, Any]) -> dict[str, Any]:
    """Compute dimension coverage. Missing critical dimensions block 'fully sufficient'."""
    covered = {d: bool(card.get(d)) for d in DIMENSIONS}
    required = dict(covered)
    # TOD and TOE are strongly preferred, but TOE is not forced for purely design-only obligations.
    req = card.get("required_dimensions") or DIMENSIONS
    required = {d: d in req for d in DIMENSIONS}
    missing = [d for d in DIMENSIONS if required[d] and not covered[d]]
    score = round(sum(1 for d in DIMENSIONS if not required[d] or covered[d]) / len(DIMENSIONS), 4)
    status = "sufficient" if not missing else "insufficient"
    return {"status": status, "score": score, "covered": covered, "missing": missing}


def gap_vector(card: dict[str, Any]) -> dict[str, float]:
    suff = assurance_sufficiency(card)
    return {d: 1.0 if suff["covered"][d] else 0.0 for d in DIMENSIONS}


def triangulate_element(element: dict[str, Any], findings: list[dict[str, Any]], registry: SourceRegistry,
                        *, as_of: str | date) -> dict[str, Any]:
    d = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    et = str(element.get("text", ""))
    rows = []
    for f in findings:
        sid = f.get("source_id")
        if sid not in registry.sources:
            continue
        s = registry.sources[sid]
        txt = str(f.get("text", ""))
        lex = lexical_support(et, txt)
        rows.append({
            "source_id": sid,
            "locator": f.get("locator"),
            "finding_type": f.get("finding_type", "unknown"),
            "text": txt,
            "lexical_support": lex,
            "classification": classify_external_finding(s, lexical=lex, supports=bool(f.get("supports", True))),
            "obligation_confidence": obligation_confidence(s, lex, as_of=d),
            "source_status": s.lifecycle_status,
            "normative_status": s.normative_status,
            "authority_tier": s.authority_tier,
        })
    rows.sort(key=lambda x: (-x["obligation_confidence"], x["authority_tier"], x["source_id"]))
    high = [r for r in rows if r["classification"] in {"corroboration", "future_candidate"}]
    corroborated = sum(r["classification"] == "corroboration" for r in high)
    future = sum(r["classification"] == "future_candidate" for r in high)
    return {
        "element_id": element.get("id") or element.get("element_id"),
        "element_text": et,
        "source_obligation_refs": element.get("source_obligation_refs", []),
        "external_findings": rows,
        "triangulation": {
            "corroboration_count": corroborated,
            "future_candidate_count": future,
            "current_requiredness_supported": corroborated > 0,
            "future_change_signal": future > 0,
        },
    }


def control_sufficiency(elements: list[dict[str, Any]], findings: list[dict[str, Any]], registry: SourceRegistry,
                        *, as_of: str | date, control_id: str,
                        web_research: dict[str, Any] | None = None,
                        human_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    by_el: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        eid = f.get("element_id")
        if eid:
            by_el.setdefault(str(eid), []).append(f)
    results = []
    for e in elements:
        eid = str(e.get("id") or e.get("element_id"))
        results.append({
            **triangulate_element(e, by_el.get(eid, []), registry, as_of=as_of),
            "assurance": assurance_sufficiency(e),
            "gap_vector": gap_vector(e),
        })

    # Requirement-level checks: an element with no source reference is never source-complete.
    source_orphans = [r["element_id"] for r in results if not r.get("source_obligation_refs")]
    decisions = (human_decisions or {}).get("elements", {})
    pending_decisions = [e for e in (str(x.get("id") or x.get("element_id")) for x in elements)
                         if str(decisions.get(e, {}).get("status", "pending_human")) == "pending_human"]
    online = web_research or {}
    online_complete = bool((online.get("online_check") or {}).get("completed"))
    future_signals = [r["element_id"] for r in results if r["triangulation"]["future_change_signal"]]
    insufficient = [r["element_id"] for r in results if r["assurance"]["status"] != "sufficient"]
    coverage = round((len(results) - len(source_orphans)) / max(1, len(results)), 4)
    return {
        "schema_version": "wb100.triangulation.1",
        "control_id": control_id,
        "as_of": str(as_of),
        "results": results,
        "control": {
            "source_mapping_coverage": coverage,
            "source_orphans": source_orphans,
            "insufficient_elements": insufficient,
            "future_change_signals": future_signals,
            "human_decision_pending": pending_decisions,
            "online_check_completed": online_complete,
            "status": "blocked" if source_orphans or insufficient or pending_decisions or not online_complete else "reviewable",
        },
    }


def change_state(source: SourceState, today: date | None = None) -> str:
    today = today or date.today()
    if source.lifecycle_status == "proposed" and source.consultation_end:
        end = date.fromisoformat(source.consultation_end)
        if today > end:
            return "consultation_closed_pending_final"
    if source.lifecycle_status == "effective":
        if source.effective_to and today > date.fromisoformat(source.effective_to):
            return "expired"
        return "effective"
    return source.lifecycle_status


def build_change_alerts(registry: SourceRegistry, *, as_of: str | date) -> list[dict[str, Any]]:
    d = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    out = []
    for s in registry.sources.values():
        state = change_state(s, d)
        if state != s.lifecycle_status:
            out.append({"source_id": s.source_id, "stored_status": s.lifecycle_status, "observed_state": state})
    return out


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def write_json(path: str | Path, obj: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return p


def write_yaml(path: str | Path, obj: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(obj, sort_keys=False, allow_unicode=False), encoding="utf-8")
    return p
