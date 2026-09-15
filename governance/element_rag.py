"""Element-centric RAG ranking.

The governed element is the retrieval anchor. Query expansion uses the element text plus testing
metadata; lexical and optional embedding rankings are fused by RRF, then diversity-filtered.
This module returns advisory context only and cannot create a governed element.
"""
from __future__ import annotations
from typing import Any


def _text(row: dict) -> str:
    vals = [row.get("topic"), row.get("statement"), row.get("type"), *(row.get("tags") or [])]
    ep = row.get("evidence_pattern") or {}
    for v in ep.values():
        vals.extend(v if isinstance(v, list) else [v])
    return " ".join(str(x) for x in vals if x)


def expand_query(element: dict[str, Any], evidence_text: str = "") -> str:
    meta = element.get("testing_metadata") or {}
    bits = [element.get("text", ""), *[str(x) for x in meta.get("evidence_types") or []],
            meta.get("failure_condition", ""), *[str(x) for x in meta.get("capability_hints") or []],
            (evidence_text or "")[:1800]]
    return " ".join(x for x in bits if x)


def rank_memory_rows(element: dict[str, Any], rows: list[dict], evidence_text: str = "", *, k: int = 4) -> list[dict]:
    q = set(_text({"statement": expand_query(element, evidence_text)}).lower().split())
    scored = []
    for row in rows:
        toks = set(_text(row).lower().split())
        lexical = len(q & toks)
        control_bonus = 8 if element.get("control_id", "") in (row.get("controls") or []) else 0
        scored.append((control_bonus + lexical, row))
    scored.sort(key=lambda x: (-x[0], str(x[1].get("memory_id", ""))))
    return [dict(r, element_rag_score=s, element_query=expand_query(element, evidence_text),
                 retrieval_method="element-expanded-lexical") for s, r in scored[:k]]


def rrf_merge(lexical: list[dict], semantic: list[dict], *, k: int = 60, top_k: int = 4) -> list[dict]:
    by_id: dict[str, dict] = {}
    for source, rows in (("lexical", lexical), ("semantic", semantic)):
        for rank, row in enumerate(rows, 1):
            rid = str(row.get("memory_id") or row.get("id") or rank)
            item = by_id.setdefault(rid, dict(row))
            item.setdefault("retrieval_methods", [])
            item["retrieval_methods"].append(source)
            item["rrf"] = float(item.get("rrf", 0.0)) + 1.0 / (k + rank)
    out = sorted(by_id.values(), key=lambda x: (-float(x.get("rrf", 0)), str(x.get("memory_id", ""))))
    return out[:top_k]
