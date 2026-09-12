"""Reason validation — one implementation for every write path.

    from reasons import reason_error, is_template, is_thin

Three places used to decide whether a reviewer's reason is real, and they disagreed:

  label.py._thin        len < 25 or the text is in PLACEHOLDERS
  decisions.py.record   empty, or len < 25, or the text is one of the decision words
  app.py                nothing at all — Lane A took "Note (optional)"

That was three dialects of the same rule, and the weakest one guarded the lane with the most
records in it. This module is the union of all three plus the rules none of them had.

Adoption, as at WB-030:
  app.py         uses reason_error on both the blind reading and the decision, with
                 rating / revised / previous supplied. Done.
  decisions.py   uses reason_error on every decision. Done.
  label.py       uses reason_error. Its own PLACEHOLDERS set and the length test inside
                 _thin are gone; _thin is kept as a name because --status calls it.
  halocline_adapters.py  uses reason_error on a component rationale and is_template on the
                 fields that are not reasons.

The deference rule is a heuristic and will not catch a determined reviewer. It is not meant to.
It catches the reflex — the reviewer who has just been shown a plausible machine output and
writes down that they found it plausible. Naming the element is the discipline; this only
refuses the most common way of skipping it.

The template rule is the same kind of rule, for the other end of the problem: text that was
never written at all. It exists because a component register shipped with REPLACE in every
field and passed every other check, which is the golden-set defect in a new lane.
"""
from __future__ import annotations

import re

MIN_CHARS = 25

# label.py's set
PLACEHOLDERS = {
    "none", "n/a", "na", "nil", "-", "ok", "fine", "good", "yes", "no", "noen",
    "sufficient", "insufficient", "as above", "same", "see above", "clear", "obvious",
}

# decisions.py's set, plus the Lane A ratings
DECISION_WORDS = {"accept", "amend", "reject", "partial", "full", "override", "agreed"}

# The rule neither lane has. Deferring to a machine is not a reason.
DEFERRAL = (
    "llm", "the model", "model says", "model is right", "ai says", "the ai",
    "challenger", "assessor", "has a point", "good point", "fair point",
    "makes sense", "convinced me", "i agree", "agree with", "as suggested",
    "as flagged", "it flagged", "it asked",
)
DEFERRAL_CEILING = 60   # a reason that mentions the model AND says nothing else

# Template text left unedited. Deliberately case-sensitive on the shouty markers, so
# "replaced the manual check" and "to do this properly" are not caught. The second branch
# catches <angle_bracket> field names of the kind shipped in a CSV or YAML template.
TEMPLATE_MARKERS = re.compile(r"\b(REPLACE|TBD|TODO|FIXME|XXX|PLACEHOLDER|LOREM)\b|<[a-z][a-z_]{2,}>")


def is_template(value: str) -> bool:
    """True when the text looks like unedited template scaffolding.

    For fields that are not reasons — a component name, a description, a title. Reasons get
    this same test inside reason_error.
    """
    return bool(TEMPLATE_MARKERS.search(value or ""))


def is_thin(reason: str) -> bool:
    """label.py's original predicate, preserved so the CLI keeps behaving as it did.

    Retained for compatibility only. Prefer reason_error — is_thin cannot see the rating, the
    deferral rule or the template rule, so a reason it passes may still be refused at the
    write path. Nothing in the repo should call this on a lane that also calls reason_error.
    """
    r = (reason or "").strip()
    return len(r) < MIN_CHARS or r.lower().rstrip(".") in PLACEHOLDERS


def reason_error(reason: str, *, rating: str | None = None, revised: bool = False,
                 previous: str | None = None) -> str | None:
    """Return an error string, or None if the reason is acceptable.

    rating    the sufficiency or decision word being recorded, so the reason cannot just repeat it
    revised   True when this reason accompanies a change made after seeing a model
    previous  the reason being superseded, so a changed rating cannot carry an unchanged reason
    """
    r = (reason or "").strip()
    low = r.lower().rstrip(".")

    if not r:
        return "A reason is required. Name the element satisfied, or the one the evidence does not show."
    if low in PLACEHOLDERS or low in DECISION_WORDS:
        return "That repeats the rating rather than giving a reason."
    if rating and low == str(rating).strip().lower():
        return "That repeats the rating rather than giving a reason."
    if TEMPLATE_MARKERS.search(r):
        return "That is template text. Write what you actually found."
    if len(r) < MIN_CHARS:
        return "Needs a real reason — name the element satisfied, or the one the evidence does not show."

    if any(t in low for t in DEFERRAL) and len(r) < DEFERRAL_CEILING:
        return ("That says the model persuaded you, not what persuaded you. "
                "Name the element the evidence satisfies, or the one it does not show.")

    if revised and previous and low == previous.strip().lower().rstrip("."):
        return "The rating has changed but the reason has not. Say what moved you."

    return None
