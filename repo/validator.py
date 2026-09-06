"""Validator. Runs AFTER the judge, mostly deterministic. Any failure downgrades the proposal
to needs_review and the reviewer sees why. The validator never upgrades a rating.

Checks
  V1 cite_exists        every cited excerpt appears verbatim in the ORIGINAL chunk text
  V2 rating_vs_gaps     'full' with non-empty gaps, or 'none' with cites and no gaps, is inconsistent
  V3 cites_required     'full' or 'partial' must cite at least one excerpt
  V4 expected_output    step-specific rule derived from the expected-output text (see RULES)
  V5 cross_step         a step cannot be 'full' if a prerequisite step's recorded decision is
                        missing or 'reject' (PREREQS)
  V6 injection          retrieved chunks contain instruction-like text aimed at the model
  V7 gate (optional)    second LLM pass with a different prompt: does the evidence for the
                        play's steps meet the exit gate — yes/no + reasons
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from retriever import Hit

# Expected-output keyword -> (regex the cited text must satisfy, human reason)
RULES: list[tuple[str, str, str]] = [
    ("score",      r"\b\d+(\.\d+)?\b|\b(low|medium|high|critical)\b", "expected a score or tier but cites contain no number or tier"),
    ("rationale",  r"\b(because|rationale|basis|due to|given that)\b",  "expected a rationale but cites contain no reasoning language"),
    ("sign",       r"\b(signed|approved by|approver|signature|sign-off)\b", "expected a signed/approved artefact but cites show no approval"),
    ("approval",   r"\b(approved|approval|approver|sign-off|signed)\b",   "expected an approval but cites show no approval"),
    ("minutes",    r"\b(minutes|meeting|attendees|decision)\b",            "expected minutes but cites show no meeting record"),
    ("log",        r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",     "expected a log but cites carry no dates"),
    ("dashboard",  r"\b(threshold|drift|metric|alert)\b",                  "expected monitoring output but cites show no metric/threshold"),
    ("report",     r"\b(finding|result|conclusion|summary)\b",             "expected a report but cites show no findings"),
    ("register",   r"\b(id|entry|registered|inventory|owner)\b",           "expected a register entry but cites show no entry fields"),
    ("inventory",  r"\b(id|entry|registered|inventory|owner)\b",           "expected an inventory entry but cites show no entry fields"),
    ("decision",   r"\b(approved|rejected|decided|decision|go|no-go)\b",   "expected a decision but cites record none"),
]

# step -> steps that must be decided (and not rejected) first. Extend as the plays evolve.
PREREQS: dict[str, list[str]] = {
    "P1.2": ["P1.1"], "P1.3": ["P1.2"], "P1.4": ["P1.3"],
    "P2.1": ["P1.4"],
}

INJECTION = re.compile(
    r"(ignore (all|any|previous|prior) instructions|you are (now|an?) |as an ai|system prompt|"
    r"mark (this|the) step|rate (this|the) step|sufficiency\s*[:=]\s*[\"']?full|respond with|"
    r"output the following|assistant:|<\s*/?\s*(system|evidence|excerpt))", re.I)


@dataclass
class Finding:
    check: str
    ok: bool
    detail: str = ""


@dataclass
class Verdict:
    status: str                      # "ok" | "needs_review"
    findings: list[Finding] = field(default_factory=list)
    downgraded_to: str | None = None

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if not f.ok]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def validate(proposal: dict, hits: list[Hit], expected_output: str,
             step_id: str, prior_decisions: dict[str, dict],
             gate_check: Callable[[], tuple[bool, str]] | None = None) -> Verdict:
    f: list[Finding] = []
    suff = proposal.get("sufficiency", "none")
    cites = proposal.get("cited_excerpts", []) or []
    gaps = [g for g in (proposal.get("gaps") or []) if str(g).strip()]
    chunks = {h.chunk.id: h.chunk.text for h in hits}

    # V1
    bad = []
    for c in cites:
        txt, cid = _norm(c.get("text", "")), c.get("chunk_id", "")
        pool = [chunks[cid]] if cid in chunks else list(chunks.values())
        if not txt or not any(txt in _norm(p) for p in pool):
            bad.append(cid or "?")
    f.append(Finding("V1 cite_exists", not bad,
                     "" if not bad else f"cited text not found verbatim in evidence: {', '.join(bad)}"))

    # V2
    v2_ok = not (suff == "full" and gaps) and not (suff == "none" and cites and not gaps)
    f.append(Finding("V2 rating_vs_gaps", v2_ok,
                     "" if v2_ok else f"sufficiency '{suff}' inconsistent with {len(gaps)} gap(s) / {len(cites)} cite(s)"))

    # V3
    v3_ok = suff == "none" or bool(cites)
    f.append(Finding("V3 cites_required", v3_ok, "" if v3_ok else f"'{suff}' proposed with no cited excerpt"))

    # V4
    if suff in ("full", "partial") and cites:
        joined = " ".join(c.get("text", "") for c in cites)
        exp = (expected_output or "").lower()
        for kw, rx, why in RULES:
            if kw in exp and not re.search(rx, joined, re.I):
                f.append(Finding("V4 expected_output", False, why))
                break
        else:
            f.append(Finding("V4 expected_output", True))
    else:
        f.append(Finding("V4 expected_output", True, "skipped"))

    # V5
    missing = [p for p in PREREQS.get(step_id, [])
               if p not in prior_decisions or prior_decisions[p].get("decision") == "reject"]
    v5_ok = not (suff == "full" and missing)
    f.append(Finding("V5 cross_step", v5_ok, "" if v5_ok else f"prerequisite step(s) undecided or rejected: {', '.join(missing)}"))

    # V6
    inj = [h.chunk.id for h in hits if INJECTION.search(h.chunk.text)]
    f.append(Finding("V6 injection", not inj, "" if not inj else f"instruction-like text in evidence: {', '.join(inj)}"))

    # V7
    if gate_check is not None:
        try:
            ok, why = gate_check()
            f.append(Finding("V7 gate", ok, why))
        except Exception as e:  # gate check failing to run is itself a finding
            f.append(Finding("V7 gate", False, f"gate check did not run: {e}"))

    fails = [x for x in f if not x.ok]
    if not fails:
        return Verdict("ok", f)
    down = "partial" if suff == "full" else ("none" if suff == "partial" else None)
    return Verdict("needs_review", f, downgraded_to=down)


GATE_PROMPT = """You are checking an exit gate, not a step. Answer only from the excerpts.
Exit gate: {exit_gate}
Steps and their recorded sufficiency: {steps}
<evidence>
{evidence}
</evidence>
Does the evidence, taken together, meet the exit gate? Reply as JSON: {{"meets": true|false, "reasons": ["..."]}}"""


def make_gate_check(exit_gate: str, steps_summary: str, hits: list[Hit],
                    llm: Callable[[str], str]) -> Callable[[], tuple[bool, str]]:
    """Builds the V7 closure. Uses a *different* prompt from the step judge on purpose."""
    import json
    from judge import _scrub

    def run() -> tuple[bool, str]:
        ev = "\n\n".join(f"<excerpt id=\"{h.chunk.id}\">\n{_scrub(h.chunk.text)}\n</excerpt>" for h in hits)
        raw = llm(GATE_PROMPT.format(exit_gate=exit_gate, steps=steps_summary, evidence=ev))
        m = re.search(r"\{.*\}", raw, re.S)
        obj = json.loads(m.group(0) if m else raw)
        return bool(obj.get("meets")), "; ".join(map(str, obj.get("reasons", [])))[:400]
    return run
