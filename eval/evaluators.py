"""GE-110b.5 — evaluators, and where runs are kept.

An evaluator is any callable `(case_id, element_id, evidence, element) -> "Y" | "N" | "n/a"`.
Everything goes through that one signature — naive baselines, the deterministic lexical evaluator
below, the real LLM assessor — so a measurement run cannot tell them apart and none of them gets
a special path. The point is that the harness treats a trivial strategy and a production assessor
identically; the only thing that distinguishes them in the record is `evaluator_config`, which is
hashed into the lineage.

Two real evaluators here.

`lexical` is deterministic and uses no model. It is not a good assessor and is not meant to be —
it exists so the whole path can be exercised without a model endpoint, and so reproducibility has
something non-constant to be true about. A constant evaluator reproduces trivially; an evaluator
with actual branching reproducing is a stronger statement about the harness.

`assessor` wires the production path. Its configuration — model, endpoint, prompt version — is
recorded in the lineage whether or not the model is deterministic, because a result that cannot
name the model that produced it is not attributable, and "it was deterministic" is not a
substitute for saying which thing was deterministic.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "ge110b5.evaluators.1"
RUNS_DIR = Path(__file__).resolve().parents[1] / "eval" / "history" / "runs"

Evaluator = Callable[[str, str, str, dict], str]

_STOP = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with", "by", "from",
         "its", "their", "this", "that", "these", "those", "is", "are", "be", "as", "at",
         "where", "which", "any", "all", "before", "under", "including", "relevant"}


def _terms(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if t not in _STOP and len(t) > 3}


def lexical(threshold: float = 0.45) -> Evaluator:
    """Deterministic term-overlap evaluator. Real branching, no model, no pretence of quality.

    Returns `n/a` when the element declares a precondition and the evidence carries none of the
    precondition's own vocabulary — a crude stand-in for an applicability decision, included
    because an evaluator that never returns `n/a` would leave that third of the path untested.
    """
    def _e(case: str, element: str, evidence: str, el: dict) -> str:
        ev = _terms(evidence)
        want = _terms(str(el.get("text") or ""))
        if not want:
            return "N"
        pre = str(el.get("precondition") or "")
        if pre and not (_terms(pre.replace("_", " ")) & ev):
            return "n/a"
        overlap = len(want & ev) / len(want)
        return "Y" if overlap >= threshold else "N"
    return _e


def lexical_config(threshold: float = 0.45) -> dict[str, Any]:
    return {"kind": "lexical", "threshold": threshold, "model": None,
            "note": "deterministic term overlap; exercises the path, not a quality claim"}


def assessor(control, *, model: str | None = None) -> Evaluator:
    """The production assessor, adapted to the evaluator signature.

    One proposal per case is computed and cached, then each element's verdict is read off its
    `elementVerdicts`. Running the assessor once per element would be thirteen calls per case and
    would also measure something different — the production path assesses a control against a
    bundle, not an element in isolation, and the harness must measure the path as it runs.

    An element the assessor returned no verdict for is `""`, which the run records as unscored
    rather than as a wrong answer. WB-031 already refuses to read silence as agreement; the same
    rule applies to measuring it.
    """
    cache: dict[str, dict] = {}

    def _e(case: str, element: str, evidence: str, el: dict) -> str:
        if case not in cache:
            from pipeline import build_evidence, propose
            from assessor import _artefacts  # noqa: F401  (import guarded by availability)
            cache[case] = propose(control, {"text": evidence, "sources": [f"{case}"]})
        out = cache[case] or {}
        for v in (out.get("elementVerdicts") or out.get("element_verdicts") or []):
            if str(v.get("element_id")) == element:
                return {"met": "Y", "not_evidenced": "N", "not_applicable": "n/a"}.get(
                    str(v.get("status")), "")
        return ""
    return _e


def assessor_config(model: str, *, prompt_version: str = "", endpoint: str = "") -> dict[str, Any]:
    """Recorded whether or not the model is deterministic. Attribution is not a function of
    variance — a result must be able to name what produced it either way."""
    return {"kind": "assessor", "model": model, "prompt_version": prompt_version,
            "endpoint": endpoint}


# ---------------------------------------------------------------- persistence

def save_run(result: dict[str, Any], *, runs_dir: Path | None = None) -> Path:
    """Write a run to disk under its own lineage, so two runs of the same thing collide by name.

    Named from the evaluator hash and the label-set hash rather than a timestamp: a rerun of
    identical inputs should be recognisable as such from the filename alone.
    """
    d = Path(runs_dir or RUNS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    lin = result["lineage"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = (f"run_{result['evaluator'].replace(' ', '-')}"
            f"_{lin['labelset_sha'][:8]}_{lin['evaluator_sha'][:8]}_{stamp}.json")
    p = d / name
    p.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    return p


def load_runs(runs_dir: Path | None = None) -> list[dict[str, Any]]:
    d = Path(runs_dir or RUNS_DIR)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("run_*.json"), reverse=True):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")) | {"_path": str(p)})
        except Exception:
            continue
    return out
