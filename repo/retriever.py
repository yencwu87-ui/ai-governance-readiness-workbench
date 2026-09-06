"""Hybrid retrieval: BM25 (lexical) fused with local embeddings (semantic) by reciprocal rank
fusion. Falls back to BM25 alone if no embedding backend is reachable, and says so.

Why both:
- BM25 is deterministic, explainable (you can show the matched terms) and needs no model. It
  fails when the step says "materiality score & rationale" and the document says
  "impact 4, complexity 3, reliance 2 — tier: High". No shared vocabulary, no hit.
- Embeddings catch that paraphrase but are opaque and model-dependent.
- Fusing ranks keeps the explainable path in the loop and makes a hit that both methods agree
  on rank highest. A result found only by one method is still surfaced, labelled with which.

Embeddings go through Ollama's /api/embeddings (default model nomic-embed-text) so nothing
leaves the machine. Vectors are cached on disk keyed by (model, sha256(text)).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from rank_bm25 import BM25Okapi

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("WB_EMBED_MODEL", "nomic-embed-text")
CACHE = Path(__file__).parent / ".cache" / "embeddings.jsonl"

_tok = re.compile(r"[a-z0-9][a-z0-9\-\.]*")


def tokenize(text: str) -> list[str]:
    return _tok.findall(text.lower())


@dataclass
class Chunk:
    doc_id: str
    idx: int
    text: str

    @property
    def id(self) -> str:
        return f"{self.doc_id}#{self.idx}"

    @property
    def label(self) -> str:
        """Short id for display: basename#idx."""
        return f"{self.doc_id.replace(chr(92), '/').rsplit('/', 1)[-1]}#{self.idx}"


@dataclass
class Hit:
    chunk: Chunk
    score: float
    found_by: list[str] = field(default_factory=list)   # ["bm25"], ["embed"], or both
    bm25_terms: list[str] = field(default_factory=list)


def chunk_documents(docs: dict[str, str], size: int = 900, overlap: int = 150) -> list[Chunk]:
    """docs: {doc_id: full_text}. Paragraph-aware fixed-size chunks with overlap."""
    out: list[Chunk] = []
    for did, text in docs.items():
        text = re.sub(r"\r\n?", "\n", text or "").strip()
        if not text:
            continue
        i, n = 0, 0
        while i < len(text):
            j = min(len(text), i + size)
            if j < len(text):
                # prefer paragraph, then sentence, then word boundary in the back half
                for pat in ("\n", ". ", " "):
                    cut = text.rfind(pat, i + size // 2, j)
                    if cut > 0:
                        j = cut + (len(pat) if pat != "\n" else 0)
                        break
            piece = text[i:j].strip()
            if piece:
                out.append(Chunk(did, n, piece)); n += 1
            if j >= len(text):
                break
            # step back to a word boundary for the overlap so no chunk starts mid-word
            nxt = max(j - overlap, i + 1)
            sp = text.rfind(" ", i + 1, nxt)
            i = sp + 1 if sp > i else nxt
    return out


# ---- embeddings -----------------------------------------------------------------------
def _load_cache() -> dict[str, list[float]]:
    if not CACHE.exists():
        return {}
    c = {}
    with CACHE.open(encoding="utf-8") as f:
        for l in f:
            try:
                r = json.loads(l); c[r["k"]] = r["v"]
            except Exception:
                pass
    return c


def _key(text: str, model: str) -> str:
    return model + ":" + hashlib.sha256(text.encode()).hexdigest()


def embed(texts: list[str], model: str = EMBED_MODEL, timeout: int = 60) -> list[list[float]] | None:
    """Return one vector per text, or None if Ollama/model is unavailable."""
    cache = _load_cache()
    out: list[list[float] | None] = [cache.get(_key(t, model)) for t in texts]
    todo = [i for i, v in enumerate(out) if v is None]
    if todo:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with CACHE.open("a", encoding="utf-8") as f:
                for i in todo:
                    req = urllib.request.Request(
                        f"{OLLAMA}/api/embeddings",
                        data=json.dumps({"model": model, "prompt": texts[i]}).encode(),
                        headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=timeout) as r:
                        v = json.loads(r.read())["embedding"]
                    out[i] = v
                    f.write(json.dumps({"k": _key(texts[i], model), "v": v}) + "\n")
        except Exception:
            return None
    return out  # type: ignore[return-value]


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ---- index ------------------------------------------------------------------------------
class HybridIndex:
    def __init__(self, chunks: list[Chunk], use_embeddings: bool = True):
        self.chunks = chunks
        self.bm25 = BM25Okapi([tokenize(c.text) for c in chunks]) if chunks else None
        self.vectors: list[list[float]] | None = None
        self.embed_status = "off"
        if not chunks:
            self.embed_status = "no documents indexed"
        elif use_embeddings:
            vs = embed([c.text for c in chunks])
            if vs is not None and all(v is not None for v in vs):
                self.vectors = vs
                self.embed_status = f"on ({EMBED_MODEL})"
            else:
                self.embed_status = "unavailable — BM25 only"

    def search(self, query: str, k: int = 6, rrf_k: int = 60, min_bm25: float = 0.0,
               max_per_doc: int = 2) -> list[Hit]:
        if not self.chunks:
            return []
        q_tokens = tokenize(query)
        bm = self.bm25.get_scores(q_tokens) if self.bm25 is not None else [0.0] * len(self.chunks)
        bm_rank = sorted(range(len(self.chunks)), key=lambda i: -bm[i])
        bm_rank = [i for i in bm_rank if bm[i] > min_bm25][: k * 3]

        em_rank: list[int] = []
        if self.vectors is not None:
            qv = embed([query])
            if qv and qv[0] is not None:
                sims = [_cos(qv[0], v) for v in self.vectors]
                em_rank = sorted(range(len(self.chunks)), key=lambda i: -sims[i])[: k * 3]

        fused: dict[int, Hit] = {}
        for name, ranking in (("bm25", bm_rank), ("embed", em_rank)):
            for r, i in enumerate(ranking):
                h = fused.get(i) or Hit(self.chunks[i], 0.0)
                h.score += 1.0 / (rrf_k + r + 1)
                h.found_by.append(name)
                fused[i] = h
        for i, h in fused.items():
            if "bm25" in h.found_by:
                ct = set(tokenize(h.chunk.text))
                h.bm25_terms = sorted(t for t in set(q_tokens) if t in ct)
        ranked = sorted(fused.values(), key=lambda h: -h.score)
        out: list[Hit] = []
        per_doc: dict[str, int] = {}
        seen: list[set[str]] = []
        for h in ranked:
            if per_doc.get(h.chunk.doc_id, 0) >= max_per_doc:
                continue
            toks = set(tokenize(h.chunk.text))
            if any(len(toks & s) / max(1, len(toks | s)) > 0.6 for s in seen):
                continue                      # near-duplicate of a hit already kept
            out.append(h); seen.append(toks)
            per_doc[h.chunk.doc_id] = per_doc.get(h.chunk.doc_id, 0) + 1
            if len(out) >= k:
                break
        return out
