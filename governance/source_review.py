"""Session-safe review helper for uploaded governance instruments.

The uploaded document is advisory review context only. It never mutates the authoritative
control contract and is never treated as organisational evidence.
"""
from __future__ import annotations
from pathlib import Path
import re


def extract_text(data: bytes, name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages)
    if ext in {".docx", ".doc"}:
        from docx import Document
        import io
        doc = Document(io.BytesIO(data))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return data.decode("utf-8", errors="replace")


def _terms(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", text.lower())
    stop = {"organisation","organization","control","ensure","should","must","risk","management","system","systems","the","and","for","that","with","from","this","into","where","their","agent","use","using"}
    seen=[]
    for w in words:
        if w in stop or w in seen: continue
        seen.append(w)
    return seen[:30]


def best_excerpts(source_text: str, control, limit: int = 5, window: int = 900) -> list[dict]:
    paras=[p.strip() for p in re.split(r"\n\s*\n", source_text or "") if p.strip()]
    query=" ".join([getattr(control,"title","") or "", getattr(control,"req","") or ""])
    terms=_terms(query)
    scored=[]
    for idx,p in enumerate(paras):
        low=p.lower()
        score=sum(1 for t in terms if t in low)
        # Strong boost for explicit control IDs / distinctive title phrases.
        cid=str(getattr(control,"id","")).lower()
        if cid and cid in low: score += 12
        title_words=_terms(getattr(control,"title","") or "")[:8]
        score += 2*sum(1 for t in title_words if t in low)
        if score:
            scored.append((score,idx,p))
    scored.sort(key=lambda x:(x[0],-x[1]), reverse=True)
    out=[]
    for score,idx,p in scored[:limit]:
        text=p if len(p)<=window else p[:window].rstrip()+"…"
        out.append({"score":score,"paragraph":idx+1,"excerpt":text})
    return out
