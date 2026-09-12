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

Gating (WB-0xx): the fused RRF score is 1/(rrf_k + rank) — a function of rank alone, so the
top hit scores the same whether the corpus is full of relevant documents or none are. It
cannot express "nothing here is relevant", and neither can raw BM25, whose scale moves with
corpus size and query length (measured +0.86 correlation between control query length and top
score, which made a single absolute threshold a different standard per control library).
Cosine similarity is the only bounded, corpus- and length-independent quantity available, so
it is now retained on each Hit and can gate results via min_cos.
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

try:
    from rank_bm25 import BM25Okapi  # type: ignore
except ImportError:
    class BM25Okapi:
        """Small deterministic Okapi BM25 fallback for offline/bootstrapping environments."""
        def __init__(self, corpus):
            self.corpus = corpus
            self.k1 = 1.5
            self.b = 0.75
            self.n = len(corpus)
            self.avgdl = (sum(len(x) for x in corpus) / self.n) if self.n else 0.0
            self.df = {}
            for doc in corpus:
                for term in set(doc):
                    self.df[term] = self.df.get(term, 0) + 1
            self.idf = {t: math.log(1 + (self.n - df + 0.5) / (df + 0.5)) for t, df in self.df.items()}

        def get_scores(self, query_tokens):
            q = list(query_tokens or [])
            scores = []
            for doc in self.corpus:
                dl = len(doc)
                counts = {}
                for term in doc:
                    counts[term] = counts.get(term, 0) + 1
                score = 0.0
                for term in q:
                    f = counts.get(term, 0)
                    if not f:
                        continue
                    denom = f + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1.0))
                    score += self.idf.get(term, 0.0) * (f * (self.k1 + 1)) / denom
                scores.append(score)
            return scores

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("WB_EMBED_MODEL", "nomic-embed-text")
CACHE = Path(__file__).parent / ".cache" / "embeddings.jsonl"

# Off by default: no value has been shown to work across all five control libraries.
# Derive one with eval/cos_sweep.py before enabling.
MIN_COS = 0.0

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
    cos: float | None = None    # cosine similarity to the query, None if embeddings are off
    bm25_score: float = 0.0     # raw BM25, for diagnostics only — do not threshold on it


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
# Loaded once per process. Previously every embed() call re-read the whole JSONL from disk,
# so a scan of 195 controls re-read the entire vector cache 195 times.
_CACHE: dict[str, list[float]] | None = None


def _load_cache() -> dict[str, list[float]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    c: dict[str, list[float]] = {}
    if CACHE.exists():
        with CACHE.open(encoding="utf-8") as f:
            for l in f:
                try:
                    r = json.loads(l); c[r["k"]] = r["v"]
                except Exception:
                    pass
    _CACHE = c
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
                    k = _key(texts[i], model)
                    cache[k] = v            # keep the in-memory cache in step with the file
                    f.write(json.dumps({"k": k, "v": v}) + "\n")
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
               max_per_doc: int = 2, min_cos: float = MIN_COS) -> list[Hit]:
        """Fused search.

        min_cos gates on cosine similarity to the query — bounded 0-1 and independent of
        corpus size and query length, so one value means the same thing for a 47-term MAS
        control and an 8-term NIST one. It is the only gate here that can assert "no
        relevant evidence exists". Ignored when embeddings are unavailable, because a
        BM25-only run has no cosine to gate on: check embed_status before relying on it.

        min_bm25 is retained for compatibility but should stay 0.0. BM25 scale moves with
        corpus size and query length, so any non-zero value is a different standard per
        control library — measured at min_score=100 on a 2,697-chunk corpus it kept 33/38
        ISO controls and 1/34 MGF Agentic ones from the same folder.
        """
        if not self.chunks:
            return []
        q_tokens = tokenize(query)
        bm = self.bm25.get_scores(q_tokens) if self.bm25 is not None else [0.0] * len(self.chunks)
        bm_rank = sorted(range(len(self.chunks)), key=lambda i: -bm[i])
        bm_rank = [i for i in bm_rank if bm[i] > min_bm25][: k * 3]

        em_rank: list[int] = []
        sims: list[float] | None = None
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
            h.bm25_score = float(bm[i])
            if sims is not None:
                h.cos = float(sims[i])
            if "bm25" in h.found_by:
                ct = set(tokenize(h.chunk.text))
                h.bm25_terms = sorted(t for t in set(q_tokens) if t in ct)

        # cosine gate — only meaningful when embeddings actually ran
        if sims is not None and min_cos > 0:
            fused = {i: h for i, h in fused.items() if (h.cos or 0.0) >= min_cos}

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
