"""GE-110b.4 — the measurement run.

A measurement result is a claim, and a claim needs to carry what it rests on and what it cannot
support. This module makes both travel with the number.

Lineage first. Every run records the hash of its contract, its corpus, its label set and its
evaluator configuration. Without that, "the evaluator scored 71%" is unattributable: nobody can
say later which contract version, which adjudicated labels, or which model produced it, and the
number becomes folklore.

Limitations second, and this is the part that matters. The M3.6 corpus supports element-level
measurement and does not support aggregate full/partial/none measurement — all four cases derive
to `partial`, so there is no case-level variation to measure against. The wrong response is to
block the architecture until the corpus improves. The right one is to report the element metric,
refuse to compute the aggregate metric, and attach the reason to the result so it cannot be
quoted without it.

So `aggregate_accuracy` is not `None` because nothing was computed. It is absent, with
`aggregate_not_computed` naming why. A consumer that wants a case-level number has to read the
reason to discover there isn't one.

Three things this deliberately does not do:

  It does not grade. `ai_adjudicated_candidate` travels as a limitation, not as a discount
  applied to a score — weighting a metric by adjudicator kind would bury the fact in arithmetic.

  It does not threshold. Baselines are reported beside the evaluator's score and the comparison
  is left to a reader. A pass mark here would make the corpus a target.

  It does not run the evaluator. An evaluator is any callable `(case_id, element_id, evidence,
  element) -> "Y" | "N" | "n/a"`, so a naive baseline, a real assessor and a planted-defect probe
  all run through the same path and are all recorded the same way.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA = "ge110b4.measurement-run.1"

Evaluator = Callable[[str, str, str, dict], str]

#: Only these are answers to a requirement. `n/a` is an applicability outcome and is excluded
#: from accuracy, consistent with the frozen discrimination definition.
SCORED = {"Y", "N"}


def _sha(obj: Any) -> str:
    if isinstance(obj, (str, bytes)):
        b = obj.encode("utf-8") if isinstance(obj, str) else obj
    else:
        b = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def lineage(doc: dict, corpus_dir: str | Path, evaluator_config: dict | None = None
            ) -> dict[str, Any]:
    """The four hashes a result must carry, plus the case files it ran against."""
    d = Path(corpus_dir)
    cases = sorted(doc.get("calibration_cases") or [])
    files = {}
    for case in cases:
        for cand in (d / f"{doc.get('control', 'X')}_{case}.md",):
            if cand.exists():
                files[case] = {"file": cand.name, "sha256": _sha(cand.read_bytes())}
    judgements = [j for j in (doc.get("judgements") or [])
                  if j.get("provenance") == "adjudicated_case_specific"
                  and (not cases or j.get("case") in cases)]
    return {
        "contract_sha": _sha([{k: e.get(k) for k in ("id", "text", "observability", "precondition")}
                              for e in (doc.get("elements") or [])]),
        "corpus_sha": _sha(files),
        "labelset_sha": _sha(sorted(
            (j["case"], j["element"], j["verdict"]) for j in judgements)),
        "evaluator_sha": _sha(evaluator_config or {}),
        "cases": cases,
        "case_files": files,
        "n_elements": len(doc.get("elements") or []),
        "n_judgements": len(judgements),
    }


def _truth(doc: dict) -> dict[tuple[str, str], str]:
    cases = set(doc.get("calibration_cases") or [])
    return {(j["case"], j["element"]): j["verdict"]
            for j in (doc.get("judgements") or [])
            if j.get("provenance") == "adjudicated_case_specific"
            and (not cases or j.get("case") in cases)}


def limitations(doc: dict, characterisation: dict | None = None) -> list[dict[str, str]]:
    """What this result cannot support, derived rather than asserted.

    Each entry names the claim it blocks, so a reader learns what not to conclude rather than
    reading a general caveat and ignoring it.
    """
    out: list[dict[str, str]] = []
    from eval.label_provenance import calibration_admissible
    adm = calibration_admissible(doc)
    if adm.get("grade") != "human_adjudicated":
        out.append({
            "code": "ADJUDICATION_GRADE",
            "blocks": "treating these labels as human ground truth",
            "detail": (f"labels are {adm.get('grade')}; adjudicator kinds "
                       f"{adm.get('adjudicator_kinds')}")})
    if characterisation:
        if characterisation.get("headline_outcome_diversity", 0) <= 1:
            out.append({
                "code": "NO_HEADLINE_VARIATION",
                "blocks": "any claim about full/partial/none accuracy",
                "detail": (f"every case derives to the same outcome "
                           f"({list(characterisation.get('outcome_coverage') or {})}); there is "
                           f"no case-level variation to measure against")})
        np_ = characterisation.get("nearest_case_pair") or {}
        if np_ and np_.get("hamming_distance", 99) <= 1:
            out.append({
                "code": "NEAR_IDENTICAL_CASES",
                "blocks": "treating the case count as the effective sample size",
                "detail": (f"{' and '.join(np_['cases'])} differ on "
                           f"{np_['hamming_distance']} element(s)")})
        if characterisation.get("case_signature_shortcut"):
            out.append({
                "code": "CASE_SIGNATURE_SHORTCUT",
                "blocks": "reading the score as evidence of evidence-reading",
                "detail": "every scoring case is internally uniform"})
        n_disc = sum(1 for m in (characterisation.get("discrimination_matrix") or [])
                     if m.get("discriminating"))
        n_els = len(characterisation.get("discrimination_matrix") or [])
        if n_els and n_disc < n_els:
            out.append({
                "code": "PARTIAL_ELEMENT_COVERAGE",
                "blocks": "generalising the score to the whole contract",
                "detail": (f"{n_disc} of {n_els} elements discriminate; the rest contribute no "
                           f"information about evaluator behaviour")})
    return out


def run(evaluator: Evaluator, doc: dict, corpus_dir: str | Path, *,
        evaluator_name: str, evaluator_config: dict | None = None,
        characterisation: dict | None = None, evidence: dict[str, str] | None = None
        ) -> dict[str, Any]:
    """Score an evaluator against the adjudicated labels. Element level only, by construction."""
    d = Path(corpus_dir)
    truth = _truth(doc)
    by_id = {str(e.get("id")): e for e in (doc.get("elements") or [])}
    evidence = evidence or {}
    for case in sorted({c for c, _ in truth}):
        if case not in evidence:
            f = d / f"{doc.get('control', 'X')}_{case}.md"
            evidence[case] = f.read_text(encoding="utf-8") if f.exists() else ""

    rows, errors = [], []
    for (case, eid), gold in sorted(truth.items()):
        try:
            got = str(evaluator(case, eid, evidence.get(case, ""), by_id.get(eid, {})) or "")
        except Exception as exc:  # an evaluator that fails is recorded, never silently skipped
            errors.append({"case": case, "element": eid, "error": str(exc)})
            got = ""
        # GE-110b.5: the denominator is defined by the GOLD label, never by the prediction.
        #
        # This previously required both to be Y/N, which handed the evaluator control of its own
        # denominator: answering `n/a` to a scored element removed that element from the
        # population rather than counting as wrong. `always-n/a` scored 0 of 0 and came back with
        # accuracy `None` — measured as nothing rather than as useless. The lexical evaluator hit
        # a milder version of the same thing, shrinking the population from 41 to 39 and lifting
        # its own apparent baseline.
        #
        # A prediction of `n/a` where the adjudicator found the element applicable is a wrong
        # answer. It is also reported separately as `declined`, because "wrong" and "refused to
        # answer" are different behaviours and a reader should see which one happened.
        rows.append({"case": case, "element": eid, "gold": gold, "predicted": got,
                     "scored": gold in SCORED,
                     "declined": gold in SCORED and got == "n/a",
                     "no_answer": gold in SCORED and got not in SCORED and got != "n/a",
                     "correct": gold in SCORED and got == gold})

    scored = [r for r in rows if r["scored"]]
    correct = sum(1 for r in scored if r["correct"])
    per_element: dict[str, dict[str, Any]] = {}
    for r in scored:
        p = per_element.setdefault(r["element"], {"n": 0, "correct": 0})
        p["n"] += 1
        p["correct"] += r["correct"]
    for eid, p in per_element.items():
        p["accuracy"] = round(p["correct"] / p["n"], 3) if p["n"] else None

    # Baselines must be computed on the population the evaluator is scored against, which is
    # the Y/N subset. `corpus_adequacy.baselines` describes the whole label distribution
    # including n/a and is the right measure there — using it here compared 29/41 against 29/52
    # and reported always-Y beating the always-Y baseline by 15 points, which cannot happen.
    gold_scored = Counter(r["gold"] for r in scored)
    n_scored = len(scored) or 1
    base_on_scored = {f"always_{k}": round(v / n_scored, 3)
                      for k, v in sorted(gold_scored.items())}
    strongest = max(base_on_scored, key=base_on_scored.get) if base_on_scored else None
    base = {"baselines": base_on_scored,
            "strongest_trivial_strategy": strongest,
            "strongest_trivial_score": base_on_scored.get(strongest) if strongest else None,
            "population": "scored (Y/N) judgements only"}

    acc = round(correct / len(scored), 3) if scored else None
    lim = limitations(doc, characterisation)
    result = {
        "schema": SCHEMA,
        "evaluator": evaluator_name,
        "lineage": lineage(doc, d, evaluator_config),
        "element_accuracy": acc,
        "n_scored": len(scored),
        "n_judgements": len(rows),
        "n_excluded_not_applicable": len(rows) - len(scored),
        "n_declined": sum(1 for r in scored if r["declined"]),
        "n_no_answer": sum(1 for r in scored if r["no_answer"]),
        "per_element": per_element,
        "baselines": base.get("baselines"),
        "baseline_population": base.get("population"),
        "strongest_trivial_strategy": base.get("strongest_trivial_strategy"),
        "strongest_trivial_score": base.get("strongest_trivial_score"),
        "margin_over_strongest_trivial": (round(acc - base["strongest_trivial_score"], 3)
                                          if acc is not None and base.get("strongest_trivial_score")
                                          is not None else None),
        "evaluator_errors": errors,
        "limitations": lim,
        "predictions": rows,
    }
    # Absent, with a reason — not None, which reads as "computed and came out empty".
    if any(l["code"] == "NO_HEADLINE_VARIATION" for l in lim):
        result["aggregate_not_computed"] = (
            "The corpus has one distinct case-level outcome, so full/partial/none accuracy is "
            "not defined against it. This is a property of the corpus, not a failure of the run.")
    return result


def reproduce(a: dict, b: dict) -> dict[str, Any]:
    """Two runs of the same thing must agree, and disagreement must say where.

    Identical lineage with differing predictions means the evaluator is non-deterministic, which
    is a finding about the evaluator. Differing lineage means the runs are not comparable and the
    accuracy difference says nothing — reported as `not_comparable` rather than as a delta.
    """
    same = {k: a["lineage"][k] == b["lineage"][k]
            for k in ("contract_sha", "corpus_sha", "labelset_sha", "evaluator_sha")}
    if not all(same.values()):
        return {"schema": SCHEMA, "comparable": False,
                "differing_lineage": [k for k, v in same.items() if not v],
                "verdict": "not_comparable",
                "note": "different inputs; any score difference is unattributable"}
    pa = {(r["case"], r["element"]): r["predicted"] for r in a["predictions"]}
    pb = {(r["case"], r["element"]): r["predicted"] for r in b["predictions"]}
    diffs = [{"case": c, "element": e, "a": pa[(c, e)], "b": pb.get((c, e))}
             for (c, e) in sorted(pa) if pa[(c, e)] != pb.get((c, e))]
    return {"schema": SCHEMA, "comparable": True, "reproducible": not diffs,
            "n_differences": len(diffs), "differences": diffs[:25],
            "verdict": "reproducible" if not diffs else "non_deterministic_evaluator"}


def constant(answer: str) -> Evaluator:
    """A naive baseline as an evaluator, so it runs through exactly the same path as a real one."""
    def _e(case: str, element: str, evidence: str, el: dict) -> str:
        return answer
    return _e


def report(result: dict[str, Any]) -> str:
    lines = [f"{result['evaluator']} — element accuracy "
             + (f"{result['element_accuracy']:.1%}" if result["element_accuracy"] is not None
                else "not computed")
             + f" over {result['n_scored']} scored judgement(s)",
             f"  excluded as not applicable (gold n/a): {result['n_excluded_not_applicable']}"
             + (f" · declined {result['n_declined']}" if result.get("n_declined") else "")
             + (f" · no answer {result['n_no_answer']}" if result.get("n_no_answer") else ""),
             f"  strongest trivial strategy: {result['strongest_trivial_strategy']} "
             f"{result['strongest_trivial_score']:.1%}"
             + (f" · margin {result['margin_over_strongest_trivial']:+.3f}"
                if result["margin_over_strongest_trivial"] is not None else "")]
    if result.get("aggregate_not_computed"):
        lines.append(f"  aggregate: NOT COMPUTED — {result['aggregate_not_computed']}")
    if result.get("evaluator_errors"):
        lines.append(f"  evaluator errors: {len(result['evaluator_errors'])}")
    lines.append("  limitations travelling with this result:")
    for l in result["limitations"]:
        lines.append(f"    · {l['code']} — blocks {l['blocks']}")
    lin = result["lineage"]
    lines.append(f"  lineage: contract {lin['contract_sha'][:12]} · corpus {lin['corpus_sha'][:12]}"
                 f" · labels {lin['labelset_sha'][:12]} · evaluator {lin['evaluator_sha'][:12]}")
    return "\n".join(lines)
