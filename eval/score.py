"""Score the assessor against the labelled golden set, and write the result to eval_results.json.

    cd repo && python eval/score.py --version v0.3.0 --mode ratchet

Metrics:
  accuracy      exact agreement on sufficiency (the headline number), over all eligible cases
                including refusals - a refusal counts as wrong, because a model that will not
                answer is not usable
  adjacent      agreement within one step (none/partial/full ordered) - a softer read
  over_credit   share of cases where the assessor rated HIGHER than the reviewer (the risk that
                matters). Reported separately from under-crediting.
  maturity_mae  mean absolute error on maturity over every case that returned a maturity, with
                the sample size reported alongside it. maturity_mae_agreed is the older, narrower
                definition (agreeing cases only) and is kept so earlier runs stay comparable.
  refusal_rate  share of cases the assessor could not produce a valid rating for

Accuracy is also broken out by case kind (real / synthetic). Synthetic cases are authored with the
answer decided in advance, so they measure agreement with the author's construction rather than
judgement on real evidence. The two should not be read as equivalent and are never pooled here.

The golden set is hashed into every result. A run that scores fewer than --min-scored cases is
recorded as NOT_TESTABLE rather than reporting a number, matching the evidence floor in
policy/ai-lifecycle.yaml.

WB-029 adds three things the EVL-* controls read:

  --mode          Every run declares what it is. `ratchet` means the assessor changed and the
                  corpus is frozen: improvement can be claimed and the per-case gate applies.
                  `recalibration` means the corpus changed and the assessor is frozen: the run
                  re-establishes a baseline and no improvement claim is admissible. A run that
                  changes both measures nothing, so a ratchet against a different corpus sha is
                  refused rather than scored.

  --repeat        Each case is executed N times. A case whose outcome is not identical across
                  every repeat is QUARANTINED: excluded from the aggregate and from the per-case
                  comparison, and reported by name. A flaky case counted once is a coin toss
                  inside the gate. Default comes from evaluation.promotion.repeat_count.

  --incumbent     The prior detail file to compare against, or auto-selected as the most recent
                  run at the same corpus sha. Per case: incumbent_agree, challenger_agree and
                  regressed (correct became incorrect). EVL-07 counts regressed rows; the
                  aggregate delta is reported but is not the gate, because at current corpus
                  size one document moves it by more than run-to-run variance.

Ambiguous cases are excluded from scoring and reported separately.
Writes an entry to governance/eval_results.json so MCM-03 and MCM-04 have real numbers to test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
SET = HERE / "golden_set.jsonl"
RANK = {"none": 0, "partial": 1, "full": 2}
DEFAULT_REPEAT = 1


def slugify(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text).strip("-").lower()


def policy_repeat_count() -> int:
    """evaluation.promotion.repeat_count, or 1 when the policy cannot be read.

    Defaulting to 1 rather than 3 on failure is deliberate: a silently reduced repeat count
    is visible in the result (repeat_count is recorded), where a silently raised one would
    just cost three times the model calls.
    """
    try:
        from caa.policy import load
        pol = load(REPO / "policy" / "ai-lifecycle.yaml")
        n = ((pol.get("golden_state") or {}).get("evaluation") or {}).get("promotion", {})
        return int(n.get("repeat_count", DEFAULT_REPEAT))
    except Exception:  # noqa: BLE001 - the policy is not load-bearing for scoring
        return DEFAULT_REPEAT


def find_incumbent(set_hash: str, exclude: Path | None = None) -> tuple[dict | None, Path | None]:
    """Most recent detail file, and whether its corpus sha matches this run's.

    Returns the newest detail regardless of sha, so the caller can refuse a ratchet whose
    corpus moved. Selecting only same-sha files here would silently skip the check.
    """
    best, best_path = None, None
    for p in sorted(HERE.glob("score_*.json")):
        if exclude and p.resolve() == exclude.resolve():
            continue
        try:
            d = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        s = d.get("summary") or {}
        if not s.get("run_at") or "rows" not in d:
            continue
        if best is None or str(s["run_at"]) > str((best.get("summary") or {}).get("run_at", "")):
            best, best_path = d, p
    return best, best_path




def classification_metrics(rows):
    """Return confusion matrix and class metrics for non-refused, non-quarantined rows."""
    matrix = {actual: {pred: 0 for pred in RANK} for actual in RANK}
    for r in rows:
        want, got = r.get("want"), r.get("got")
        if want in RANK and got in RANK and not r.get("quarantined"):
            matrix[want][got] += 1
    metrics = {}
    for cls in RANK:
        tp = matrix[cls][cls]
        fp = sum(matrix[a][cls] for a in RANK if a != cls)
        fn = sum(matrix[cls][p] for p in RANK if p != cls)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
        support = sum(matrix[cls].values())
        metrics[cls] = {"support": support, "precision": precision, "recall": recall, "f1": f1}
    observed = [v["f1"] for v in metrics.values() if v["f1"] is not None]
    recalls = [v["recall"] for v in metrics.values() if v["recall"] is not None]
    macro_f1 = sum(observed) / len(observed) if observed else None
    balanced_accuracy = sum(recalls) / len(recalls) if recalls else None
    return matrix, metrics, macro_f1, balanced_accuracy



def _corpus_binding() -> dict:
    """Stale and unbound corpus cases, or an empty result when the corpus is unavailable.

    Never raises: score.py must still run on the golden set in a tree without eval_adapters,
    and an unavailable corpus is not the same claim as a bound one.
    """
    try:
        import sys as _sys
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
        import eval_adapters as _ea
        rows = _ea.corpus_case_rows()
    except Exception as e:
        return {"available": False, "reason": str(e), "stale": [], "unbound": []}
    return {
        "available": True,
        "stale": sorted(r["case_id"] for r in rows if r.get("requirement_sha_mismatch")),
        "unbound": sorted(r["case_id"] for r in rows if not r.get("requirement_sha")),
        "cases_examined": len(rows),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="assessor version being evaluated, e.g. v0.3.0")
    ap.add_argument("--mode", required=True, choices=["ratchet", "recalibration"],
                    help="ratchet = assessor changed, corpus frozen (gated). "
                         "recalibration = corpus changed, assessor frozen (baseline only).")
    ap.add_argument("--set-name", default="golden_30_mas_v2")
    ap.add_argument("--repeat", type=int, default=None,
                    help="executions per case; default from evaluation.promotion.repeat_count")
    ap.add_argument("--incumbent", default=None, metavar="DETAIL_JSON",
                    help="prior detail file to compare against; default is the most recent run")
    ap.add_argument("--no-incumbent", action="store_true",
                    help="score without a comparison (first run at a new corpus sha)")
    ap.add_argument("--dry-run", action="store_true", help="score but do not write eval_results.json")
    ap.add_argument("--min-scored", type=int, default=12,
                    help="evidence floor - below this many scored cases the run is NOT_TESTABLE")
    a = ap.parse_args()

    repeat = a.repeat if a.repeat is not None else policy_repeat_count()
    if repeat < 1:
        print("--repeat must be at least 1")
        return 1

    from pipeline import propose
    from assessor import model_name
    from label_governance import audit as audit_labels

    raw = SET.read_text()
    set_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    cases = [json.loads(l) for l in raw.splitlines() if l.strip()]
    label_audit = audit_labels(SET, min_each=5)
    if label_audit["status"] != "PASS":
        print("LABEL GOVERNANCE BLOCKED — fix label/rubric defects before using the score")
        for p in label_audit["problems"]:
            print(f"  {p["case_id"]}: {p["issue"]}")
        return 3
    real_full = sum(1 for c in cases if c.get("kind") == "real" and not (c.get("label") or {}).get("ambiguous") and (c.get("label") or {}).get("sufficiency") == "full")
    if real_full < 3:
        print(f"LABEL GOVERNANCE BLOCKED — only {real_full} real-evidence full cases; require at least 3")
        return 3
    labelled = [c for c in cases if c.get("label") and not c["label"].get("ambiguous")]
    ambiguous = [c for c in cases if c.get("label", {}).get("ambiguous")]
    unlabelled = [c for c in cases if not c.get("label")]
    if unlabelled:
        print(f"{len(unlabelled)} case(s) unlabelled - label them first: python eval/label.py --all")
        return 1

    # ---- incumbent selection and the one-variable-per-commit rule ------------------------
    inc, inc_path = (None, None)
    if not a.no_incumbent:
        if a.incumbent:
            inc_path = Path(a.incumbent)
            if not inc_path.exists():
                print(f"--incumbent {inc_path} not found")
                return 1
            inc = json.loads(inc_path.read_text())
        else:
            inc, inc_path = find_incumbent(set_hash)

    inc_hash = ((inc or {}).get("summary") or {}).get("eval_set_sha256_12")
    if a.mode == "ratchet" and inc and inc_hash != set_hash:
        print(f"REFUSED. Mode is ratchet, but the corpus moved: incumbent sha {inc_hash}, "
              f"this run {set_hash}.\nA run that changes both the assessor and the corpus "
              f"measures neither. Score this as --mode recalibration, or restore the corpus.")
        return 2
    compare = bool(inc) and inc_hash == set_hash
    inc_rows = {r["case"]: r for r in (inc or {}).get("rows", [])} if compare else {}

    dist = Counter(c["label"]["sufficiency"] for c in labelled)
    kinds = Counter(c.get("kind", "unknown") for c in labelled)
    print(f"scoring {len(labelled)} cases ({len(ambiguous)} ambiguous, excluded) against {model_name()}")
    print(f"set {a.set_name} sha {set_hash} - labels {dict(dist)} - kinds {dict(kinds)}")
    print(f"mode {a.mode} - {repeat} execution(s) per case - "
          + (f"incumbent {inc_path.name}" if compare else "no incumbent comparison") + "\n")

    rows, refusals, quarantined = [], 0, 0
    for c in labelled:
        outs = [propose(SimpleNamespace(**c["control"]),
                        {"text": c["evidence"], "file_name": "", "auto": False, "sources": []})
                for _ in range(repeat)]
        gots = [o.get("sufficiency") if o.get("model") != "error" else None for o in outs]
        want = c["label"]["sufficiency"]
        flaky = len(set(map(str, gots))) > 1
        out, got = outs[0], gots[0]

        base = {"case": c["case_id"], "kind": c.get("kind", "unknown"), "control": c["control"]["id"],
                "want": want, "want_maturity": c["label"]["maturity"],
                "reviewer_reason": c["label"]["reason"],
                "runs": [str(g) for g in gots], "repeat_count": repeat, "quarantined": flaky}

        if flaky:
            quarantined += 1
            rows.append({**base, "got": None, "agree": False, "direction": "quarantined",
                         "got_maturity": None})
            print(f"?? {c['case_id']:6} {c['control']['id']:6} want={want:8} got={'/'.join(str(g) for g in gots)}")
            continue

        if got not in RANK:
            refusals += 1
            rows.append({**base, "got": None, "agree": False, "direction": "refusal",
                         "got_maturity": None})
            print(f"  {c['case_id']:6} {c['control']['id']:6} want={want:8} got=ERROR")
            continue

        d = RANK[got] - RANK[want]
        rows.append({**base, "got": got, "agree": got == want,
                     "direction": "over" if d > 0 else "under" if d < 0 else "exact",
                     "got_maturity": out.get("proposedMaturity"),
                     "flags": len(out.get("flags", []))})
        mark = "  " if got == want else ("!!" if d > 0 else " ~")
        print(f"{mark} {c['case_id']:6} {c['control']['id']:6} want={want:8} got={got:8} "
              f"mat {c['label']['maturity']}->{out.get('proposedMaturity')}"
              + (f"  flags={len(out.get('flags', []))}" if out.get("flags") else ""))

    # ---- per-case comparison against the incumbent ---------------------------------------
    regressions = []
    for r in rows:
        prior = inc_rows.get(r["case"]) if compare else None
        r["incumbent_agree"] = bool(prior["agree"]) if prior else None
        r["challenger_agree"] = bool(r["agree"])
        r["regressed"] = bool(prior and prior.get("agree") and not r["agree"]
                              and not r["quarantined"])
        if r["regressed"]:
            regressions.append(r)

    # ---- aggregates. Quarantined cases are outside the denominator entirely: they are not
    # wrong answers, they are absent ones, and counting them either way states more than the
    # run knows. Refusals stay inside it - a model that will not answer is not usable.
    eligible = [r for r in rows if not r["quarantined"]]
    n_total = len(eligible)
    scored = [r for r in eligible if r["direction"] not in ("refusal", "quarantined")]
    n_scored = len(scored)

    actual_dist = Counter(r["want"] for r in eligible if r.get("want") in RANK)
    predicted_dist = Counter(r["got"] for r in scored if r.get("got") in RANK)
    matrix, class_metrics, macro_f1, balanced_accuracy = classification_metrics(scored)
    acc = sum(r["agree"] for r in scored) / n_total if n_total else 0
    adj = sum(1 for r in scored if abs(RANK[r["got"]] - RANK[r["want"]]) <= 1) / n_total if n_total else 0
    over = sum(1 for r in scored if r["direction"] == "over") / n_total if n_total else 0
    under = sum(1 for r in scored if r["direction"] == "under") / n_total if n_total else 0
    quarantine_rate = quarantined / len(rows) if rows else 0

    mat_all = [abs(r["got_maturity"] - r["want_maturity"]) for r in scored if r["got_maturity"] is not None]
    mae = sum(mat_all) / len(mat_all) if mat_all else None
    mat_agr = [abs(r["got_maturity"] - r["want_maturity"]) for r in scored if r["agree"] and r["got_maturity"] is not None]
    mae_agr = sum(mat_agr) / len(mat_agr) if mat_agr else None

    by_kind = {}
    for r in eligible:
        b = by_kind.setdefault(r["kind"], {"n": 0, "correct": 0, "refusals": 0})
        b["n"] += 1
        if r["direction"] == "refusal":
            b["refusals"] += 1
        elif r["agree"]:
            b["correct"] += 1
    for b in by_kind.values():
        b["accuracy"] = round(b["correct"] / b["n"], 3) if b["n"] else None

    status = "evaluated" if n_scored >= a.min_scored else "NOT_TESTABLE"

    # WB-036: a label is only a label while it describes the requirement it was argued against.
    # eval_adapters has computed requirement_sha since WB-029 and the EVL controls check it, but
    # nothing in the scoring path consulted it — so a run whose corpus had gone stale reported an
    # accuracy figure exactly as if it had not. Staleness is not a low sample count and it is not
    # a failure: it is an unanswerable question, which is what NOT_TESTABLE is for.
    binding = _corpus_binding()
    if binding.get("stale") or binding.get("unbound"):
        status = "NOT_TESTABLE"

    if not rows:
        print("\nno cases scored")
        return 1

    print(f"\nscored {n_scored} of {n_total} eligible ({refusals} refusals, "
          f"{quarantined} quarantined of {len(rows)})   status {status}   mode {a.mode}")
    print(f"accuracy {acc:.0%}   adjacent {adj:.0%}   over-credit {over:.0%}   under-credit {under:.0%}   "
          f"refusals {refusals/n_total if n_total else 0:.0%}")
    def _shares(c):
        total = sum(c.values()) or 1
        return {k: round(c.get(k, 0) / total, 3) for k in RANK}
    pred_delta = {k: round(_shares(predicted_dist)[k] - _shares(actual_dist)[k], 3) for k in RANK}
    print(f"prediction distribution  actual={dict(actual_dist)} predicted={dict(predicted_dist)}")
    print(f"class metrics            macro_f1={macro_f1 if macro_f1 is None else round(macro_f1, 3)} "
          f"balanced_accuracy={balanced_accuracy if balanced_accuracy is None else round(balanced_accuracy, 3)}")
    print(f"distribution share delta  {pred_delta}")
    print("confusion matrix         rows=actual, columns=predicted")
    print("                         none partial full")
    for actual in RANK:
        print(f"  {actual:8}               {matrix[actual]['none']:4} {matrix[actual]['partial']:7} {matrix[actual]['full']:4}")
    print(f"maturity MAE {mae if mae is None else round(mae, 2)} over {len(mat_all)} case(s)   "
          f"(agreed-only {mae_agr if mae_agr is None else round(mae_agr, 2)} over {len(mat_agr)})")
    for k in sorted(by_kind):
        b = by_kind[k]
        print(f"  {k:10} accuracy {b['accuracy']:.0%} over {b['n']} case(s), {b['refusals']} refusal(s)")

    # Constant baselines. An accuracy figure means nothing without them: a set whose labels are
    # 47% "none" gives 47% to a model that answers "none" unconditionally, and on 2026-09-10
    # llama3.2 scored 42% on this set - worse than saying nothing at all. Reported here so the
    # headline number is always read against the floor it has to clear.
    _wants = [c["label"]["sufficiency"] for c in labelled if c.get("label")]
    margin = None
    if _wants:
        _n = len(_wants)
        _const = {s: _wants.count(s) / _n for s in ("none", "partial", "full")}
        _best = max(_const, key=_const.get)
        print("\nconstant baselines - what a model scores by answering the same thing every time:")
        for s in ("none", "partial", "full"):
            mark = "  <- majority class" if s == _best else ""
            print(f"  always-{s:8} {_const[s]:.0%}{mark}")
        margin = acc - _const[_best]
        verdict = ("BELOW the majority-class baseline - this model would score higher by "
                   "answering the same thing every time" if margin < 0 else
                   f"{margin:+.0%} against the majority-class baseline")
        print(f"  accuracy {acc:.0%} is {verdict}")

    if binding.get("stale") or binding.get("unbound"):
        bad = binding.get("stale") or binding.get("unbound")
        what = "stale" if binding.get("stale") else "unbound"
        print(f"\nNOT_TESTABLE - {len(bad)} corpus case(s) are {what}: {', '.join(bad)}")
        print("The labels were argued against a requirement that has since changed, so agreement "
              "with them\nmeasures nothing. Re-argue LABELS.md against the current elements and "
              "update requirement_sha\nin elements.yaml. Any accuracy printed above is reported "
              "for diagnosis only.")
    elif status == "NOT_TESTABLE":
        print(f"\nfewer than {a.min_scored} cases scored - this run reports NOT_TESTABLE, not a rating")

    if quarantined:
        print(f"\nQuarantined ({quarantine_rate:.0%}) - the same input gave different answers across "
              f"{repeat} executions. Read these before trusting any number above:")
        for r in rows:
            if r["quarantined"]:
                print(f"  {r['case']} {r['control']}: {' / '.join(r['runs'])}")

    if compare:
        prior_acc = (inc.get("summary") or {}).get("accuracy")
        delta = None if prior_acc is None else acc - float(prior_acc)
        print(f"\nagainst incumbent {inc_path.name}"
              + (f" - accuracy {delta:+.1%}" if delta is not None else ""))
        if regressions:
            print(f"REGRESSIONS: {len(regressions)} case(s) were correct under the incumbent and "
                  f"are not now. EVL-07 counts these; the aggregate is not the gate.")
            for r in regressions:
                print(f"  {r['case']} {r['control']}: want {r['want']}, got {r['got']} - "
                      f"reviewer said: {r['reviewer_reason']}")
        else:
            print("no per-case regressions")
    elif a.mode == "ratchet":
        print("\nno incumbent at this corpus sha - this run establishes the baseline, "
              "it does not demonstrate improvement")

    if over:
        print("\nOver-credited (the assessor rated the evidence higher than the reviewer) - read these first:")
        for r in scored:
            if r["direction"] == "over":
                print(f"  {r['case']} {r['control']}: want {r['want']}, got {r['got']} - reviewer said: {r['reviewer_reason']}")

    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = {"version": a.version, "run_at": run_at,
             "mode": a.mode,
             "eval_set": a.set_name, "eval_set_size": len(rows), "eval_set_sha256_12": set_hash,
             "cases_eligible": n_total, "cases_scored": n_scored, "cases_refused": refusals,
             "cases_quarantined": quarantined, "quarantine_rate": round(quarantine_rate, 3),
             "repeat_count": repeat, "min_scored": a.min_scored,
             "corpus_binding": binding,
             "label_distribution": dict(dist), "kind_distribution": dict(kinds), "real_full_cases": real_full,
             "label_governance": {"status": label_audit["status"],
                                  "distribution_status": label_audit["distribution_status"],
                                  "distribution_readiness": label_audit["distribution_readiness"]},
             "model": model_name(),
             "accuracy": round(acc, 3), "adjacent_accuracy": round(adj, 3),
             "over_credit_rate": round(over, 3), "under_credit_rate": round(under, 3),
             "refusal_rate": round(refusals / n_total, 3) if n_total else None,
             "maturity_mae": None if mae is None else round(mae, 2), "maturity_mae_n": len(mat_all),
             "maturity_mae_agreed": None if mae_agr is None else round(mae_agr, 2),
             "maturity_mae_agreed_n": len(mat_agr),
             "accuracy_by_kind": by_kind,
             "prediction_distribution": dict(predicted_dist),
             "prediction_distribution_share": _shares(predicted_dist),
             "actual_distribution_share": _shares(actual_dist),
             "prediction_distribution_delta": pred_delta,
             "confusion_matrix": matrix,
             "class_metrics": class_metrics,
             "macro_f1": None if macro_f1 is None else round(macro_f1, 3),
             "balanced_accuracy": None if balanced_accuracy is None else round(balanced_accuracy, 3),
             "constant_baselines": {s: round(
                 [c["label"]["sufficiency"] for c in labelled if c.get("label")].count(s)
                 / max(1, len([c for c in labelled if c.get("label")])), 3)
                 for s in ("none", "partial", "full")},
             "baseline_margin": None if margin is None else round(margin, 3),
             "incumbent": inc_path.name if compare else None,
             "incumbent_sha256_12": inc_hash if compare else None,
             "regressions": len(regressions),
             "regressed_cases": [r["case"] for r in regressions],
             "fairness_gap": None,
             "status": status,
             "notes": f"{len(rows)} reviewer-labelled cases, {len(ambiguous)} excluded as ambiguous, "
                      f"{quarantined} quarantined as non-deterministic over {repeat} execution(s). "
                      f"Labels recorded before scoring; assessor output not shown during labelling. "
                      f"Refusals counted as wrong in accuracy; quarantined cases excluded from it. "
                      f"Synthetic cases are author-constructed and are reported separately from "
                      f"real-evidence cases, never pooled. Mode {a.mode}: "
                      + ("improvement claims are admissible against the incumbent."
                         if a.mode == "ratchet" else
                         "the corpus moved, so this re-establishes a baseline and no improvement "
                         "claim is admissible.")}

    # Time in the filename, not just the date: two runs of the same version and model on one
    # day were overwriting each other, which is how a detail file came to show as modified
    # rather than new.
    stamp = run_at.replace(":", "").replace("-", "")[:15]
    detail = HERE / f"score_{a.version}_{slugify(model_name())}_{stamp}.json"
    detail.write_text(json.dumps({"summary": entry, "rows": rows}, indent=2))
    print(f"\ndetail: {detail}")

    if a.dry_run:
        print("dry run - eval_results.json not written")
        return 0
    ep = REPO / "governance" / "eval_results.json"
    existing = json.loads(ep.read_text()) if ep.exists() else []
    existing = [e for e in existing if not (e.get("version") == a.version and e.get("model") == model_name())]
    existing.append(entry)
    ep.write_text(json.dumps(existing, indent=2))
    print(f"wrote {ep} - MCM-03 and MCM-04 now have real numbers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
