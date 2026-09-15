"""WB-101 typed retrieval plane.

Retrieval remains advisory: it never changes a requirement, evidence record, assessment, or
human decision.  Its job is to make each independently-auditable retrieval mode explicit:
semantic knowledge, prior assessment episodes, testing procedure, and regulatory context.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "wb101.retrieval-plane.1"


class EpisodicUnavailable(RuntimeError):
    """The append-only ledger could not be read.

    Raised so the retrieval receipt can say "episodic did not complete" instead of reporting a
    clean run that found nothing.  Zero episodes and an unreadable ledger are different facts
    and a governance record must not merge them.
    """


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9_.-]{2,}", (value or "").lower()))


def _compact(value: Any, limit: int = 700) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:limit]


def _element_ids(state: dict[str, Any]) -> list[str]:
    ids: set[str] = set()
    for row in ((state.get("proposal") or {}).get("elementVerdicts") or []):
        if isinstance(row, dict) and row.get("element_id"):
            ids.add(str(row["element_id"]))
    for row in ((state.get("diff") or {}).get("disagreements") or []):
        ids.add(str(row))
    return sorted(ids)


def _episode_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Make a retrieval-safe, compact read model of one historical assessment cycle."""
    proposal = state.get("proposal") or {}
    read = state.get("read") or {}
    decision = state.get("decision") or {}
    challenges = state.get("challenges") or []
    challenge_rows = [x for x in challenges if isinstance(x, dict)]
    decisions = [str(x.get("challenge_outcome") or "") for x in challenge_rows if x.get("challenge_outcome")]
    evidence = state.get("evidence") or {}
    evidence_text = _compact(evidence.get("text") or evidence.get("summary") or evidence.get("name") or "")
    assessor = {
        "sufficiency": proposal.get("sufficiency"),
        "maturity": proposal.get("proposedMaturity"),
        "element_verdicts": [
            {"element_id": r.get("element_id"), "status": r.get("status")}
            for r in proposal.get("elementVerdicts") or [] if isinstance(r, dict)
        ],
    }
    reviewer = {
        "sufficiency": read.get("sufficiency"),
        "maturity": read.get("maturity"),
        "reason": _compact(read.get("reason"), 350),
    }
    human = dict(decision) if isinstance(decision, dict) else {"value": decision}
    human = {k: v for k, v in human.items() if k in {"sufficiency", "maturity", "reason", "reviewer", "decision"}}
    return {
        "episode_id": state.get("cycle_id"),
        "assessment_id": (state.get("assessment_identity") or {}).get("assessment_id") or state.get("cycle_id"),
        "control_id": state.get("control_id"),
        "framework": state.get("framework"),
        "element_ids": _element_ids(state),
        "prior_assessor_verdict": assessor,
        "reviewer_verdict": reviewer,
        "challenger_verdict": {
            "count": len(challenge_rows),
            "outcomes": decisions,
            "strong_count": sum(
                1 for c in challenge_rows for x in (c.get("challenges") or [])
                if isinstance(x, dict) and x.get("challenge_strength") == "strong"
            ),
        },
        "human_decision": human,
        "evidence_pattern": evidence_text,
        "disagreement": (state.get("diff") or {}).get("disagreements") or [],
        "resolution": _compact(
            human.get("reason") or human.get("decision") or decision.get("reason") if isinstance(decision, dict) else "",
            500,
        ),
        "date": state.get("decision_recorded_at") or state.get("updated") or state.get("started"),
        "source": "append_only_event_log",
    }


def retrieve_episodes(control_id: str, framework: str, requirement: str = "", evidence_text: str = "", *,
                      element_ids: Iterable[str] | None = None, limit: int = 5,
                      event_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Retrieve prior *decided* assessment episodes from the append-only event ledger.

    A curated ``brain.yaml`` precedent deliberately does not qualify here.  This lane contains
    only replayable cycles that reached a human decision.  It returns summaries and pointers,
    not source evidence; an old decision is context, never proof for the current one.
    """
    try:
        import events
        states = list(events.iter_states(Path(event_path) if event_path else None))
    except Exception as exc:
        # WB-102: a ledger that could not be read is not "no matching episode".  The caller
        # needs to be able to tell those apart, so the failure is raised into the receipt
        # rather than flattened into an empty result.
        raise EpisodicUnavailable(f"episodic ledger could not be read: {exc}") from exc
    wanted_elements = {str(x) for x in (element_ids or []) if str(x)}
    query = _tokens(" ".join([control_id, framework, requirement, evidence_text[:3000]]))
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for state in states:
        if state.get("stage") != "decided":
            continue
        # Same control is a high-confidence episode.  Same-framework episodes can still be
        # helpful only where there is substantive lexical overlap.
        same_control = str(state.get("control_id")) == str(control_id)
        same_framework = str(state.get("framework")) == str(framework)
        episode = _episode_from_state(state)
        haystack = " ".join([
            str(episode.get("control_id") or ""), str(episode.get("framework") or ""),
            str(episode.get("evidence_pattern") or ""), str(episode.get("resolution") or ""),
            str(episode.get("prior_assessor_verdict") or ""),
        ])
        overlap = len(query & _tokens(haystack))
        element_overlap = len(wanted_elements & set(episode["element_ids"]))
        if not same_control and (not same_framework or overlap == 0):
            continue
        score = (100 if same_control else 10) + overlap + (8 * element_overlap)
        episode["retrieval_score"] = score
        ranked.append((score, str(episode.get("date") or ""), episode))
    ranked.sort(key=lambda x: (x[0], x[1], x[2]["episode_id"]), reverse=True)
    return [x[2] for x in ranked[:max(0, int(limit))]]


def _registry_sources(framework: str, requirement: str, *, as_of: str) -> dict[str, list[dict[str, Any]]]:
    """Return versioned regulatory sources, retaining their effective/proposed history."""
    empty = {"effective_sources": [], "proposed_sources": [], "superseded_sources": []}
    try:
        from governance.triangulation import SourceRegistry, change_state
        registry = SourceRegistry.from_yaml()
    except Exception:
        return empty
    q = _tokens(f"{framework} {requirement}")
    buckets = dict(empty)
    for source in registry.sources.values():
        source_text = f"{source.title} {source.issuer} {source.notes or ''}"
        # Framework/issuer matching makes MAS controls discover MAS sources even if the
        # requirement text does not repeat the regulator's name.
        framework_match = (str(framework).upper().startswith("MAS") and "MAS" in source_text.upper())
        if not framework_match and not (q & _tokens(source_text)):
            continue
        item = {
            "source_id": source.source_id, "title": source.title, "issuer": source.issuer,
            "authority_tier": source.authority_tier, "normative_status": source.normative_status,
            "lifecycle_status": source.lifecycle_status, "temporal_status": change_state(source, dt.date.fromisoformat(as_of)),
            "publication_date": source.publication_date, "effective_from": source.effective_from,
            "effective_to": source.effective_to, "source_uri": source.source_uri,
        }
        if source.lifecycle_status == "effective":
            buckets["effective_sources"].append(item)
        elif source.lifecycle_status == "proposed":
            buckets["proposed_sources"].append(item)
        elif source.lifecycle_status in {"superseded", "historical", "expired", "withdrawn"}:
            buckets["superseded_sources"].append(item)
    for rows in buckets.values():
        rows.sort(key=lambda x: (x["authority_tier"], x["source_id"]))
    return buckets


def build_plane(*, control_id: str, framework: str, requirement: str, role: str,
                memories: list[dict] | None = None, testing: list[dict] | None = None,
                element_bundles: dict[str, dict] | None = None, web_rows: list[dict] | None = None,
                web_attempted: bool = False, web_error: str | None = None,
                local_error: str | None = None, evidence_text: str = "", task: str = "",
                as_of: str | None = None) -> dict[str, Any]:
    """Compose the four typed lanes and their machine-readable retrieval receipt."""
    elements = element_bundles or {}
    memories = memories or []
    testing = testing or []
    web_rows = web_rows or []
    date = as_of or dt.date.today().isoformat()
    semantic_hits = [
        {"memory_id": x.get("memory_id"), "score": x.get("score"), "authority_tier": x.get("authority_tier"),
         "type": x.get("type"), "source": "governance_knowledge"}
        for x in memories
    ]
    semantic_elements = {
        eid: [
            {"memory_id": x.get("memory_id"), "score": x.get("rrf", x.get("element_rag_score", x.get("semantic_score"))),
             "cosine": x.get("semantic_cos"), "methods": x.get("retrieval_methods") or [x.get("retrieval_method", "lexical")],
             "source": "element_scoped_governance_knowledge"}
            for x in (row.get("local") or [])
        ] for eid, row in elements.items()
    }
    requested_ids = list(elements)
    episodic_error: str | None = None
    try:
        episodes = retrieve_episodes(control_id, framework, requirement, evidence_text,
                                     element_ids=requested_ids)
    except EpisodicUnavailable as exc:
        episodes = []
        episodic_error = str(exc)
    procedural_elements = {
        eid: [
            {"control_id": x.get("control_id"), "framework": x.get("framework"), "score": x.get("score"),
             "testing": x.get("testing"), "evidence_artifacts": x.get("evidence_artifacts") or [],
             "capabilities": (row.get("testing_metadata") or {}).get("capability_hints") or []}
            for x in (row.get("testing") or [])
        ] for eid, row in elements.items()
    }
    regulatory = _registry_sources(framework, requirement, as_of=date)
    regulatory["web_checks"] = [
        {"title": x.get("title"), "url": x.get("url"), "snippet": x.get("snippet"), "retrieved_at": x.get("retrieved_at")}
        for x in web_rows
    ]
    regulatory["web_attempted"] = bool(web_attempted)
    regulatory["web_error"] = web_error
    regulatory["as_of"] = date
    plane = {
        "schema": SCHEMA, "control_id": control_id, "framework": framework, "role": role,
        "semantic": {"query": requirement, "method": ["lexical", "embedding", "rrf"], "hits": semantic_hits, "element_hits": semantic_elements},
        "episodic": {"query": requirement, "matching_episodes": episodes},
        "procedural": {"control_testing": testing, "element_testing": procedural_elements},
        "regulatory": regulatory,
    }
    plane["retrieval_receipt"] = receipt_for(plane, local_error=local_error,
                                            web_attempted=web_attempted, web_error=web_error,
                                            episodic_error=episodic_error)
    return plane


def receipt_for(plane: dict[str, Any], *, local_error: str | None = None,
                web_attempted: bool = False, web_error: str | None = None,
                episodic_error: str | None = None) -> dict[str, Any]:
    """A stable, inspectable statement of which independent lanes actually ran."""
    semantic = plane.get("semantic") or {}
    procedural = plane.get("procedural") or {}
    regulatory = plane.get("regulatory") or {}
    counts = {
        "semantic": len(semantic.get("hits") or []) + sum(len(v or []) for v in (semantic.get("element_hits") or {}).values()),
        "episodic": len((plane.get("episodic") or {}).get("matching_episodes") or []),
        "procedural": len(procedural.get("control_testing") or []) + sum(len(v or []) for v in (procedural.get("element_testing") or {}).values()),
        "regulatory": sum(len(regulatory.get(k) or []) for k in ("effective_sources", "proposed_sources", "superseded_sources", "web_checks")),
        # Split out so a non-zero count can never imply the half that failed succeeded.
        "regulatory_registry": sum(len(regulatory.get(k) or []) for k in ("effective_sources", "proposed_sources", "superseded_sources")),
        "regulatory_web": len(regulatory.get("web_checks") or []),
    }
    return {
        "schema": "wb101.retrieval-receipt.1",
        "semantic": {"attempted": True, "completed": not bool(local_error), "result_count": counts["semantic"], "degraded": bool(local_error), "error": local_error},
        "episodic": {"attempted": True, "completed": not bool(episodic_error), "result_count": counts["episodic"], "degraded": bool(episodic_error), "error": episodic_error},
        "procedural": {"attempted": True, "completed": not bool(local_error), "result_count": counts["procedural"], "degraded": bool(local_error), "error": local_error},
        "regulatory": {
            "attempted": True,                       # the versioned source registry always runs
            "web_attempted": bool(web_attempted),    # the optional web check may not have
            "completed": not bool(web_error),
            "result_count": counts["regulatory"],
            "registry_count": counts["regulatory_registry"],
            "web_count": counts["regulatory_web"],
            "degraded": bool(web_error),
            "error": web_error,
        },
        "degraded": [name for name, row in (("semantic", local_error), ("episodic", episodic_error),
                                            ("procedural", local_error), ("regulatory", web_error)) if row],
    }


def unavailable_plane(*, control_id: str, framework: str, role: str, error: str) -> dict[str, Any]:
    """Represent resolver failure without pretending the independent lanes ran."""
    lane = {"attempted": False, "completed": False, "result_count": 0, "degraded": True, "error": error}
    return {
        "schema": SCHEMA, "control_id": control_id, "framework": framework, "role": role,
        "semantic": {"query": "", "method": [], "hits": [], "element_hits": {}},
        "episodic": {"query": "", "matching_episodes": []},
        "procedural": {"control_testing": [], "element_testing": {}},
        "regulatory": {"effective_sources": [], "proposed_sources": [], "superseded_sources": [], "web_checks": []},
        "retrieval_receipt": {
            "schema": "wb101.retrieval-receipt.1",
            "semantic": dict(lane), "episodic": dict(lane), "procedural": dict(lane), "regulatory": dict(lane),
            "degraded": ["semantic", "episodic", "procedural", "regulatory"],
        },
    }


def format_for_model(plane: dict[str, Any], *, max_chars: int = 15000) -> str:
    """Render the structured contract as JSON; lanes must not be merged into untyped prose."""
    import json
    return json.dumps(plane, ensure_ascii=False, sort_keys=True, indent=2, default=str)[:max_chars]
