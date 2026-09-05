"""Evidence-sufficiency assessor. Proposes; never decides.

Provider is chosen by env var ASSESSOR_PROVIDER: "ollama" (default) or "anthropic".
  Ollama:    OLLAMA_MODEL (default llama3.1:8b), OLLAMA_URL (default http://localhost:11434)
  Anthropic: ASSESSOR_MODEL (default claude-sonnet-4-6), ANTHROPIC_API_KEY
"""
from __future__ import annotations

import base64
import io
import json
import os

PROVIDER = os.environ.get("ASSESSOR_PROVIDER", "ollama").lower()
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
ANTHROPIC_MODEL = os.environ.get("ASSESSOR_MODEL", "claude-sonnet-4-6")

SYSTEM = """You are an AI-governance assessment assistant supporting a second-line-of-defence reviewer.
You read evidence an organisation has supplied against one control and give a cautious, auditable opinion on how far that evidence supports the control.
You never declare compliance; you rate evidence sufficiency.
Rules:
- If the control requires a running or operational artefact (logs, monitoring output, test results, inventory records) and only a policy or intent statement is supplied, sufficiency is at most "partial".
- If the evidence is unrelated to the control, sufficiency is "none".
- Quote the excerpt verbatim from the evidence; never invent one.
- Maturity: 1 ad hoc, 2 documented, 3 implemented, 4 measured, 5 optimised. Rate only what the evidence shows.
Work in this order: first find the most relevant verbatim excerpt, then list what the requirement needs that the evidence does not show, then write the rationale, and only then decide sufficiency and maturity. The rating must follow from the gaps: if any gap remains, sufficiency cannot be "full".
Respond with ONLY a JSON object, no prose, no markdown fences, with exactly these keys in this order:
{"excerpt": "most relevant verbatim phrase from the evidence, or empty string", "gaps": ["specific item the requirement needs that the evidence does not show"], "rationale": "two sentences max", "sufficiency": "none" | "partial" | "full", "proposedMaturity": 1-5, "reviewerPrompt": "one question the human reviewer should ask before accepting"}"""


def model_name() -> str:
    return f"ollama/{OLLAMA_MODEL}" if PROVIDER == "ollama" else ANTHROPIC_MODEL


def pdf_text(pdf_bytes: bytes, limit: int = 30000) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    return text[:limit]


def _prompt(control, evidence_text: str, attachment_note: str) -> str:
    return f"""Library: {control.lib}
Control ID: {control.id}
Control: {control.title}
Requirement: {control.req}
Control owner (role): {control.owner}
{('Cross-mapped to: ' + control.maps) if control.maps else ''}

Evidence supplied{attachment_note}:
{evidence_text or '(no text notes)'}"""


def _norm(t: str) -> str:
    return " ".join(t.lower().replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"').split())


def _validate(out: dict, evidence_text: str) -> dict:
    """Deterministic checks applied after the model. Can only downgrade, never upgrade."""
    flags = []
    ex = out.get("excerpt", "")
    if ex and _norm(ex) not in _norm(evidence_text):
        flags.append("Excerpt not found verbatim in the evidence — treat the quote as unreliable")
        out["excerpt"] = ""
        if out["sufficiency"] == "full":
            out["sufficiency"] = "partial"
    if out["gaps"] and out["sufficiency"] == "full":
        flags.append("Model rated full while listing gaps — downgraded to partial")
        out["sufficiency"] = "partial"
    if out["sufficiency"] == "none" and out["proposedMaturity"] > 1:
        flags.append("Maturity capped at 1 because sufficiency is none")
        out["proposedMaturity"] = 1
    if out["sufficiency"] == "partial" and out["proposedMaturity"] > 3:
        flags.append("Maturity capped at 3 because sufficiency is partial")
        out["proposedMaturity"] = 3
    out["flags"] = flags
    return out


def _parse(text: str) -> dict:
    text = text.replace("```json", "").replace("```", "").strip()
    text = text[text.index("{"): text.rindex("}") + 1]
    out = json.loads(text)
    out["sufficiency"] = out.get("sufficiency") if out.get("sufficiency") in ("none", "partial", "full") else "none"
    try:
        out["proposedMaturity"] = int(min(5, max(1, int(out.get("proposedMaturity", 1)))))
    except (TypeError, ValueError):
        out["proposedMaturity"] = 1
    gaps = out.get("gaps") or []
    out["gaps"] = [str(g) for g in (gaps if isinstance(gaps, list) else [gaps])]
    out["excerpt"] = str(out.get("excerpt") or "")
    out["model"] = model_name()
    return out


def _ollama(system: str, user: str) -> str:
    import requests
    r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=300, json={
        "model": OLLAMA_MODEL, "stream": False, "format": "json",
        "options": {"temperature": 0.1, "num_ctx": 8192},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    })
    r.raise_for_status()
    return r.json()["message"]["content"]


def _anthropic(system: str, user: str, pdf_bytes: bytes | None) -> str:
    import anthropic
    content = []
    if pdf_bytes:
        content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                       "data": base64.b64encode(pdf_bytes).decode()}})
    content.append({"type": "text", "text": user})
    msg = anthropic.Anthropic().messages.create(model=ANTHROPIC_MODEL, max_tokens=1000, system=system,
                                                messages=[{"role": "user", "content": content}])
    return "".join(b.text for b in msg.content if b.type == "text")


def assess(control, evidence_text: str, pdf_bytes: bytes | None = None, pdf_name: str = "") -> dict:
    if PROVIDER == "ollama":
        if pdf_bytes:
            evidence_text = (evidence_text + "\n\n" if evidence_text else "") + f"[{pdf_name}]\n" + pdf_text(pdf_bytes)
        raw = _ollama(SYSTEM, _prompt(control, evidence_text, ""))
    else:
        raw = _anthropic(SYSTEM, _prompt(control, evidence_text, f" (see attached PDF {pdf_name})" if pdf_bytes else ""), pdf_bytes)
        if pdf_bytes:  # so the excerpt check can see the PDF text too
            evidence_text = (evidence_text + "\n" if evidence_text else "") + pdf_text(pdf_bytes)
    return _validate(_parse(raw), evidence_text)
