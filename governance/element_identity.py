"""WB-104 — element identity that survives a contract revision.

The problem this exists for
---------------------------
`e1`, `e2`, `e14` are ordinals. `draft_one` assigns them with `f"e{len(elements) + 1}"`, so an
element id records one thing: the order it happened to come out of the drafter. Nothing binds
`e5` to any obligation.

That would be harmless if the id stayed inside one version. It does not. Element ids are the
join key for the reviewer's element verdicts in `compare.py`, the challenger's
`requirement_pointer.element_id`, `governance/step_decisions.jsonl`, the eval corpus a/b/c
labels, `M3.6_element_decisions.yaml`, and `element_testing.yaml`. Every one of those stores a
judgement against a number whose meaning is positional.

The strain is already visible in the previous M3.6 contract, which ran
`e1, e2, e3, e3b, e4, e4b, e5, e5d, e5b`. Those suffix letters are what happens when a scheme
with no room for insertion has to take an insertion: someone needed a new obligation between
`e3` and `e4` and there was no number available, so the id grew a letter. `e5d` sorts before
`e5b`. That is not a naming quirk, it is the identifier telling you it cannot carry the load.

The cost was paid in full at the 10 → 14 revision. Ten elements carried real per-document
labels; not one could be carried across, and `elements.yaml` records the reason as "the prior
labels are not copied". They could not be copied because there was no way to ask whether `e3`
in the old contract and `e3` in the new one were the same obligation. The ids matched and the
requirements did not.

What this module does
---------------------
It gives every element two handles derived from its own text, so identity travels with meaning
rather than with position:

  uid    `el-<10 hex>` over the normalised text. Same obligation, same uid, in any contract, in
         any order. Reword the obligation and the uid changes — which is correct, and which is
         exactly the event that should invalidate a stored label rather than silently inherit
         one.

  slug   a readable handle like `independent-validation-before-deployment`. `e7` tells a person
         nothing; the slug is what a reviewer can hold in their head and what a disagreement can
         be discussed in.

`diff_contracts` then answers the question that was unanswerable: given an old contract with
labels and a new one without, which labels carry? Exact uid matches carry automatically. Near
matches are *proposed* with their similarity and never applied — a reworded obligation may or
may not be the same obligation and that is a human call, the same standing rule as everywhere
else here. Everything else is reported as new or retired.

This module is additive. It does not repoint any existing consumer, and `e1..e14` remain the
display ordinals. Migrating the join key is a separate decision with its own blast radius.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

SCHEMA = "wb104.element-identity.1"

#: Proposed as a possible carry-over. Never applied without a person.
NEAR_MATCH = 0.62

_STOP = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with", "by", "from",
         "its", "their", "this", "that", "these", "those", "is", "are", "be", "been", "as",
         "at", "any", "all", "where", "which", "such", "must", "should", "shall", "will"}

#: Words that carry the obligation and belong in a readable handle, roughly in the order a
#: person would reach for them when naming the requirement.
_SALIENT_FIRST = ("validation", "evaluation", "testing", "approval", "review", "monitoring",
                  "documentation", "independence", "independent", "fairness", "explainability",
                  "robustness", "security", "deployment", "revalidation", "residual",
                  "threshold", "materiality", "proportionate", "accountable", "record")


def normalise(text: str) -> str:
    """Canonical form for identity. Case, punctuation and whitespace are not meaning."""
    t = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return " ".join(t.split())


def uid(text: str) -> str:
    return "el-" + hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()[:10]


def _terms(text: str) -> list[str]:
    return [t for t in normalise(text).split() if t not in _STOP and len(t) > 2]


def slug(text: str, *, max_words: int = 5) -> str:
    """A readable handle derived from the obligation, not from its position.

    Salient governance nouns are pulled to the front so the handle reads as what the element is
    about rather than as its first five words. Deterministic, so the same obligation always
    produces the same handle.
    """
    terms = _terms(text)
    if not terms:
        return "unnamed-element"
    seen, ordered = set(), []
    for key in _SALIENT_FIRST:
        for t in terms:
            if t.startswith(key) and t not in seen:
                seen.add(t)
                ordered.append(t)
    for t in terms:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return "-".join(ordered[:max_words])


def similarity(a: str, b: str) -> float:
    """Jaccard over content terms. Deliberately not an embedding.

    A similarity used to *propose* a carry-over must be inspectable by the person deciding: they
    can see which words two obligations share. A cosine between two vectors gives them a number
    to defer to, which is the wrong relationship to a judgement they are supposed to be making.
    """
    x, y = set(_terms(a)), set(_terms(b))
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def identify(elements: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach uid and slug to a contract's elements, leaving existing fields untouched."""
    out = []
    for e in elements or []:
        if not isinstance(e, dict):
            continue
        text = " ".join(str(e.get("text") or "").split())
        if not text:
            continue
        row = dict(e)
        row["text"] = text
        row["uid"] = uid(text)
        row["slug"] = slug(text)
        out.append(row)
    return out


def diff_contracts(old: Iterable[dict[str, Any]], new: Iterable[dict[str, Any]], *,
                   near_match: float = NEAR_MATCH) -> dict[str, Any]:
    """Which labels carry from `old` to `new`, and which are a human decision.

    Three outcomes per new element, and the boundary between them is the point:

      carried    identical obligation text. The uid matches, so any label attached to the old
                 element is about this same requirement and travels with it.
      proposed   similar but not identical. Reported with the similarity and the old element it
                 resembles, and never applied. Rewording an obligation can change what evidence
                 satisfies it, and only a person can say whether it did.
      new        nothing close. Needs labelling from scratch.

    Old elements with no counterpart are `retired`: any judgement stored against them is now
    orphaned, which is a thing to know rather than a thing to hide.
    """
    old_rows = identify(old)
    new_rows = identify(new)
    old_by_uid = {r["uid"]: r for r in old_rows}
    matched_old: set[str] = set()

    carried, proposed, fresh = [], [], []
    for r in new_rows:
        exact = old_by_uid.get(r["uid"])
        if exact:
            matched_old.add(exact["uid"])
            carried.append({"new_id": r.get("id"), "old_id": exact.get("id"), "uid": r["uid"],
                            "slug": r["slug"], "text": r["text"],
                            "labels": {k: exact.get(k) for k in ("a", "b", "c")
                                       if exact.get(k) is not None}})
            continue
        best, score = None, 0.0
        for o in old_rows:
            sc = similarity(r["text"], o["text"])
            if sc > score:
                best, score = o, sc
        if best and score >= near_match:
            proposed.append({"new_id": r.get("id"), "old_id": best.get("id"), "uid": r["uid"],
                             "slug": r["slug"], "similarity": round(score, 3),
                             "new_text": r["text"], "old_text": best["text"],
                             "old_labels": {k: best.get(k) for k in ("a", "b", "c")
                                            if best.get(k) is not None},
                             "decision": "pending_human"})
        else:
            fresh.append({"new_id": r.get("id"), "uid": r["uid"], "slug": r["slug"],
                          "text": r["text"], "closest": round(score, 3)})

    retired = [{"old_id": o.get("id"), "uid": o["uid"], "slug": o["slug"], "text": o["text"],
                "labels": {k: o.get(k) for k in ("a", "b", "c") if o.get(k) is not None}}
               for o in old_rows if o["uid"] not in matched_old
               and not any(p["old_id"] == o.get("id") for p in proposed)]

    return {
        "schema": SCHEMA,
        "old_count": len(old_rows),
        "new_count": len(new_rows),
        "carried": carried,
        "proposed": proposed,
        "new": fresh,
        "retired": retired,
        "summary": {
            "carried": len(carried),
            "proposed_for_human": len(proposed),
            "needs_fresh_labels": len(fresh),
            "retired": len(retired),
            # What the ordinal scheme could not tell you, and the reason the 10 labels were
            # abandoned rather than triaged.
            "decidable_without_a_person": len(carried),
        },
    }


def duplicate_obligations(elements: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Elements that are the same obligation under different ids.

    `validate_elements` already rejects a duplicate *id*. It cannot see two ids carrying the
    same requirement, which is the failure that actually inflates an element count.
    """
    rows = identify(elements)
    by_uid: dict[str, list[str]] = {}
    for r in rows:
        by_uid.setdefault(r["uid"], []).append(str(r.get("id")))
    return [{"uid": u, "ids": ids, "slug": next(r["slug"] for r in rows if r["uid"] == u)}
            for u, ids in by_uid.items() if len(ids) > 1]
