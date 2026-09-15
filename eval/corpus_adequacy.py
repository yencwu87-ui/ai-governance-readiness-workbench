"""GE-110b.1 — corpus adequacy. Is this corpus capable of measuring anything?

Separate from harness validity, and deliberately so. A harness can be perfectly deterministic,
contract-locked and reproducible while measuring a corpus that cannot distinguish a good
assessor from a broken one. `MIN_COMPARED = 3` says a comparison may be *calculated*; it does
not say the result means anything.

This module answers the second question only, for any control. It computes nothing about model
performance and never runs an assessor — it characterises the labels against the contract, so a
corpus can be judged before 42 element judgements are spent on it.

The one number worth reading first is `degenerate_baseline`: the element-level accuracy of an
assessor that ignores the evidence and returns the most common label every time. If a real
assessor cannot beat that, the corpus cannot tell you whether it is working.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "ge110b.corpus-adequacy.1"

_CASE = re.compile(r"### `([^`]+)` → \*\*(\w+)\*\*(.*?)(?=\n###|\n---\n*$|\Z)", re.S)
_ROW = re.compile(r"\|\s*`(e\d+[a-z]?)`\s*\|\s*(\S*)\s*\|\s*(.*?)\s*\|")


def parse_labels(markdown: str) -> dict[str, dict[str, Any]]:
    """{case: {"label": str, "verdicts": {element: (verdict, justification)}}}."""
    out: dict[str, dict[str, Any]] = {}
    for name, label, body in _CASE.findall(markdown):
        verdicts = {m.group(1): (m.group(2), m.group(3)) for m in _ROW.finditer(body)}
        if verdicts:
            out[name] = {"label": label, "verdicts": verdicts}
    return out


def characterise(labels: dict[str, dict[str, Any]], *,
                 elements: list[dict] | None = None) -> dict[str, Any]:
    """The adequacy dimensions, each as a fact rather than a pass/fail.

    Nothing here blocks. A corpus is not invalid for being small — it is only incapable of
    supporting a claim its size does not support, and which claim that is depends on what is
    being asked of it. The caller decides; this reports.
    """
    cases = list(labels)
    declared = [str(e.get("id")) for e in (elements or [])]
    seen_els = sorted({e for c in labels.values() for e in c["verdicts"]},
                      key=lambda x: (len(x), x))
    els = declared or seen_els

    per_element: dict[str, Counter] = {e: Counter() for e in els}
    for c in labels.values():
        for e in els:
            per_element[e][c["verdicts"].get(e, ("missing", ""))[0] or "blank"] += 1

    # An element every case answers the same way cannot discriminate: a model that is right
    # about it once is right about it always, for free.
    constant = [e for e in els if len(per_element[e]) == 1]
    never_met = [e for e in els if not per_element[e].get("Y")]
    never_applicable = [e for e in els
                        if per_element[e].get("n/a", 0) == len(cases) and cases]
    unexercised = [e for e in els if per_element[e].get("missing", 0) == len(cases) and cases]

    all_verdicts = Counter(v for e in els for v, n in per_element[e].items() for _ in range(n)
                           if v not in {"missing", "blank"})
    total = sum(all_verdicts.values())
    degenerate = (max(all_verdicts.values()) / total) if total else 0.0

    # How far apart are the cases? Two cases differing on one element out of seven are two
    # samples of nearly the same document.
    pairs = []
    for i, a in enumerate(cases):
        for b in cases[i + 1:]:
            diff = [e for e in els
                    if labels[a]["verdicts"].get(e, ("", ""))[0]
                    != labels[b]["verdicts"].get(e, ("", ""))[0]]
            pairs.append({"a": a, "b": b, "differing_elements": diff,
                          "distance": len(diff)})

    # Per-case justification. If the text for an element is the same string in every case, the
    # record says what the element means, not why this case was judged this way — so a stored
    # judgement cannot be re-argued from its own provenance.
    shared_justification = []
    for e in els:
        texts = {labels[c]["verdicts"].get(e, ("", ""))[1] for c in cases
                 if e in labels[c]["verdicts"]}
        if len(cases) > 1 and len(texts) == 1 and next(iter(texts), ""):
            shared_justification.append(e)

    # Discrimination matrix. The question is not "how many cases" but "under which elements
    # does different evaluator behaviour produce a different score". An element answered the same
    # way by every case is free marks: a model that is right about it once is right about it
    # always, and gets no credit for understanding it.
    matrix = []
    for e in els:
        answers = [labels[c]["verdicts"].get(e, ("missing", ""))[0] or "blank" for c in cases]
        distinct = {a for a in answers if a not in {"missing", "blank"}}
        # GE-110b.2 — two measures, not two definitions of one measure.
        #
        #   applicability_variation : how many states the element took, n/a included
        #   discriminating          : Y and N both present among *applicable* observations
        #
        # The frozen invariant: `n/a` may change applicability classification, but never by
        # itself creates measurement discrimination. This previously counted n/a as a
        # distinguishing label, so e10 answering N, n/a, N, N read as discriminating — and the
        # module reported 9 discriminating elements against topology's 7 on identical data.
        applicable = [a for a in answers if a in {"Y", "N"}]
        matrix.append({
            "element": e,
            "answers": answers,
            "distinct_labels": sorted(distinct),
            "applicable": applicable,
            "applicability_variation": len(distinct),
            "discriminating": len(set(applicable)) > 1,
        })
    discriminating = [m["element"] for m in matrix if m["discriminating"]]
    applicability_varying = [m["element"] for m in matrix if m["applicability_variation"] > 1]

    outcomes = Counter(c["label"] for c in labels.values())
    # Nearest pair, as a descriptive statistic. Two materially different scenarios landing one
    # element apart says case identity is carrying little extra information under this contract.
    # It is not a defect in either case and does not block anything.
    nearest = min(pairs, key=lambda p: p["distance"]) if pairs else None
    return {
        "discrimination_matrix": matrix,
        "discriminating_elements": discriminating,
        "n_discriminating": len(discriminating),
        "discrimination_rate": round(len(discriminating) / len(els), 3) if els else 0.0,
        "schema": SCHEMA,
        "cases": cases,
        "n_cases": len(cases),
        "n_elements": len(els),
        "n_judgements": len(cases) * len(els),
        "outcome_coverage": dict(outcomes),
        "missing_outcomes": [r for r in ("full", "partial", "none") if r not in outcomes],
        "element_balance": dict(all_verdicts),
        "degenerate_baseline": round(degenerate, 3),
        "degenerate_answer": all_verdicts.most_common(1)[0][0] if all_verdicts else None,
        "constant_elements": constant,
        "never_met_elements": never_met,
        "never_applicable_elements": never_applicable,
        "unexercised_elements": unexercised,
        "pairwise_distance": pairs,
        "min_pairwise_distance": min((p["distance"] for p in pairs), default=None),
        "elements_with_shared_justification": shared_justification,
        "applicability_varying_elements": applicability_varying,
        "nearest_case_pair": ({"cases": [nearest["a"], nearest["b"]],
                               "hamming_distance": nearest["distance"],
                               "differing_elements": nearest["differing_elements"]}
                              if nearest else None),
        # Reported, never required. A rule saying a corpus must contain full and none would turn
        # the instrument into a target-setting device, which is the failure the whole protocol
        # is built to avoid.
        "headline_outcome_diversity": len(outcomes),
        "headline_outcome_status": ("sufficient for case-level outcome discrimination"
                                    if len(outcomes) > 1
                                    else "insufficient for case-level outcome discrimination"),
        "case_signatures": case_signatures(labels, elements),
        "case_signature_shortcut": case_uniformity(labels)["shortcut_risk"],
    }


def report(char: dict[str, Any]) -> str:
    lines = [f"{char['n_cases']} case(s) × {char['n_elements']} element(s) "
             f"= {char['n_judgements']} judgement(s)",
             f"outcomes: {char['outcome_coverage']}"
             + (f"  MISSING: {', '.join(char['missing_outcomes'])}"
                if char["missing_outcomes"] else ""),
             f"element balance: {char['element_balance']}",
             f"degenerate baseline: an assessor that always answers "
             f"{char['degenerate_answer']!r} scores {char['degenerate_baseline']:.0%} "
             f"at element level"]
    if char["never_met_elements"]:
        lines.append(f"never evidenced by any case ({len(char['never_met_elements'])}): "
                     + ", ".join(char["never_met_elements"])
                     + " — nothing measures whether the assessor recognises these when met")
    if char["never_applicable_elements"]:
        lines.append(f"never applicable ({len(char['never_applicable_elements'])}): "
                     + ", ".join(char["never_applicable_elements"])
                     + " — the not_applicable path is untested")
    if char["min_pairwise_distance"] is not None:
        closest = min(char["pairwise_distance"], key=lambda p: p["distance"])
        lines.append(f"closest pair: {closest['a']} vs {closest['b']} differ on "
                     f"{closest['distance']} of {char['n_elements']} element(s)"
                     + (f" ({', '.join(closest['differing_elements'])})"
                        if closest["differing_elements"] else ""))
    lines.append(f"discriminating elements: {char['n_discriminating']} of "
                 f"{char['n_elements']} ({char['discrimination_rate']:.0%}) — the rest are "
                 f"answered identically by every case and cannot distinguish evaluator behaviour")
    if char["n_discriminating"]:
        lines.append("  " + ", ".join(
            f"{m['element']}[{'/'.join(m['answers'])}]"
            for m in char["discrimination_matrix"] if m["discriminating"]))
    sig = char.get("case_signatures") or {}
    if sig.get("signatures"):
        lines.append("case signatures (+ Y · - N · · n/a · ? missing):")
        for case, v in sig["signatures"].items():
            lines.append(f"    {case:16} {v}")
        if sig.get("collisions"):
            lines.append("    signature collision — these cases observe the same thing: "
                         + "; ".join(", ".join(c["cases"]) for c in sig["collisions"]))
        if char.get("case_signature_shortcut"):
            lines.append(f"    {CASE_SIGNATURE_SHORTCUT} — every scoring case is internally "
                         f"uniform, so case identity predicts every answer")
    if char["elements_with_shared_justification"]:
        lines.append(f"justification is per-element, not per-case, for "
                     f"{len(char['elements_with_shared_justification'])} element(s) — a stored "
                     f"judgement cannot be re-argued from its own record")
    return "\n".join(lines)


def characterise_path(labels_md: str | Path, elements_yaml: str | Path | None = None) -> dict:
    """Characterise a corpus from its rendered labels, and its provenance from the source YAML.

    Two files because they answer different questions. `LABELS.md` is a rendering and carries the
    verdicts; `elements.yaml` is the record and carries who decided and why. A corpus can look
    well-covered in the first and be unattributable in the second.
    """
    import yaml
    text = Path(labels_md).read_text(encoding="utf-8")
    elements, doc = None, {}
    if elements_yaml is None:
        guess = Path(labels_md).parent / "elements.yaml"
        elements_yaml = guess if guess.exists() else None
    if elements_yaml and Path(elements_yaml).exists():
        doc = yaml.safe_load(Path(elements_yaml).read_text(encoding="utf-8")) or {}
        elements = doc.get("elements")
    char = characterise(parse_labels(text), elements=elements)
    if doc:
        from eval.label_provenance import summary, validate
        char["provenance"] = summary(doc)
        char["provenance_findings"] = validate(doc)
    return char


def _observability(elements: list[dict] | None) -> dict[str, dict]:
    return {str(e.get("id")): e for e in (elements or []) if e.get("id")}


def classify_gaps(char: dict[str, Any], elements: list[dict] | None = None) -> dict[str, Any]:
    """Split the undiscriminating elements by *why* they are undiscriminating.

    Without this the tool reports a permanent gap for an element no validation pack contains,
    and a permanent gap looks like a corpus that was never finished. Three different facts were
    being counted as one:

      ordinary      the corpus should discriminate this and does not — a real gap, fix it with
                    a case
      conditional   the precondition never held in any case, so the element was never applicable.
                    Not a corpus defect; whether it is worth engineering a case that triggers the
                    precondition is a separate judgement
      out_of_band   this evidence class cannot decide it at all. e14 (re-validation triggers) is
                    a lifecycle-governance artefact held outside any single validation pack, so a
                    strong pack legitimately carries nothing for it

    The third is the one worth naming, because it is not a corpus finding at all — it is a
    capability finding, and it is exactly what the eventual verification planner needs to know:
    this element requires a governance-policy source, not document retrieval.
    """
    by_id = _observability(elements)
    constant = [m["element"] for m in char.get("discrimination_matrix") or []
                if not m["discriminating"]]
    out = {"ordinary": [], "conditional": [], "out_of_band": [], "unclassified": []}
    for eid in constant:
        kind = str((by_id.get(eid) or {}).get("observability") or "unclassified")
        out.setdefault(kind, []).append(eid)
    return {
        "real_gaps": sorted(out["ordinary"]),
        "precondition_never_held": sorted(out["conditional"]),
        "outside_this_evidence_class": sorted(out["out_of_band"]),
        "unclassified": sorted(out["unclassified"]),
        "capability_gaps": [
            {"element": eid, "note": (by_id.get(eid) or {}).get("observability_note", ""),
             "needs": "a source other than the evidence bundle"}
            for eid in sorted(out["out_of_band"])],
    }


def discrimination_target(char: dict[str, Any], elements: list[dict] | None = None) -> dict[str, Any]:
    """What new cases must *exercise*, derived from what the current corpus cannot distinguish.

    GE-110b.2 is a content-design problem, and this is deliberately the smaller half of it: it
    states which elements currently have no discriminating observation, never what the answer
    for them should be.

    That distinction is the design rule. Writing "case 1 should be `full`" and then building
    evidence to reach it produces a corpus that measures whether the author can hit a target.
    Saying "e6 is answered N by every case, so nothing tests whether the evaluator recognises it
    when met" states a property of the instrument and leaves the evidence — and therefore the
    label — free. Evidence constrains the label; the target constrains only coverage.

    Nothing here is a quota. Three cases that happen to leave one element undiscriminating are
    a better corpus than three contrived ones that fill every cell.
    """
    blind = sorted(set(char.get("never_met_elements") or [])
                   | set(char.get("unexercised_elements") or []))
    split = classify_gaps(char, elements)
    # Only the ordinary ones are things new cases should be engineered to cover. Forcing a case
    # to make an out-of-band element decidable is how a calibration corpus becomes fiction.
    constant = split["real_gaps"] + split["unclassified"]
    return {
        "schema": SCHEMA,
        "needs_a_discriminating_observation": constant,
        "gap_classification": split,
        "never_observed_as_met": blind,
        "applicability_untested": sorted(char.get("never_applicable_elements") or []),
        "missing_outcomes": char.get("missing_outcomes") or [],
        "current_degenerate_baseline": char.get("degenerate_baseline"),
        "note": ("These are coverage gaps, not target verdicts. A new case must make the "
                 "element decidable from its evidence; what it decides to is the evidence's "
                 "business."),
    }


def target_report(char: dict[str, Any], elements: list[dict] | None = None) -> str:
    t = discrimination_target(char, elements)
    lines = ["What the next cases must make decidable (coverage, not verdicts):"]
    if t["missing_outcomes"]:
        lines.append(f"  · outcomes never produced: {', '.join(t['missing_outcomes'])}")
    if t["needs_a_discriminating_observation"]:
        lines.append("  · answered identically by every case, so untested: "
                     + ", ".join(t["needs_a_discriminating_observation"]))
    if t["never_observed_as_met"]:
        lines.append("  · never observed as met by anything: "
                     + ", ".join(t["never_observed_as_met"]))
    if t["applicability_untested"]:
        lines.append("  · applicability branch never exercised: "
                     + ", ".join(t["applicability_untested"]))
    g = t.get("gap_classification") or {}
    if g.get("precondition_never_held"):
        lines.append("  · conditional, precondition never held in any case (engineer only if a "
                     "genuine case supplies it): " + ", ".join(g["precondition_never_held"]))
    if g.get("outside_this_evidence_class"):
        lines.append("  · outside this evidence class — a capability gap, not a corpus gap: "
                     + ", ".join(g["outside_this_evidence_class"]))
    lines.append(f"  · a blanket-N evaluator currently scores "
                 f"{t['current_degenerate_baseline']:.0%}; new cases should lower that")
    lines.append("  " + t["note"])
    return "\n".join(lines)


# ---------------------------------------------------------------- measurement topology

#: The joint-discrimination failure. Named for the mechanism rather than for any model or
#: algorithm: the case's own answer-vector identifies it, so an evaluator that recognises which
#: document it is holding can answer uniformly and score full marks without reading evidence.
#: An instrument can have excellent marginal discrimination and terrible joint discrimination,
#: and per-element metrics structurally cannot see the difference.
CASE_SIGNATURE_SHORTCUT = "CASE_SIGNATURE_SHORTCUT"

DISCRIMINATING = "DISCRIMINATING"
INSUFFICIENT_VARIATION = "INSUFFICIENT_VARIATION"
CONDITIONAL_NOT_TRIGGERED = "CONDITIONAL_NOT_TRIGGERED"
UNOBSERVABLE_IN_BUNDLE = "UNOBSERVABLE_IN_BUNDLE"

#: An element needs observations under at least this many applicable cases, differing, before
#: it measures anything. Two is the floor, not a goal: one Y and one N is the minimum that can
#: distinguish an evaluator that reads the evidence from one that has learned the element.
MIN_APPLICABLE_OBSERVATIONS = 2


def element_status(answers: list[str], observability: str = "") -> tuple[str, str]:
    """(status, why) for one element across the corpus.

    Four outcomes rather than good/bad, because an element can fail to discriminate for reasons
    that carry completely different obligations. Collapsing them is what invites a corpus review
    to manufacture documents until the matrix looks tidy.
    """
    applicable = [a for a in answers if a in {"Y", "N"}]
    distinct = set(applicable)
    if observability == "out_of_band":
        return UNOBSERVABLE_IN_BUNDLE, ("this evidence class cannot decide the element; it needs "
                                        "a source other than the evidence bundle")
    if not applicable:
        if observability == "conditional":
            return CONDITIONAL_NOT_TRIGGERED, "the precondition did not hold in any case"
        return INSUFFICIENT_VARIATION, "no case produced an applicable observation"
    if len(distinct) >= 2 and len(applicable) >= MIN_APPLICABLE_OBSERVATIONS:
        return DISCRIMINATING, ""
    if observability == "conditional" and len(applicable) < MIN_APPLICABLE_OBSERVATIONS:
        return CONDITIONAL_NOT_TRIGGERED, (f"only {len(applicable)} applicable observation(s); "
                                           f"the precondition rarely held")
    return INSUFFICIENT_VARIATION, (f"{len(applicable)} applicable observation(s), all "
                                    f"{'/'.join(sorted(distinct))}")


def topology(char: dict[str, Any], elements: list[dict] | None = None) -> dict[str, Any]:
    """Per-element status plus what each element still *requires*, as a requirement.

    The requirement never says what a case should resolve to. "e1 requires two applicable cases
    with differing observed labels" is a demand for an opportunity; "case B should rate e1 N" is
    a demand for an outcome, and a corpus built to the second measures whether the author hit
    the target.
    """
    by_id = _observability(elements)
    rows, requires = [], []
    for m in char.get("discrimination_matrix") or []:
        eid = m["element"]
        obs = str((by_id.get(eid) or {}).get("observability") or "")
        status, why = element_status(m["answers"], obs)
        rows.append({"element": eid, "status": status, "observability": obs or "unclassified",
                     "answers": m["answers"], "why": why})
        if status == DISCRIMINATING:
            continue
        if status == UNOBSERVABLE_IN_BUNDLE:
            requires.append({"element": eid,
                             "requirement": "excluded from validation-pack adequacy",
                             "kind": "capability_finding"})
        elif status == CONDITIONAL_NOT_TRIGGERED:
            pre = (by_id.get(eid) or {}).get("precondition") or "its precondition"
            requires.append({"element": eid,
                             "requirement": f"≥1 case where {pre} genuinely holds",
                             "kind": "conditional"})
        else:
            requires.append({"element": eid,
                             "requirement": (f"≥{MIN_APPLICABLE_OBSERVATIONS} applicable cases "
                                             f"with differing observed labels"),
                             "kind": "variation"})
    counts = Counter(r["status"] for r in rows)
    return {"schema": SCHEMA, "elements": rows, "by_status": dict(counts),
            "requires": requires,
            "n_discriminating": counts.get(DISCRIMINATING, 0)}


def baselines(labels: dict[str, dict[str, Any]], elements: list[dict] | None = None
              ) -> dict[str, Any]:
    """Several trivial strategies, not one.

    A single degenerate baseline hides which trivial strategy is competitive. Reporting them
    separately is what makes the property legible: after a good corpus redesign, *every* trivial
    strategy should be structurally incapable of looking competitive, not just the one that
    happened to be measured.
    """
    els = [str(e.get("id")) for e in (elements or [])] or sorted(
        {e for c in labels.values() for e in c["verdicts"]})
    truth = [labels[c]["verdicts"].get(e, ("", ""))[0] for c in labels for e in els]
    truth = [t for t in truth if t]
    if not truth:
        return {"schema": SCHEMA, "n": 0, "baselines": {}}
    counts = Counter(truth)
    majority = counts.most_common(1)[0][0]
    out = {
        "always_N": round(counts.get("N", 0) / len(truth), 3),
        "always_Y": round(counts.get("Y", 0) / len(truth), 3),
        "always_not_applicable": round(counts.get("n/a", 0) / len(truth), 3),
        f"always_majority({majority})": round(counts[majority] / len(truth), 3),
    }
    return {"schema": SCHEMA, "n": len(truth), "baselines": out,
            "strongest_trivial_strategy": max(out, key=out.get),
            "strongest_trivial_score": max(out.values())}


#: Structural encoding for a signature. The verdicts themselves may be provenance-restricted in
#: a production report; the shape is what the check needs and is always safe to print.
_SIGIL = {"Y": "+", "N": "-", "n/a": "·"}


def case_signatures(labels: dict[str, dict[str, Any]],
                    elements: list[dict] | None = None) -> dict[str, Any]:
    """The answer-vector of each case, structurally, plus collisions between them.

    Recorded explicitly so a later measurement report can say *which* check a corpus failed —
    "passed element discrimination, failed joint discrimination" is an audit trail; "adequacy =
    FAIL" is not.

    A collision is two cases with identical signatures: the second observes nothing the first
    did not, whatever its documents say. Distinct from the shortcut, which is about a signature
    being internally uniform, and worth reporting because the existing corpus is one element
    away from it — M3.6_a and M3.6_b differ on e4 alone.
    """
    els = [str(e.get("id")) for e in (elements or [])] or sorted(
        {e for c in labels.values() for e in c["verdicts"]}, key=lambda x: (len(x), x))
    sigs: dict[str, str] = {}
    for case, blk in labels.items():
        sigs[case] = "".join(_SIGIL.get(blk["verdicts"].get(e, ("", ""))[0], "?") for e in els)
    collisions = []
    seen: dict[str, list[str]] = {}
    for case, sig in sigs.items():
        seen.setdefault(sig, []).append(case)
    for sig, group in seen.items():
        if len(group) > 1:
            collisions.append({"signature": sig, "cases": sorted(group)})
    return {"schema": SCHEMA, "elements": els, "signatures": sigs,
            "legend": {"+": "Y", "-": "N", "·": "n/a", "?": "missing"},
            "collisions": collisions,
            "distinct_signatures": len(seen), "n_cases": len(sigs)}


def case_uniformity(labels: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Can a case be scored without reading its elements?

    A risk the four-case tabulation carries and which per-element discrimination does not catch.
    If case A answers Y to everything and case B answers N to everything, every element looks
    perfectly discriminating — and an evaluator can still score full marks by recognising which
    document it is holding and answering uniformly. The measurement would then be of document
    identification, not of evidence reading.

    A case with internal variation cannot be shortcut that way. This reports which cases are
    uniform; one uniform case in a corpus is normal (a `none` case usually is), several is a
    shortcut waiting to be learned.
    """
    rows = []
    for case, blk in labels.items():
        answers = [v for v, _ in blk["verdicts"].values() if v in {"Y", "N"}]
        distinct = set(answers)
        rows.append({"case": case, "uniform": len(distinct) <= 1 and bool(answers),
                     "answers": sorted(distinct), "n_applicable": len(answers)})
    uniform = [r["case"] for r in rows if r["uniform"]]
    # Only cases that actually observe the element block can break a shortcut. A case whose
    # every answer is n/a neither creates the risk nor dilutes it, so it is excluded from the
    # denominator — counting it made the check silently unfireable on a corpus where half the
    # cases are conditional.
    scoring = [r for r in rows if r["n_applicable"] >= MIN_APPLICABLE_OBSERVATIONS]
    uniform_scoring = [r["case"] for r in scoring if r["uniform"]]
    risk = len(scoring) >= 2 and len(uniform_scoring) == len(scoring)
    return {"schema": SCHEMA, "cases": rows, "uniform_cases": uniform,
            "scoring_cases": [r["case"] for r in scoring],
            "shortcut_risk": risk,
            "finding": CASE_SIGNATURE_SHORTCUT if risk else None,
            "note": ("A corpus whose cases are internally uniform can be scored by recognising "
                     "the document rather than reading the evidence.")}
