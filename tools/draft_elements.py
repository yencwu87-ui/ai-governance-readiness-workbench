#!/usr/bin/env python3
"""WB-063/070 — draft requirement elements from the source instrument.

Why the elements needed drafting at all
---------------------------------------
For 165 of 195 controls the governed "requirement elements" are the control title with a prefix:
D1.3 reads "The organization must ensure that cap the agent's blast radius before build." That is
not a decomposition of a requirement. An element should say what the regulator is pinning down;
the control title is your shorthand for it. This inverts the direction.

Why it works by selection and not by quotation
----------------------------------------------
Four runs, four ways of losing every element:

  S4.2 run 1   the whole 7,152-word instrument went into one call; the model anchored on SAFR's
               identity requirement instead of its gateway section, then reported that the
               instrument did not oblige gateway interception at all
  S4.2 run 2   retrieval fixed that, and five of six elements were dropped as paraphrases
  M3.6 run 1   retrieval found the right passages, but fixed-width chunking handed them over
               starting "hms or features aligns with", and a model cannot copy from a fragment
  M3.6 run 2   passages snapped to sentence boundaries, and the model restated the control's own
               objective field into the quote slot instead — all five dropped

The last is the lesson. Asking a model to transcribe exactly is asking it to do the thing it is
structurally worst at, and each guard caught the failure without preventing it.

So it no longer transcribes. Candidate sentences are enumerated from the instrument and numbered;
the model returns *numbers*. An index cannot be paraphrased. The anchor is looked up
deterministically and is verbatim by construction rather than by check. A second call says what
each selected sentence obliges — interpretation, which models are good at, with the copying
already done.

Nothing here writes the governed path. Output goes to requirements/drafts/ for argument.

    python tools/draft_elements.py --control M3.6 --instrument instruments/mas-airg.txt --compare
    python tools/draft_elements.py --framework SAFR --instrument instruments/SAFR.txt
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DRAFTS = ROOT / "requirements" / "drafts"

#: Read as obligation language. Used to rank candidates when there are too many, never to exclude
#: them — a requirement can be written in the present indicative ("the FI maintains a register"),
#: and filtering those out would quietly narrow what the instrument is allowed to say.
_OBLIGATION = (" should", " shall", " must", "required to", "expected to", "is to be",
               "are to be", "needs to", "ought to")

# Element-level hardening. The draft tool is intentionally conservative: a source sentence may
# be selected, but no model-generated element reaches a draft until it survives these gates.
_MAX_ELEMENTS_PER_SENTENCE = 3
_ELEMENT_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into",
    "is", "it", "of", "on", "or", "that", "the", "their", "this", "to", "with", "within",
    "should", "shall", "must", "would", "could", "may", "might", "can", "fi", "ai",
}
_ELEMENT_FUNCTION_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or",
    "the", "to", "with", "within", "that", "this", "these", "those", "and", "of", "for",
}
_ELEMENT_ACTIONS = {
    "align", "apply", "approve", "assign", "assess", "audit", "challenge", "check", "complete",
    "conduct", "confirm", "control", "cover", "define", "demonstrate", "document", "ensure",
    "establish", "evaluate", "evidence", "examine", "implement", "maintain", "measure", "monitor",
    "name", "perform", "provide", "record", "report", "review", "run", "set", "show", "state",
    "test", "trace", "validate", "verify", "exist", "exists", "govern", "governed", "manage", "support",
    "applied", "documented", "approved", "defined", "established", "assigned", "recorded", "reported", "reviewed", "performed", "covered",
    "precedes", "precede", "contains", "contained",
}

def _tokenise_meaningful(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", _norm(text))
    return [t for t in toks if t not in _ELEMENT_STOPWORDS and len(t) > 2]


def clean_instrument_text(text: str) -> str:
    """Remove PDF running headers/footers and obvious footnote spill before sentencing.

    The source text is a PDF-to-text artefact, not a clean regulation. A running header such as
    "Proposed Guidelines on AI Risk Management | 25" is not an obligation, and footnote lines
    such as "29This includes..." must not be allowed to become requirement anchors."""
    lines = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            lines.append("")
            continue
        if re.fullmatch(r"Proposed Guidelines on AI Risk Management\s*\|\s*\d+", line, flags=re.I):
            continue
        if re.fullmatch(r"\d{1,2}(?:This|Such|For|As|See|The|It|Where|Examples?).*", line):
            continue
        # Header bleed can also occur when PDF extraction joins the header to the next line.
        line = re.sub(r"Proposed Guidelines on AI Risk Management\s*\|\s*\d+\s*", "", line, flags=re.I)
        lines.append(line)
    return "\n".join(lines)


def element_is_obligation(text: str) -> tuple[bool, str]:
    """Reject grammatical noise such as "of" / "and" before it reaches the draft."""
    t = " ".join((text or "").split()).strip()
    toks = re.findall(r"[a-z0-9-]+", t.lower())
    if len(toks) < 3:
        return False, "too_short_to_state_an_obligation"
    if all(tok in _ELEMENT_FUNCTION_WORDS for tok in toks):
        return False, "function_words_only"
    meaningful = _tokenise_meaningful(t)
    if len(meaningful) < 2:
        return False, "insufficient_meaningful_tokens"
    verbs = {v for v in meaningful if v in _ELEMENT_ACTIONS}
    has_modal = any(tok in {"should", "shall", "must", "required", "expected"} for tok in toks)
    if not verbs and not has_modal:
        return False, "no_action_or_modal_language"
    return True, ""


_ACTOR_MARKERS = {"fi", "institution", "organisation", "organization", "ai", "system", "model",
                  "validator", "reviewer", "developer", "developers", "owner", "board",
                  "committee", "person", "personnel", "function", "vendor"}


def _subject_markers(text: str, *, whole: bool = False) -> set[str]:
    """Return explicit actor markers from a clause.

    `whole=False` reads only the prefix before the first obligation verb/modal, which is the
    right scope for an element: the model writes one clean obligation, so its subject is at the
    front.

    `whole=True` scans the entire sentence and is the right scope for an *anchor*. WB-102 fixed
    an inversion here. A regulatory sentence routinely nests its real subject inside the clause —
    "An FI should ensure that the AI system is secure, well-governed..." — and prefix-only
    reading extracted {fi} and stopped at "should". The guard then rejected the faithful element
    ("the AI system should be secure") as unsupported while admitting the drifted one ("the FI
    should be well-governed"), which is the precise error it was written to catch, passed with a
    clean bill. Scanning the whole anchor stops the false rejection.

    What it still cannot do is decide which of several nested subjects a predicate attaches to —
    that needs a parser, not a token set. So where an anchor names more than one actor, the
    element is not dropped and is not silently kept: it is flagged `subject_ambiguous` for a
    human. An unprovable subject is reported, not guessed.
    """
    toks = re.findall(r"[a-z0-9]+", _norm(text))
    if whole:
        return {t for t in toks if t in _ACTOR_MARKERS}
    stop = {"should", "shall", "must", "will", "needs", "need", "is", "are", "can", "may",
            "required", "expected", "to", "perform", "conduct", "ensure", "establish",
            "define", "review", "validate", "test", "document", "record", "provide",
            "cover", "assess", "evaluate", "identify", "report", "maintain", "approve",
            "apply", "implement"}
    prefix=[]
    for tok in toks[:14]:
        if tok in stop:
            break
        prefix.append(tok)
    markers = {t for t in prefix if t in _ACTOR_MARKERS}
    return markers


def element_subject_match(element_text: str, anchor: str) -> tuple[bool, str]:
    """(ok, reason). `ok` is False only when the element's subject is absent from the anchor.

    A reason returned alongside ok=True is an advisory flag, not a rejection.
    """
    src = _subject_markers(anchor, whole=True)
    got = _subject_markers(element_text)
    if src and got and src.isdisjoint(got):
        return False, "obligated_subject_not_supported_by_anchor"
    if len(src) > 1 and len(got) == 1:
        # The anchor obliges more than one actor and the element picked one. Which one the
        # predicate belongs to is not decidable lexically, so a person decides.
        return True, "subject_ambiguous:" + "/".join(sorted(src))
    return True, ""


def element_anchor_match(element_text: str, anchor: str) -> tuple[bool, str, float]:
    """Require lexical provenance back to the element's own anchor.

    This is deliberately not a semantic similarity score. It is a provenance guard: the model may
    paraphrase, but the material nouns/verbs it used must still be recognisable in the sentence that
    supposedly supports the element."""
    et = set(_tokenise_meaningful(element_text))
    at = set(_tokenise_meaningful(anchor))
    if not et:
        return False, "no_meaningful_element_tokens", 0.0
    overlap = len(et & at) / len(et)
    # A single short word can match by accident. Require either two shared terms or >= 50% overlap.
    if len(et & at) < 2 and overlap < 0.5:
        return False, "element_tokens_not_supported_by_own_anchor", overlap
    return True, "", overlap


def anchor_is_clean(anchor: str) -> tuple[bool, str]:
    a = " ".join((anchor or "").split()).strip()
    if re.search(r"Proposed Guidelines on AI Risk Management\s*\|\s*\d+", a, re.I):
        return False, "running_header_in_anchor"
    if re.search(r"\b\d{1,2}(?:This|Such|For|As|See|The)\b", a):
        return False, "footnote_prefix_in_anchor"
    if not a or not re.match(r"^[A-Z0-9(]", a):
        return False, "anchor_is_sentence_fragment"
    return True, ""

SELECT_SYSTEM = """You select sentences. You do not write them.

You are given numbered sentences from a regulatory instrument, and one control that claims to
implement part of it. Return the numbers of the sentences that create an obligation the control
is accountable for.

Rules:
- Return numbers only. Never return sentence text. Never rewrite, summarise or combine sentences.
- Select a sentence only if it creates an obligation — something an institution must do, have, or
  be able to show. A sentence describing an option, an example or a rationale is not an
  obligation, however relevant it sounds.
- Select between two and eight. If fewer than two sentences create an obligation this control is
  accountable for, return fewer. An empty list is a valid and useful answer: it usually means the
  control was derived from descriptive text rather than from a requirement.
- Judge against the instrument, not the control title. The title is someone's shorthand and may
  claim more, or less, than the instrument obliges.

Respond with ONLY: {"picked":[3,11,14],"note":"one short line on anything notable, or empty"}"""

STATE_SYSTEM = """You state what ONE sentence obliges.

You are given a single sentence from a regulatory instrument. Write what it requires an
institution to do, have, or be able to show — in one sentence a tester could fail. Then say
whether the obligation is about something being defined, approved or documented ("design"), or
about something actually having happened for the real population in the period ("operation").

Rules:
- Stay inside the sentence you were given. Do not add obligations it does not create, do not
  continue into what the instrument says elsewhere, and do not import what you know of good
  practice.
- Prefer wording that can fail. "Maintain appropriate governance" cannot fail a test. "The board
  approves the AI risk appetite" can.
- If the sentence creates two genuinely distinct obligations, return two entries. Most sentences
  create one. If it creates none — it describes, explains or gives an example — return an empty
  list, which is a correct answer.

Respond with ONLY: {"elements":[{"text":"...","kind":"design"}]}"""

#: The selector is told two to eight. On the first real M3.6 run it returned 42 of 47, which is
#: acceptance rather than selection. Over-selection is reported rather than silently obeyed,
#: because a decomposition built from 42 sentences is the instrument re-typed, not a control's
#: requirement.
MAX_SELECTED = 8


# ---------------------------------------------------------------- text handling

def _norm(t: str) -> str:
    t = t or ""
    for bad, good in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
                      ("\u2013", "-"), ("\u2014", "-"), ("\u00a0", " ")):
        t = t.replace(bad, good)
    return re.sub(r"\s+", " ", t.lower()).strip()


def sentences(text: str, *, min_words: int = 6) -> list[str]:
    """Sentence split tolerant of PDF extraction artefacts and regulatory numbering."""
    t = clean_instrument_text(text)
    t = re.sub(r"\s+", " ", t or "")
    t = re.sub(r"\b(e\.g|i\.e|etc|no|fig|para|vs)\.\s", r"\1<DOT> ", t, flags=re.I)
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(])", t)
    out = []
    for p in parts:
        p = p.replace("<DOT>", ".").strip()
        if len(p.split()) >= min_words:
            out.append(p)
    return out


def candidates(text: str, control, *, top_chunks: int = 8, cap: int = 60) -> list[str]:
    """Sentences of the instrument that bear on this control, in document order.

    Retrieval is BM25 over the instrument's chunks — deterministic, no embedding model. Sentences
    are then taken from within those chunks, so nothing the model sees begins mid-word: the
    fixed-width chunk boundary is used for scoring and never shown.
    """
    from retriever import BM25Okapi
    from scanner import chunk_text

    chunks = [c for c in chunk_text(text) if c.strip()]
    if not chunks:
        return []
    query = f"{getattr(control, 'title', '')} {getattr(control, 'req', '')}".lower().split()
    if len(chunks) > top_chunks:
        index = BM25Okapi([c.lower().split() for c in chunks])
        scores = index.get_scores(query)
        keep = sorted(sorted(range(len(chunks)), key=lambda i: -scores[i])[:top_chunks])
        chunks = [chunks[i] for i in keep]

    seen, out = set(), []
    for c in chunks:
        got = sentences(c)
        # A fixed-width chunk starts and ends mid-word, so its first and last sentences are
        # fragments: "ws of the scope of the inventory." and "An FI should identify key AI risks
        # and set cl". Offering those as selectable candidates is how a truncated clause becomes
        # an anchor, so they are dropped unless they are whole.
        if got and not re.match(r"^[A-Z0-9(]", got[0]):
            got = got[1:]
        if got and not got[-1].rstrip().endswith((".", ";", ":")):
            got = got[:-1]
        for s in got:
            k = _norm(s)
            if k and k not in seen:
                seen.add(k)
                out.append(s)
    if len(out) > cap:
        ranked = sorted(range(len(out)),
                        key=lambda i: (not any(w in out[i].lower() for w in _OBLIGATION), i))
        keep_idx = set(ranked[:cap])
        out = [s for i, s in enumerate(out) if i in keep_idx]
    return out


def anchored_in(sentence: str, text: str) -> bool:
    return _norm(sentence) in _norm(text)


# ---------------------------------------------------------------- model calls

def _ask(system: str, user: str) -> dict:
    import assessor as A
    raw = A._ollama(system, user) if A.PROVIDER == "ollama" else A._anthropic(system, user, None)
    raw = (raw or "").replace("```json", "").replace("```", "").strip()
    if "{" not in raw or "}" not in raw:
        raise ValueError(f"no JSON object returned (got {raw[:120]!r})")
    return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])


def select(control, cands: list[str]) -> tuple[list[int], str, int]:
    """Pass 1 — which numbered sentences create an obligation. Returns (picked, note, invalid)."""
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(cands))
    user = f"""CONTROL claiming to implement part of this instrument:
  id:    {control.id}
  title: {control.title}

NUMBERED SENTENCES FROM THE INSTRUMENT:
{numbered}

Which of these create an obligation this control is accountable for? Numbers only."""
    out = _ask(SELECT_SYSTEM, user)
    picked, invalid = [], 0
    for n in out.get("picked") or []:
        try:
            i = int(n)
        except (TypeError, ValueError):
            invalid += 1
            continue
        if 1 <= i <= len(cands) and i not in picked:
            picked.append(i)
        else:
            invalid += 1
    return picked, str(out.get("note") or "").strip(), invalid


def state_one(sentence: str) -> list[dict]:
    """Pass 2 — what ONE sentence obliges.

    Batched, this call returned 37 obligations all stamped with a single index: given 42 numbered
    sentences it enumerated the instrument and ignored the numbering, so every element carried the
    same anchor. One sentence per call removes the index from the schema entirely, and an anchor
    that is never named cannot be misnamed.
    """
    from inference import TaskSignals, run_with_escalation

    def quality(raw: str) -> tuple[bool, str]:
        try:
            cleaned = raw.replace("```json", "").replace("```", "").strip()
            obj = json.loads(cleaned[cleaned.index("{"):cleaned.rindex("}") + 1])
            elems = obj.get("elements") or []
            if not isinstance(elems, list):
                return False, "elements_not_a_list"
            if not elems:
                return False, "no_element_returned"
            if len(elems) > _MAX_ELEMENTS_PER_SENTENCE:
                return False, "element_fanout_exceeds_guard"
            for item in elems:
                if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                    return False, "element_missing_text"
            return True, ""
        except Exception as exc:
            return False, f"invalid_json:{type(exc).__name__}"

    try:
        raw, _plan, _telemetry = run_with_escalation(
            role="elements",
            system=STATE_SYSTEM,
            user=f"SENTENCE:\n{sentence}\n\nWhat does it oblige?",
            signals=TaskSignals(role="elements", evidence_chars=len(sentence), element_count=1),
            validate=quality,
        )
    except Exception as exc:
        # A transport failure must not trigger a second expensive request. Empty/model-degraded
        # validation failures remain reportable through the legacy path for test compatibility.
        msg = str(exc).lower()
        if any(marker in msg for marker in ("ollama", "timed out", "cannot connect", "connection")):
            return []
        raw = _ask(STATE_SYSTEM, f"SENTENCE:\n{sentence}\n\nWhat does it oblige?") | {}
    if isinstance(raw, dict):
        out = raw
    else:
        try:
            out = json.loads(raw.replace("```json", "").replace("```", "").strip())
        except Exception:
            out = {}
    rows = []
    for e in out.get("elements") or []:
        if not isinstance(e, dict):
            continue
        body = " ".join(str(e.get("text") or "").split())
        if body:
            rows.append({"text": body,
                         "kind": str(e.get("kind") or "").strip().lower() or "unspecified"})
    return rows


# ---------------------------------------------------------------- drafting

def draft_one(control, text: str, verified: bool, provenance: str) -> dict:
    cands = candidates(text, control) if text else []
    row = {"control_id": control.id, "framework": control.lib, "title": control.title,
           "instrument_provenance": provenance, "instrument_verified": verified,
           "candidates_offered": len(cands), "selected": [], "elements": [], "dropped": [],
           "selection_note": "", "invalid_indices": 0, "selected_not_stated": [],
           "selected_count_raw": 0, "over_selected": False, "element_rejections": [],
           "element_overflow": [], "element_flags": [], "elements_by_sentence": {}}
    if not cands:
        row["dropped"].append({"reason": "no candidate sentences found in the instrument"})
        return row

    picked, note, invalid = select(control, cands)
    row["selection_note"], row["invalid_indices"] = note, invalid
    row["selected_count_raw"] = len(picked)
    row["over_selected"] = len(picked) > MAX_SELECTED
    if row["over_selected"]:
        picked = picked[:MAX_SELECTED]
    row["selected"] = [{"index": i, "sentence": cands[i - 1]} for i in picked]
    if not picked:
        row["dropped"].append({"reason": "no sentence was selected as creating an obligation this "
                                         "control is accountable for — often a sign the control "
                                         "was derived from descriptive text rather than a rule"})
        return row

    for i in picked:
        anchor = cands[i - 1]
        # Verbatim by construction — the anchor IS the candidate sentence at this index, and the
        # model is never asked to name or reproduce it.
        if verified and not anchored_in(anchor, text):
            row["dropped"].append({"reason": "internal: candidate sentence not found in the "
                                             "instrument", "text": anchor[:120]})
            continue
        try:
            stated = state_one(anchor)
        except Exception as exc:
            row["dropped"].append({"reason": f"stating the obligation failed "
                                             f"({type(exc).__name__})", "text": anchor[:120]})
            continue
        if not stated:
            row["selected_not_stated"].append(i)
            continue
        accepted_for_sentence = 0
        for e in stated:
            body = e["text"]
            ok, reason = element_is_obligation(body)
            if not ok:
                row["element_rejections"].append({"sentence_index": i, "text": body, "reason": reason})
                continue
            if verified:
                ok, reason, overlap = element_anchor_match(body, anchor)
                if not ok:
                    row["element_rejections"].append({"sentence_index": i, "text": body, "reason": reason, "anchor_overlap": round(overlap, 3)})
                    continue
                ok, reason = element_subject_match(body, anchor)
                if not ok:
                    row["element_rejections"].append({"sentence_index": i, "text": body, "reason": reason, "anchor_overlap": round(overlap, 3)})
                    continue
                subject_flag = reason if reason.startswith("subject_ambiguous") else ""
            else:
                overlap = None
                subject_flag = ""
            ok, reason = anchor_is_clean(anchor) if verified else (True, "")
            if not ok:
                row["element_rejections"].append({"sentence_index": i, "text": body, "reason": reason})
                continue
            if accepted_for_sentence >= _MAX_ELEMENTS_PER_SENTENCE:
                row["element_overflow"].append({"sentence_index": i, "text": body, "reason": "max_elements_per_sentence_exceeded"})
                continue
            row["elements"].append({
                "id": f"e{len(row['elements']) + 1}",
                "text": body,
                "kind": e["kind"],
                "anchor": anchor,
                "anchor_verified": bool(verified),
                "anchor_overlap": round(overlap, 3) if overlap is not None else None,
                "confidence": "known" if verified else "unchecked",
                "flags": [subject_flag] if subject_flag else [],
            })
            if subject_flag:
                row["element_flags"].append({"sentence_index": i, "text": body, "flag": subject_flag})
            accepted_for_sentence += 1
        row["elements_by_sentence"][str(i)] = accepted_for_sentence
    row["kinds"] = {k: sum(1 for e in row["elements"] if e["kind"] == k)
                    for k in ("design", "operation")}
    return row


def current_elements(control) -> list[str]:
    try:
        from governance.control_contract import requirement_context
        ctx = requirement_context(control.id, control.lib) or {}
        return [" ".join(str(e.get("text", "")).split()) for e in (ctx.get("elements") or [])]
    except Exception:
        return []


def render(row: dict, *, compare: bool = False, control=None) -> str:
    selected = len(row["selected"])
    offered = row["candidates_offered"]
    raw = row.get("selected_count_raw") or selected
    # WB-102: the headline used to divide the *capped* count by the offered count, so a selector
    # that accepted 15 of 18 sentences (83%) was reported as "8/18 selected (44%)" — the number
    # the footer was warning about was hidden by the number in the header. Report the selector's
    # own acceptance, and show the cap separately.
    rate = (raw / offered * 100) if offered else 0.0
    rejected = len(row.get("element_rejections") or [])
    overflow = len(row.get("element_overflow") or [])
    flagged = len(row.get("element_flags") or [])
    out = [f"{row['control_id']} — {row['title']}",
           f"  instrument: {row['instrument_provenance']}"
           + ("" if row["instrument_verified"] else "   [ADVISORY — not verified against a file]"),
           f"  sentences: selector accepted {raw}/{offered} ({rate:.0f}% acceptance)"
           + (f"; capped to {selected} for drafting" if raw != selected else ""),
           f"  elements: {len(row['elements'])} accepted; {rejected} rejected; "
           f"{overflow} overflow-flagged; {flagged} subject-flagged",
           f"  element integrity: {'FLAGGED' if (rejected or overflow or flagged) else 'PASS'}", ""]
    if row.get("element_rejections"):
        out += [f"  Element guard rejected {len(row['element_rejections'])} model-generated element(s) before promotion."]
        for r in row["element_rejections"][:8]:
            out.append(f"      sentence {r['sentence_index']}: {r['reason']} — {r['text'][:140]}")
        if len(row["element_rejections"]) > 8:
            out.append(f"      ... {len(row['element_rejections']) - 8} more element rejection(s)")
    if row.get("element_overflow"):
        out += [f"  Element fan-out guard flagged {len(row['element_overflow'])} element(s) beyond the {_MAX_ELEMENTS_PER_SENTENCE}/sentence cap."]
    if row.get("element_flags"):
        out += [f"  Subject guard could not prove which actor {len(row['element_flags'])} element(s) oblige. "
                f"Kept for human decision, not promoted on the guard's word."]
        for f_ in row["element_flags"][:5]:
            out.append(f"      sentence {f_['sentence_index']}: {f_['flag']} — {f_['text'][:140]}")
    for e in row["elements"]:
        mark = "  [subject unproven]" if e.get("flags") else ""
        out.append(f"  {e['id']}  [{e['kind']:9}] {e['text']}{mark}")
        out.append(f"      anchor: \"{e['anchor'][:170]}\"")
    if not row["elements"]:
        for d in row["dropped"]:
            out.append(f"  {d['reason']}")
    if row.get("over_selected"):
        out += ["", f"  Selection guard: the model returned {row['selected_count_raw']} candidate sentences "
                    f"from {row['candidates_offered']}. The tool capped the draft at {MAX_SELECTED}; "
                    f"Only the first\n  {MAX_SELECTED} were used. A decomposition built from that "
                    f"many sentences is the instrument\n  re-typed rather than this control's "
                    f"requirement, so treat what follows with suspicion."]
    if row["selected_not_stated"]:
        out += ["", f"  {len(row['selected_not_stated'])} selected sentence(s) produced no element "
                    f"— the second call stated no obligation for them."]
    if row["invalid_indices"]:
        out.append(f"  {row['invalid_indices']} returned index/indices were out of range, ignored.")
    k = row.get("kinds") or {}
    if row["elements"] and not k.get("operation"):
        out += ["", "  Every element is design-side. A requirement decomposed this way is satisfied "
                    "by a policy\n  with nothing operating behind it — check whether the instrument "
                    "really obliges nothing\n  about what happened."]
    if row["selection_note"]:
        out += ["", f"  Selector note: {row['selection_note']}"]
    if compare and control is not None:
        cur = current_elements(control)
        out += ["", f"  Currently in the governed contract ({len(cur)}):"]
        for c in cur:
            out.append(f"      {c[:170]}")
    return "\n".join(out)


# ---------------------------------------------------------------- inputs

def load_control(control_id: str, framework: str = ""):
    from playbook import load_controls
    books = sorted(glob.glob(str(ROOT / "data" / "*.xlsx")))
    if not books:
        sys.exit("no playbook workbook in data/")
    for lib, controls in load_controls(books[0]).items():
        if framework and framework.lower() not in lib.lower():
            continue
        for c in controls:
            if c.id == control_id:
                return c
    sys.exit(f"control {control_id} not found")


def controls_in(framework: str):
    from playbook import load_controls
    books = sorted(glob.glob(str(ROOT / "data" / "*.xlsx")))
    out = []
    for lib, controls in load_controls(books[0]).items():
        if framework.lower() in lib.lower():
            out.extend(controls)
    return out


def instrument_text(path: Path | None, control, max_chars: int) -> tuple[str, str, bool]:
    """Local file wins. A web search is advisory and never counts as verified: a snippet is not
    the instrument, and this tool cannot tell a regulator's page from a summary of it."""
    if path:
        if not path.exists():
            sys.exit(f"instrument not found: {path}")
        return path.read_text(errors="ignore")[:max_chars], f"file:{path.name}", True
    try:
        from ollama_search import search_web_checked
    except Exception:
        return "", "unavailable", False
    rows, err = search_web_checked(f"{control.lib} {control.title} regulatory requirement", 5)
    if err or not rows:
        return "", f"web-search-failed:{err or 'no results'}", False
    return ("\n\n".join(f"[{r['url']}] {r['snippet']}" for r in rows)[:max_chars],
            "web-search (advisory, unverified)", False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--control")
    ap.add_argument("--framework")
    ap.add_argument("--instrument", type=Path)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-chars", type=int, default=80000)
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    if not a.control and not a.framework:
        sys.exit("give --control or --framework")
    targets = [load_control(a.control)] if a.control else controls_in(a.framework)
    if a.limit:
        targets = targets[:a.limit]

    text, provenance, verified = instrument_text(a.instrument, targets[0], a.max_chars)
    if not verified:
        print(f"No instrument file supplied ({provenance}). Elements will be marked unchecked and "
              f"this draft is not promotable as authored interpretation.\n")

    rows = []
    for c in targets:
        try:
            row = draft_one(c, text, verified, provenance)
        except Exception as exc:
            print(f"{c.id}: FAILED ({type(exc).__name__}: {exc})")
            continue
        rows.append(row)
        print(render(row, compare=a.compare, control=c))
        print()

    if not rows:
        return 1

    import yaml
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    name = (a.control or a.framework or "draft").replace(" ", "-").replace("/", "-")
    out = a.out or DRAFTS / f"elements-{name}-{stamp}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump({
        "schema_version": "wb070.element-draft.2",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "instrument_provenance": provenance,
        "instrument_verified": verified,
        "needs_instrument": not verified,
        "authority": "draft",
        "method": "sentence selection by index, obligation stated in a second call; anchors are "
                  "verbatim by construction",
        "note": ("Proposed decomposition for second-line argument. Not governed. Promote into "
                 "requirements/<framework>.yaml only after the wording has been argued against "
                 "the instrument by a named person — the confidence becomes 'known' because a "
                 "person checked it, not because this tool matched a string."),
        "controls": {r["control_id"]: {k: v for k, v in r.items() if k != "control_id"}
                     for r in rows},
    }, sort_keys=False, allow_unicode=True, width=100))
    print(f"draft written: {out}")
    print("Nothing governed was changed. Argue with it, then promote what survives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
