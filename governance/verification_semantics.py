"""Three concepts that were one field.

`semantic_registry.yaml` set `verification: DETERMINISTIC` on nineteen elements, with
`verification_reason: "Executable predicate specification exists."` The verification mode was
derived directly from predicate presence, which makes it a restatement of `predicate_spec.present`
rather than an independent fact.

That produced a live contradiction. M3.6 e6 —

    "Before deployment, the AI use case, system or model is reviewed by parties not involved in
     its development."

— is marked DETERMINISTIC, while the adjudicated M3.6 calibration corpus in the same package
treats it as a human-adjudicated judgement and 52 judgements were made on that basis. Both cannot
be right, and the one feeding the coverage figure was never adjudicated.

The three concepts:

    predicate_available     a predicate specification exists for this element.
                            A statement about our code.

    verification            whether this element can be decided deterministically *given the
                            evidence a declared provider actually supplies*. A predicate that
                            needs reviewer and developer identities is unsatisfiable until
                            something observes identities. A statement about the evidence
                            boundary, which changes as providers are added.

    corpus_observability    how the calibration corpus treats it — ordinary, conditional,
                            out_of_band. A statement about what a validation pack contains.

The rule: **verification may be DETERMINISTIC only when a declared capability supplies every
observation the element's predicate requires.** With no providers declared, no element qualifies,
and that is the honest answer rather than a disappointing one — it says the deterministic layer is
built and not yet fed, which is exactly the state of the system.

When `corpus_observability` and `verification` disagree, both are kept and the conflict is
reported. Silently preferring one would repeat the original error in the opposite direction.
"""
from __future__ import annotations

import collections
from pathlib import Path
from typing import Any, Iterable

import yaml

SCHEMA = "verification-semantics.1"
ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "governance" / "knowledge" / "semantic_registry.yaml"

DETERMINISTIC = "DETERMINISTIC"
HUMAN_JUDGEMENT = "HUMAN_JUDGEMENT"
OUT_OF_BAND = "OUT_OF_BAND"


def corpus_observability(control_id: str, root: Path | None = None) -> dict[str, str]:
    """{element_id: observability} from the calibration corpus, where one exists."""
    base = root or ROOT
    p = base / "eval" / "corpus" / control_id / "elements.yaml"
    if not p.exists():
        return {}
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(e.get("id")): str(e.get("observability") or "")
            for e in doc.get("elements") or [] if e.get("observability")}


def resolve(element: dict, *, capabilities: Iterable[dict] = (),
            observability: str = "") -> dict[str, Any]:
    """The three facts for one element, computed independently of each other."""
    spec = element.get("predicate_spec") or {}
    available = bool(spec.get("present"))
    requires = list(spec.get("requires") or spec.get("observations") or [])

    supplied = {o for c in capabilities for o in (c.get("observes") or [])}
    satisfiable = available and bool(requires) and set(requires) <= supplied

    if observability == "out_of_band" or element.get("verification") == OUT_OF_BAND:
        mode, why = OUT_OF_BAND, "outside the evidence class this control is assessed from"
    elif satisfiable:
        mode, why = DETERMINISTIC, (
            f"predicate available and every required observation "
            f"({', '.join(requires)}) is supplied by a declared provider")
    elif available:
        mode, why = HUMAN_JUDGEMENT, (
            "predicate specification exists, but no declared provider supplies "
            + (f"the observations it requires ({', '.join(requires)})" if requires
               else "the observations it would require, and the predicate does not declare them"))
    else:
        mode, why = HUMAN_JUDGEMENT, "no predicate specification exists for this element"

    out = {"predicate_available": available,
           "predicate_requires": requires,
           "verification": mode,
           "verification_reason": why}
    if observability:
        out["corpus_observability"] = observability
        # A conflict is recorded, never resolved by preference.
        conflict = (mode == DETERMINISTIC and observability in ("ordinary", "conditional"))
        if conflict:
            out["verification_conflict"] = (
                f"registry says {mode}; the adjudicated corpus treats this element as "
                f"{observability}. Both are retained — the disagreement is the finding.")
    return out


def apply(registry_path: Path | None = None, *, capabilities: Iterable[dict] = (),
          root: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Recompute verification across the registry from the three facts."""
    p = registry_path or REGISTRY
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    caps = list(capabilities)
    changes, conflicts = [], []
    counts: collections.Counter = collections.Counter()

    for c in doc.get("controls") or []:
        cid = str(c.get("control_id") or "")
        obs = corpus_observability(cid, root)
        for e in c.get("elements") or []:
            eid = str(e.get("id"))
            before = e.get("verification")
            res = resolve(e, capabilities=caps, observability=obs.get(eid, ""))
            if res["verification"] != before:
                changes.append({"ref": f"{cid}.{eid}", "from": before,
                                "to": res["verification"], "why": res["verification_reason"]})
            if res.get("verification_conflict"):
                conflicts.append({"ref": f"{cid}.{eid}",
                                  "detail": res["verification_conflict"]})
            e.update(res)
            counts[res["verification"]] += 1

    if not dry_run:
        p.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100),
                     encoding="utf-8")
    return {"schema": SCHEMA, "by_mode": dict(counts), "changed": len(changes),
            "changes": changes[:40], "conflicts": conflicts, "dry_run": dry_run,
            "capabilities_declared": len(caps)}


def report(r: dict[str, Any]) -> str:
    lines = [f"verification modes: {r['by_mode']}",
             f"changed: {r['changed']} · capabilities declared: {r['capabilities_declared']}"]
    if r["conflicts"]:
        lines.append(f"  {len(r['conflicts'])} registry/corpus conflict(s) retained:")
        for c in r["conflicts"][:5]:
            lines.append(f"    {c['ref']}")
    for c in r["changes"][:6]:
        lines.append(f"  {c['ref']:14} {c['from']} -> {c['to']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(report(apply(dry_run="--dry-run" in sys.argv)))
