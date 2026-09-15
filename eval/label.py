"""Label the golden set. One case at a time, blind — the assessor is never run before you decide.

    cd repo && python eval/label.py            # label the next unlabelled case
    python eval/label.py --all                 # walk through every unlabelled case
    python eval/label.py --review S-06         # re-open a case you have already labelled
    python eval/label.py --status              # how many are done
    python eval/label.py --all --reveal        # blind label first, then see the assessor and reconsider
    python eval/label.py --review R-02 --challenge   # blind label first, then have it attacked

Each label records sufficiency, maturity, the one-line reason, who labelled it and when. Labels are
written back into eval/golden_set.jsonl. The rubric is eval/rubric.md — keep it open beside you.

Two aids to writing a real reason, neither of which weakens the blind protocol:

  Requirement elements. The control's own requirement text is broken into its constituent parts and
  shown beside the evidence. It is derived from the control, never from the case's evidence, so it is
  identical for every case sharing a control and cannot hint at the answer. Override the automatic
  split for any control by adding an entry to eval/req_elements.json:
      {"M2.2": ["a central register exists", "it covers owner, purpose, dependencies and risk tier",
                "it is kept current"]}

  --challenge. Your blind label is captured and saved FIRST, then a hostile reviewer (eval/challenge.py)
  is given your rating and your reason and asked to make the strongest case that you are wrong. It
  cannot rate and cannot agree — it only asks. Most of what it says will be noise; the value is the
  one that lands and the discipline of having to answer it. If it changes your mind, that is recorded
  as a revision, same as --reveal. Watch your revision rate: if a challenger is moving your labels
  often, it is anchoring you rather than sharpening you.

  --reveal. Your blind label is captured and saved FIRST. Only then is the assessor run and its gaps
  shown, and you are asked whether it changes your judgement. The blind label is never overwritten —
  score.py continues to score against it. A change is recorded separately as label_revision, and the
  fact that you were shown the assessor is recorded on the case either way. That record is the point:
  a judgement made after seeing the model is not the same evidence as one made cold, and the file
  should say which it was.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

from reasons import reason_error  # noqa: E402  — needs REPO on the path first

SET = HERE / "golden_set.jsonl"
ELEMENTS = HERE / "req_elements.json"
SUFF = {"1": "none", "2": "partial", "3": "full", "n": "none", "p": "partial", "f": "full"}


def load() -> list[dict]:
    return [json.loads(l) for l in SET.read_text().splitlines() if l.strip()]


def save(cases: list[dict]):
    with SET.open("w") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")


# ---------- requirement elements (derived from the control, never from the evidence) ----------

def _overrides() -> dict:
    if ELEMENTS.exists():
        try:
            return json.loads(ELEMENTS.read_text())
        except json.JSONDecodeError as e:
            print(f"  warning: {ELEMENTS.name} is not valid JSON ({e}) — using the automatic split")
    return {}


def req_elements(ctl: dict) -> list[str]:
    """Break a requirement into the parts a reviewer has to satisfy themselves about.

    A crude sentence/clause split, deliberately so — it is a prompt for your attention, not a control.
    Where the split reads badly, author the elements by hand in eval/req_elements.json."""
    hand = _overrides().get(ctl["id"])
    if hand:
        return [str(h) for h in hand]
    text = " ".join((ctl.get("req") or "").split())
    parts = []
    for sentence in re.split(r"(?<=[.;])\s+", text):
        for clause in re.split(r",\s+and\s+|,\s+(?=which\b|that\b)", sentence):
            clause = clause.strip(" ,.;")
            if len(clause) >= 12:
                parts.append(clause)
    return parts or ([text] if text else [])


def print_elements(ctl: dict, header: str = "REQUIREMENT ELEMENTS"):
    els = req_elements(ctl)
    if not els:
        return
    print(f"\n{header} (from the control text — decide each one from the evidence):")
    for i, e in enumerate(els, 1):
        print(f"  {i}. {e}")


# ---------- display ----------

def show(c: dict, i: int, n: int):
    ctl = c["control"]
    print("\n" + "=" * 78)
    print(f"CASE {c['case_id']}  ({i} of {n})   [{c['kind']}{'  ' + c['source'] if c.get('source') else ''}]")
    print("=" * 78)
    print(f"\nCONTROL {ctl['id']} — {ctl['title']}")
    print(f"REQUIREMENT: {ctl['req']}")
    print_elements(ctl)
    print("\n--- EVIDENCE " + "-" * 64)
    ev = c["evidence"]
    print(ev if len(ev) <= 2200 else ev[:2200] + f"\n… [{len(ev) - 2200} more characters]")
    print("-" * 78)


def _thin(reason: str) -> bool:
    """Kept as a name because --status calls it. The rule itself lives in reasons.py.

    This used to be a second dialect: a 25-character floor and its own placeholder set, with
    no notion of the rating being repeated, no deferral rule and no template rule. --status
    therefore reported the golden set as cleaner than any write path would have found it."""
    return bool(reason_error(reason))


def ask(c: dict, reviewer: str, prefix: str = "", previous: dict | None = None) -> dict | None:
    while True:
        s = input(f"\n{prefix}Sufficiency  [1] none  [2] partial  [3] full   (s=skip, q=quit): ").strip().lower()
        if s in ("q", "quit"):
            return None
        if s in ("s", "skip"):
            return {}
        if s in SUFF:
            suff = SUFF[s]
            break
        print("  enter 1, 2 or 3")
    cap = {"none": 1, "partial": 3, "full": 5}[suff]
    while True:
        m = input(f"{prefix}Maturity 1-{cap}  (1 ad hoc, 2 documented, 3 implemented, 4 measured, 5 optimised): ").strip()
        if m.isdigit() and 1 <= int(m) <= cap:
            mat = int(m)
            break
        print(f"  enter 1 to {cap} — sufficiency '{suff}' caps maturity at {cap}")

    print_elements(c["control"], "Which element decided it?")
    while True:
        reason = input(f"{prefix}One sentence: what evidence fact or missing element makes this {suff}? Do not write review instructions. ").strip()
        err = reason_error(reason, rating=suff, revised=bool(previous),
                           previous=(previous or {}).get("reason"))
        if not err:
            break
        print(f"  {err}")
    amb = input(f"{prefix}Ambiguous? (y/N): ").strip().lower().startswith("y")
    return {"sufficiency": suff, "maturity": mat, "reason": reason, "ambiguous": amb,
            "labelled_by": reviewer, "labelled_on": datetime.now(timezone.utc).isoformat(timespec="seconds")}


# ---------- reveal (runs only after the blind label is saved) ----------

def run_assessor(c: dict) -> dict | None:
    sys.path.insert(0, str(REPO))
    try:
        from pipeline import propose
    except Exception as e:
        print(f"  assessor unavailable ({e}) — staying blind for this case")
        return None
    try:
        return propose(SimpleNamespace(**c["control"]),
                       {"text": c["evidence"], "file_name": "", "auto": False, "sources": []})
    except Exception as e:
        print(f"  assessor call failed ({e}) — staying blind for this case")
        return None


def show_proposal(out: dict):
    print("\n" + "-" * 78)
    print(f"ASSESSOR PROPOSAL ({out.get('model', '?')}) — a proposal, not a decision")
    print(f"  sufficiency: {out.get('sufficiency')}   maturity: {out.get('proposedMaturity')}")
    if out.get("excerpt"):
        print(f"  excerpt:     {out['excerpt'][:200]}")
    for g in out.get("gaps") or []:
        print(f"  gap:         {g}")
    if out.get("rationale"):
        print(f"  rationale:   {out['rationale'][:300]}")
    for f in out.get("flags") or []:
        print(f"  FLAG:        {f}")
    if out.get("reviewerPrompt"):
        print(f"  it asks you: {out['reviewerPrompt'][:200]}")
    print("-" * 78)
    print("  These gaps are unverified model output. A gap that sounds plausible is not thereby real —")
    print("  check each one against the requirement and the evidence before it changes your mind.")


def run_challenger(c: dict, blind: dict) -> dict | None:
    sys.path.insert(0, str(REPO))
    try:
        from challenge import challenge as _challenge
    except Exception as e:
        print(f"  challenger unavailable ({e})")
        return None
    try:
        return _challenge(c["control"], c["evidence"], blind)
    except Exception as e:
        print(f"  challenger failed ({e})")
        return None


def show_challenge(out: dict):
    print("\n" + "-" * 78)
    print(f"CHALLENGE ({out.get('model', '?')}) — questions only, it cannot rate and cannot agree")
    if out.get("sharpest"):
        print(f"  ANSWER FIRST: {out['sharpest']}")
    for q in out.get("challenges") or []:
        print(f"  - {q}")
    for u in out.get("unaddressed") or []:
        print(f"  requirement element your reason never mentions: {u}")
    print("-" * 78)
    print("  A challenger attacks sound labels too. Hold your label unless it named something you")
    print("  cannot answer from the requirement and the evidence.")


def reveal(c: dict, reviewer: str, use_assessor: bool, use_challenger: bool) -> bool:
    """Show the assessor after the blind label is saved. Returns True if anything was written."""
    blind = c["label"]
    record = {"shown_on": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "shown_to": reviewer, "changed": False}
    shown = False

    if use_assessor:
        out = run_assessor(c)
        if out:
            show_proposal(out)
            shown = True
            record.update({"model": out.get("model"), "assessor_sufficiency": out.get("sufficiency"),
                           "assessor_maturity": out.get("proposedMaturity"),
                           "assessor_gaps": out.get("gaps") or [],
                           "agreed_with_blind": out.get("sufficiency") == blind.get("sufficiency")})

    if use_challenger:
        ch = run_challenger(c, blind)
        if ch:
            show_challenge(ch)
            shown = True
            record.update({"challenger_model": ch.get("model"),
                           "challenges": ch.get("challenges") or [],
                           "sharpest": ch.get("sharpest", ""),
                           "unaddressed": ch.get("unaddressed") or []})

    if not shown:
        return False
    ans = input("\nDoes this change your judgement? (y/N): ").strip().lower()
    if ans.startswith("y"):
        print("  the blind label is kept and still scored — this is recorded separately as a revision")
        rev = ask(c, reviewer, prefix="revised ", previous=blind)
        if rev:
            rev["revised_after_assessor"] = bool(use_assessor)
            rev["revised_after_challenge"] = bool(use_challenger)
            rev["assessor_model"] = record.get("model") or record.get("challenger_model")
            rev["supersedes"] = {k: blind.get(k) for k in ("sufficiency", "maturity", "reason")}
            c["label_revision"] = rev
            record["changed"] = True
    c["assessor_shown"] = record
    return True


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--review", default=None, metavar="CASE_ID")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reviewer", default=os.environ.get("REVIEWER", ""))
    ap.add_argument("--reveal", action="store_true",
                    help="after the blind label is saved, run the assessor and offer a recorded revision")
    ap.add_argument("--challenge", action="store_true",
                    help="after the blind label is saved, have a hostile reviewer attack it")
    a = ap.parse_args()

    if not SET.exists():
        print("no golden_set.jsonl — run: python eval/build_set.py")
        return 1
    cases = load()
    done = [c for c in cases if c.get("label")]
    if a.status:
        print(f"{len(done)} of {len(cases)} labelled")
        for c in cases:
            l = c.get("label") or {}
            marks = ("AMBIGUOUS " if l.get("ambiguous") else "") + \
                    ("REVISED " if c.get("label_revision") else "") + \
                    ("SEEN " if c.get("assessor_shown") else "") + \
                    ("CHALLENGED " if (c.get("assessor_shown") or {}).get("challenges") else "")
            print(f"  {c['case_id']:6} {c['control']['id']:6} {(l.get('sufficiency') or '—'):8} "
                  f"{str(l.get('maturity') or '—'):3} {marks}{l.get('reason','')[:60]}")
        thin = [c['case_id'] for c in cases if (c.get('label') or {}).get('reason') and _thin(c['label']['reason'])]
        if thin:
            print(f"\n{len(thin)} case(s) still carry a placeholder or very short reason: {', '.join(thin)}")
            print("re-open one with: python eval/label.py --review CASE_ID")
        return 0

    reviewer = a.reviewer or input("Your name (recorded on every label): ").strip()
    if not reviewer:
        print("a label needs an attributable reviewer")
        return 1

    todo = [c for c in cases if c["case_id"] == a.review] if a.review else [c for c in cases if not c.get("label")]
    if not todo:
        print("nothing to label. python eval/label.py --status")
        return 0
    if not a.all and not a.review:
        todo = todo[:1]

    print("\nRubric: eval/rubric.md — label from the evidence alone, for this control alone.")
    if a.reveal:
        print("--reveal is on: you label blind first, then see the assessor and may record a revision.")
    if a.challenge:
        print("--challenge is on: you label blind first, then your label is attacked. It asks; you decide.")
    for i, c in enumerate(todo, 1):
        show(c, i, len(todo))
        lab = ask(c, reviewer)
        if lab is None:
            break
        if lab:
            c["label"] = lab
            save(cases)
            print(f"  recorded: {lab['sufficiency']} / {lab['maturity']}")
            if (a.reveal or a.challenge) and reveal(c, reviewer, a.reveal, a.challenge):
                save(cases)
    n = len([c for c in load() if c.get("label")])
    print(f"\n{n} of {len(cases)} labelled." + ("  Ready to score: python eval/score.py" if n == len(cases) else "  Continue: python eval/label.py --all"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
