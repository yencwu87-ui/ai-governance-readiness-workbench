"""Governance knowledge brain: versioned, authority-aware retrieval for assessor/challenger context.

The brain is advisory context only. It cannot create, upgrade, or sign a governance decision.
Each memory is explicit, versioned, and assigned an authority tier. Lower-authority memories may
provide patterns/examples but must never override higher-authority requirements or decisions.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import re
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "governance" / "knowledge" / "brain.yaml"
DEFAULT_TESTING_PATH = ROOT / "governance" / "knowledge" / "control_testing.yaml"
TIER_RANK = {"authoritative": 1, "approved_interpretation": 2, "organisational_precedent": 3,
             "example": 4, "heuristic": 5}

@dataclass(frozen=True)
class Memory:
    memory_id: str
    type: str
    authority_tier: str
    controls: tuple[str, ...]
    topic: str
    statement: str
    evidence_pattern: dict
    prior_disposition: str | None = None
    challenge_prompt: str | None = None
    tags: tuple[str, ...] = ()

    @property
    def rank(self) -> int:
        return TIER_RANK.get(self.authority_tier, 99)


def load_brain(path: Path | str = DEFAULT_PATH) -> dict:
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("memories"), list):
        raise ValueError("governance knowledge brain must contain a memories list")
    return data


def _memory(raw: dict) -> Memory:
    return Memory(
        memory_id=str(raw["memory_id"]), type=str(raw.get("type", "example")),
        authority_tier=str(raw.get("authority_tier", "example")),
        controls=tuple(str(x) for x in raw.get("controls", [])),
        topic=str(raw.get("topic", "")), statement=str(raw.get("statement", "")),
        evidence_pattern=raw.get("evidence_pattern") or {},
        prior_disposition=raw.get("prior_disposition"),
        challenge_prompt=raw.get("challenge_prompt"),
        tags=tuple(str(x) for x in raw.get("tags", [])),
    )


def memories(path: Path | str = DEFAULT_PATH) -> list[Memory]:
    return [_memory(x) for x in load_brain(path)["memories"]]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text.lower()))


def _memory_text(m: Memory) -> str:
    flat = [m.topic, m.statement, m.type, *m.controls, *m.tags]
    for v in m.evidence_pattern.values():
        flat.extend(v if isinstance(v, list) else [v])
    if m.challenge_prompt:
        flat.append(m.challenge_prompt)
    return " ".join(map(str, flat))


def retrieve(control_id: str, requirement: str, evidence_text: str = "", *, role: str = "assessor", limit: int = 5,
             path: Path | str = DEFAULT_PATH) -> list[dict]:
    """Retrieve relevant memories using control match + lexical overlap.

    Authority tier breaks close score ties in favour of more authoritative material. Returned
    records are context, not findings. Role filters avoid feeding challenge-only prompts to the
    assessor and vice versa.
    """
    q = _tokens(" ".join([control_id, requirement or "", evidence_text[:6000]]))
    candidates = []
    for m in memories(path):
        control_match = control_id in m.controls or "*" in m.controls
        overlap = len(q & _tokens(_memory_text(m)))
        if not control_match and overlap == 0:
            continue
        role_bonus = 0
        if role == "challenger" and m.type == "challenge_pattern": role_bonus = 3
        if role == "assessor" and m.type in {"precedent", "approved_interpretation", "evidence_pattern"}: role_bonus = 2
        control_bonus = 8 if control_match else 0
        score = control_bonus + overlap + role_bonus
        candidates.append((score, -m.rank, m))
    candidates.sort(reverse=True, key=lambda x: (x[0], x[1], x[2].memory_id))
    return [{**asdict(m), "authority_rank": m.rank, "score": score} for score, _neg, m in candidates[:limit]]


def format_context(rows: Iterable[dict], *, max_chars: int = 7000) -> str:
    blocks = []
    for r in rows:
        examples = []
        for k, v in (r.get("evidence_pattern") or {}).items():
            examples.append(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}")
        blocks.append(
            f"[{r['memory_id']}] tier={r['authority_tier']} type={r['type']}\n"
            f"Topic: {r['topic']}\n"
            f"Statement: {r['statement']}\n"
            + (f"Evidence pattern: {'; '.join(examples)}\n" if examples else "")
            + (f"Prior disposition: {r['prior_disposition']}\n" if r.get('prior_disposition') else "")
            + (f"Challenge prompt: {r['challenge_prompt']}\n" if r.get('challenge_prompt') else "")
        )
    text = "\n".join(blocks)
    return text[:max_chars]



@dataclass(frozen=True)
class ControlTesting:
    control_id: str
    framework: str
    title: str
    requirement_basis: str
    objective: str
    owner: str
    evidence_artifacts: tuple[str, ...]
    linked_play: tuple[str, ...]
    testing: dict
    provenance: dict
    authority_tier: str


def load_control_testing(path: Path | str = DEFAULT_TESTING_PATH) -> dict:
    """Load the normalized control-testing knowledge base generated from the workbook."""
    import yaml
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("controls"), list):
        raise ValueError("control testing knowledge base must contain a controls list")
    return data


def _testing(raw: dict) -> ControlTesting:
    return ControlTesting(
        control_id=str(raw["control_id"]), framework=str(raw.get("framework", "")),
        title=str(raw.get("title", "")), requirement_basis=str(raw.get("requirement_basis", "")),
        objective=str(raw.get("objective", "")), owner=str(raw.get("owner", "")),
        evidence_artifacts=tuple(str(x) for x in raw.get("evidence_artifacts", [])),
        linked_play=tuple(str(x) for x in raw.get("linked_play", [])),
        testing=raw.get("testing") or {}, provenance=raw.get("provenance") or {},
        authority_tier=str(raw.get("authority_tier", "example")),
    )


def control_testing_records(path: Path | str = DEFAULT_TESTING_PATH) -> list[ControlTesting]:
    return [_testing(x) for x in load_control_testing(path)["controls"]]


def _framework_alias(lib: str) -> set[str]:
    aliases = {
        "MGF Agentic": {"MGF_Agentic", "MGF Agentic"},
        "NIST AI RMF": {"NIST_AI_RMF", "NIST AI RMF"},
        "ISO 42001": {"ISO42001", "ISO 42001"},
    }
    return aliases.get(lib, {lib})


def retrieve_control_testing(control_id: str, framework: str = "", requirement: str = "", evidence_text: str = "", *, limit: int = 3,
                             path: Path | str = DEFAULT_TESTING_PATH) -> list[dict]:
    """Retrieve the control's testing procedure knowledge. This is advisory testing context, not a decision."""
    q = _tokens(" ".join([control_id, requirement or "", evidence_text[:4000]]))
    rows=[]
    aliases=_framework_alias(framework)
    for r in control_testing_records(path):
        if r.framework not in aliases and framework:
            continue
        exact = r.control_id == control_id
        overlap = len(q & _tokens(" ".join([r.control_id, r.title, r.requirement_basis, r.objective, *r.linked_play, *r.evidence_artifacts])))
        if not exact and overlap == 0:
            continue
        score = (20 if exact else 0) + overlap
        rows.append((score, -TIER_RANK.get(r.authority_tier, 99), r))
    rows.sort(reverse=True, key=lambda x:(x[0],x[1],x[2].control_id))
    return [{**asdict(r), "score": score, "authority_rank": -neg} for score,neg,r in rows[:limit]]


def format_control_testing_context(rows: Iterable[dict], *, max_chars: int = 8500) -> str:
    blocks=[]
    for r in rows:
        t=r.get("testing") or {}
        design=t.get("design") or []
        operating=t.get("operating") or []
        play_steps=t.get("play_steps") or []
        lines=[f"[{r['framework']} {r['control_id']}] title={r['title']}",
               f"Testing knowledge authority={r.get('authority_tier')} source_status={t.get('source_status')}"]
        if r.get("requirement_basis"): lines.append(f"Requirement basis: {r['requirement_basis']}")
        if r.get("objective"): lines.append(f"Objective: {r['objective']}")
        if r.get("evidence_artifacts"): lines.append("Expected artefacts: " + "; ".join(r['evidence_artifacts']))
        if r.get("linked_play"): lines.append("Linked plays: " + "; ".join(r['linked_play']))
        if design: lines.append("Test of Design: " + " | ".join(design[:8]))
        if operating: lines.append("Test of Operating Effectiveness: " + " | ".join(operating[:10]))
        if play_steps:
            lines.append("Play-derived operating steps: " + " | ".join(f"{x['play']} {x['step']}: {x['action']}" for x in play_steps[:8]))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)[:max_chars]


def validate_control_testing(path: Path | str = DEFAULT_TESTING_PATH) -> list[str]:
    errors=[]; seen=set()
    data=load_control_testing(path)
    for raw in data["controls"]:
        cid=str(raw.get("control_id", "")); fw=str(raw.get("framework", "")); key=(fw,cid)
        if not cid: errors.append("missing control_id")
        if key in seen: errors.append(f"duplicate control: {fw}/{cid}")
        seen.add(key)
        if not raw.get("title"): errors.append(f"missing title: {fw}/{cid}")
        if not raw.get("testing"): errors.append(f"missing testing block: {fw}/{cid}")
        if raw.get("authority_tier") not in TIER_RANK: errors.append(f"invalid authority tier: {fw}/{cid}")
        src=(raw.get("provenance") or {}).get("source_file")
        if not src: errors.append(f"missing provenance source: {fw}/{cid}")
    return errors

def validate_brain(path: Path | str = DEFAULT_PATH) -> list[str]:
    errors = []
    data = load_brain(path)
    seen = set()
    for raw in data["memories"]:
        mid = raw.get("memory_id")
        if not mid or mid in seen: errors.append(f"duplicate/missing memory_id: {mid}")
        seen.add(mid)
        if raw.get("authority_tier") not in TIER_RANK: errors.append(f"invalid authority tier: {mid}")
        if not raw.get("statement"): errors.append(f"missing statement: {mid}")
        if not raw.get("controls"): errors.append(f"missing controls: {mid}")
    return errors
