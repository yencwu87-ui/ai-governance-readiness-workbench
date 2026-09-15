"""WB-047 knowledge resolver: local governance RAG + optional live web knowledge.

Internet material is advisory context only. It is never treated as organisational evidence and
cannot override the control contract, submitted evidence, or deterministic validation.
"""
from __future__ import annotations
import datetime as dt
import os
from typing import Any

from ollama_search import search_web_checked


def _local(control_id, framework, requirement, evidence, role):
    from governance.knowledge import (
        retrieve, format_context, retrieve_control_testing,
        format_control_testing_context,
    )
    memories = retrieve(control_id, requirement, evidence, role=role)
    testing = retrieve_control_testing(control_id, framework, requirement, evidence, limit=2)
    return memories, testing, format_context(memories), format_control_testing_context(testing)


def _needs_web(control_id: str, framework: str, requirement: str, task: str) -> bool:
    mode = os.environ.get("WB_WEB_KNOWLEDGE", "auto").strip().lower()
    if mode in {"off", "false", "0", "no"}:
        return False
    if mode in {"always", "on", "true", "1", "yes"}:
        return True
    text = f"{control_id} {framework} {requirement} {task}".lower()
    cues = (
        "current", "latest", "regulation", "regulatory", "guidance", "consultation",
        "effective date", "in force", "supervisory", "mas", "imda", "pdpa", "eu ai act",
        "nist update", "standard update", "version", "amendment", "regulatory change",
    )
    return any(c in text for c in cues)


def _web(query: str, max_results: int = 5) -> tuple[list[dict[str, Any]], str | None]:
    return search_web_checked(query, max_results=max_results)


def _web_context(rows: list[dict], error: str | None = None) -> str:
    if error:
        # WB-056: never render a failed search as a quiet one. The model is told the channel
        # was unavailable so it cannot silently reason as though current guidance was checked.
        return f"(external knowledge WAS SOUGHT AND COULD NOT BE RETRIEVED - {error}. Do not " \
               f"assume current guidance has been checked.)"
    if not rows:
        return "(external knowledge was searched and returned nothing relevant)"
    parts=[]
    for i,r in enumerate(rows,1):
        parts.append(f"[WEB-{i}] {r['title']}\n{r['snippet']}\nURL: {r['url']}")
    return "\n\n".join(parts)


def resolve(control, evidence_text: str = "", *, role: str = "assessor", task: str = "", force_web: bool | None = None, element_ids: list[str] | None = None) -> dict:
    """Return governed local context plus optional current external context.

    Local knowledge retrieval and external web search are independent, read-only channels. When
    web retrieval is requested they are executed concurrently; their provenance/degraded-state
    semantics remain unchanged.
    """
    cid = str(getattr(control, "id", ""))
    framework = str(getattr(control, "lib", ""))
    requirement = str(getattr(control, "req", ""))
    from governance.element_registry import elements_for
    canonical_elements = elements_for(cid, framework)
    wanted = {str(x) for x in (element_ids or [])}
    scoped_elements = [e for e in canonical_elements if not wanted or e["element_id"] in wanted]
    use_web = _needs_web(cid, framework, requirement, task) if force_web is None else bool(force_web)
    query = f"{framework} {cid} {requirement} {task}".strip()
    query += f" {dt.date.today().year}"

    memories, testing, local_context, testing_context = [], [], "", ""
    local_error = None
    web_rows, web_error = [], None

    def get_local():
        return _local(cid, framework, requirement, evidence_text, role)

    if use_web:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            local_future = pool.submit(get_local)
            web_future = pool.submit(_web, query, int(os.environ.get("WB_WEB_MAX_RESULTS", "5")))
            try:
                memories, testing, local_context, testing_context = local_future.result()
            except Exception as exc:
                local_error = f"{type(exc).__name__}: {exc}"
                local_context = f"(local governance knowledge unavailable: {exc})"
                testing_context = "(control testing knowledge unavailable)"
            try:
                web_rows, web_error = web_future.result()
            except Exception as exc:
                web_error = f"{type(exc).__name__}: {exc}"
    else:
        try:
            memories, testing, local_context, testing_context = get_local()
        except Exception as exc:
            local_error = f"{type(exc).__name__}: {exc}"
            local_context = f"(local governance knowledge unavailable: {exc})"
            testing_context = "(control testing knowledge unavailable)"

    # Element-scoped local/testing retrieval is the contract spine. It is read-only metadata and
    # can never add or rename governed elements. Internet retrieval remains control-level by default
    # to avoid one web request per element; set WB_RAG_WEB_PER_ELEMENT=1 for hard, bounded per-element
    # regulatory lookups.
    element_bundles: dict[str, dict] = {}
    if scoped_elements:
        from governance.knowledge import retrieve_for_element, retrieve_testing_for_element
        web_per_element = use_web and os.environ.get("WB_RAG_WEB_PER_ELEMENT", "0").strip().lower() in {"1", "true", "yes", "on"}
        for e in scoped_elements:
            meta = dict(e)
            try:
                from governance.element_contract import element_testing_context
                meta["testing_metadata"] = (element_testing_context(cid, framework).get(e["element_id"]) or {})
            except Exception:
                meta["testing_metadata"] = {}
            local_e = retrieve_for_element(cid, meta, evidence_text, role=role, limit=int(os.environ.get("WB_RAG_ELEMENT_K", "4")))
            testing_e = retrieve_testing_for_element(cid, framework, meta, evidence_text, limit=int(os.environ.get("WB_RAG_ELEMENT_TEST_K", "3")))
            web_e = []
            if web_per_element:
                q_e = f"{framework} {cid} {e['element_id']} {e['text']} {task} {dt.date.today().year}"
                try:
                    web_e, _web_e_err = _web(q_e, int(os.environ.get("WB_WEB_MAX_RESULTS", "5")))
                except Exception:
                    web_e = []
            hint_caps = list((meta.get("testing_metadata") or {}).get("capability_hints") or [])
            element_bundles[e["element_id"]] = {
                "element_id": e["element_id"], "element_key": e["element_key"], "text": e["text"],
                "locator": e["locator"], "local": local_e, "testing": testing_e, "internet": web_e,
                "capabilities": hint_caps,
                "testing_metadata": meta.get("testing_metadata") or {},
            }

    # WB-101 keeps the independent modes separate.  The existing return fields remain for
    # compatibility with callers/UI code, while assessor and challenger consume this typed
    # contract rather than a flattened, source-ambiguous context string.
    from governance.retrieval_plane import build_plane
    retrieval_plane = build_plane(
        control_id=cid, framework=framework, requirement=requirement, role=role,
        memories=memories, testing=testing, element_bundles=element_bundles,
        web_rows=web_rows, web_attempted=use_web, web_error=web_error,
        local_error=local_error, evidence_text=evidence_text, task=task,
    )
    retrieval_receipt = retrieval_plane["retrieval_receipt"]

    try:
        from governance.knowledge_monitor import record as _record_knowledge_usage
        _record_knowledge_usage(
            role=role, task=task, control_id=cid, framework=framework,
            local_memories=memories, testing_rows=testing, web_rows=web_rows,
            web_attempted=use_web, web_error=web_error, local_error=local_error, web_query=query if use_web else "",
            element_bundles=element_bundles,
            retrieval_receipt=retrieval_receipt,
        )
    except Exception:
        # Observability must never make retrieval fail.
        pass

    return {
        "local_context": local_context,
        "testing_context": testing_context,
        "web_context": _web_context(web_rows, web_error),
        "web_used": bool(web_rows),
        "web_attempted": use_web,
        "web_error": web_error,
        "web_degraded": bool(use_web and web_error),
        "web_query": query if use_web else "",
        "web_sources": [
            {"source_type":"internet", "rank":i, "title":r["title"], "url":r["url"], "query":query}
            for i,r in enumerate(web_rows,1)
        ],
        "local_error": local_error,
        "local_degraded": bool(local_error),
        "memories": memories,
        "testing": testing,
        "elements": element_bundles,
        "element_scope": [e["element_id"] for e in scoped_elements],
        "retrieval_plane": retrieval_plane,
        "retrieval_receipt": retrieval_receipt,
    }


def resolver_flags(bundle: dict) -> list[str]:
    """Validator-style flags for anything the reviewer must be told about this retrieval.

    Returned rather than logged, so the caller puts them where a human will actually see them —
    on the proposal, beside the rating.
    """
    flags = []
    if bundle.get("web_degraded"):
        flags.append(f"External knowledge was sought and could not be retrieved: "
                     f"{bundle.get('web_error')}. This assessment reflects local governed "
                     f"knowledge only.")
    if bundle.get("local_degraded"):
        flags.append(f"Local governance knowledge was unavailable: {bundle.get('local_error')}.")
    return flags


def combined_context(bundle: dict) -> str:
    from governance.knowledge import format_element_context
    element_context = format_element_context(bundle.get("elements") or {})
    return (
        "LOCAL GOVERNANCE KNOWLEDGE (ADVISORY)\n"
        + bundle.get("local_context", "(none)")
        + "\n\nCONTROL TESTING KNOWLEDGE (ADVISORY; derived from governed control library)\n"
        + bundle.get("testing_context", "(none)")
        + "\n\nELEMENT-SCOPED GOVERNANCE CONTEXT (ADVISORY; ELEMENT ID IS THE GOVERNED KEY)\n"
        + (element_context or "(none)")
        + "\n\nCURRENT EXTERNAL KNOWLEDGE (ADVISORY; NEVER COMPLIANCE EVIDENCE)\n"
        + bundle.get("web_context", "(none)")
    )


def typed_context(bundle: dict, *, max_chars: int = 15000) -> str:
    """The WB-101 model-facing retrieval contract.

    Deliberately separate from :func:`combined_context`: the latter is retained only for
    backwards-compatible displays.  New assessor/challenger calls receive typed lanes plus
    their receipt, which makes a missing episodic lookup distinguishable from zero episodes.
    """
    from governance.retrieval_plane import format_for_model
    return format_for_model(bundle.get("retrieval_plane") or {}, max_chars=max_chars)


def element_knowledge_digest(bundle: dict) -> dict[str, dict]:
    """Compact, audit-friendly per-element retrieval record for persisted run outputs/UI."""
    out = {}
    for eid, row in (bundle.get("elements") or {}).items():
        out[str(eid)] = {
            "element_key": row.get("element_key"),
            "text": row.get("text"),
            "local_ids": [str(x.get("memory_id")) for x in row.get("local") or [] if x.get("memory_id")],
            "testing_controls": [str(x.get("control_id")) for x in row.get("testing") or [] if x.get("control_id")],
            "internet_sources": [
                {"rank": i + 1, "title": str(x.get("title", "")), "url": str(x.get("url", ""))}
                for i, x in enumerate(row.get("internet") or [])
            ],
            "capabilities": list(row.get("capabilities") or []),
            "retrieval_methods": sorted({str(m) for x in (row.get("local") or []) for m in (x.get("retrieval_methods") or [x.get("retrieval_method", "")]) if m}),
        }
    return out
