"""Row sources for the HAL-* control pack (WB-030 rev 2).

Rev 1 guessed at field names and carried its own reason predicate. Both are fixed here:
the log keys are `use_case` and `step`, and the reason rule is imported from reasons.py,
which decisions.py states is the single place it lives.

Two populations, deliberately not merged:
  * uc_components   — the governed use case's components. CAID/OAID is declared here.
  * step decisions  — the workbench's own review. Always CAID by construction, so nothing
                      is declared; what is measured is whether the human judgement the
                      architecture assumes is actually in evidence.

The checks are generic counters (record_count over one source with one `where`), so every
judgement is precomputed here as a boolean field — the same division of labour as
corpus_cases and its incomplete_set. A cross-source join cannot happen in a check, so the
two joined sources below do it and emit one row per (component, evidencing step).

INTEGRATION SEAM — the only thing still unresolved:
  `steps()` needs the loaded plays. app.py already has them from plays.load_plays(...);
  pass that list in rather than re-loading here, so the runner and the UI cannot disagree
  about what the steps are.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import decisions as D
import usecases as U
from reasons import is_template, reason_error

COMPONENT_REGISTER = Path("governance/uc_components.csv")

REQUIRED_COLUMNS = (
    "use_case",
    "component_id",
    "component_name",
    "description",
    "spec_sha",
    "outcome_defined",
    "correctness_verifiable",
    "errors_recoverable",
    "human_between_steps",
    "judgement_required",
    "override_human_evaluates",
    "declared_domain",
    "evidencing_steps",
    "rationale",
    "classified_by",
    "classified_on",
)

BOOL_COLUMNS = (
    "outcome_defined",
    "correctness_verifiable",
    "errors_recoverable",
    "human_between_steps",
    "judgement_required",
    "override_human_evaluates",
)

YES_NO = ("yes", "no")
PERMITTED_DOMAINS = ("CAID", "OAID")
NON_PERSON = {"", "system", "assessor", "judge", "runner", "n/a", "none"}

# machine_verdict values that are not a real result. Confirm against the Lane B runner's
# vocabulary before wiring — parameterised in the YAML so the pack, not this module, decides.
INCONCLUSIVE_VERDICTS = {"NOT_TESTABLE", "ERROR", "", None}


def spec_sha(component_name: str, description: str) -> str:
    """sha256 over the component text the classifier read. Nothing volatile."""
    blob = f"{component_name.strip()}\n{description.strip()}"
    lines = [ln.rstrip() for ln in blob.replace("\r\n", "\n").split("\n")]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _g(o, k, d=None):
    return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)


# --- row sources ------------------------------------------------------------


def steps(plays: list) -> list[dict]:
    """Every play step, flattened. SEAM: pass plays.load_plays(...) output from the caller."""
    rows = []
    for p in plays or []:
        for s in _g(p, "steps", []) or []:
            rows.append(
                {
                    "play": _g(p, "id"),
                    "step": _g(s, "id"),
                    "owner": _g(s, "owner", ""),
                    "action": _g(s, "action", ""),
                    "expected": _g(s, "evidence", "") or "",
                }
            )
    return rows


def uc_components(root: Path) -> list[dict]:
    """Parsed and validated component rows, with staleness computed.

    Malformed rows are kept and carry their defects in `errors`. Dropping them would hide
    them from the evidence floor, letting a register full of junk report a small clean
    population and pass.
    """
    known_cases = {uc.id for uc in U.load()}
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for raw in _read_csv(root / COMPONENT_REGISTER):
        row = {k: (raw.get(k) or "").strip() for k in REQUIRED_COLUMNS}
        errors: list[str] = []

        for col in REQUIRED_COLUMNS:
            if not row[col]:
                errors.append(f"missing:{col}")
        for col in BOOL_COLUMNS:
            if row[col] and row[col].lower() not in YES_NO:
                errors.append(f"not_yes_no:{col}")
        if row["declared_domain"] and row["declared_domain"] not in PERMITTED_DOMAINS:
            errors.append("domain_not_permitted")
        if row["use_case"] not in known_cases:
            errors.append("use_case_not_found")
        if row["classified_by"].lower() in NON_PERSON:
            errors.append("classifier_not_a_person")
        if reason_error(row["rationale"], rating=row["declared_domain"]):
            errors.append("rationale_hollow")
        # Fields that are not reasons, so they get the template rule directly. Without this a
        # register of REPLACE placeholders passes every other check, which is how the shipped
        # template came back with zero errors and two valid hashes.
        for col in ("component_name", "description"):
            if is_template(row[col]):
                errors.append(f"template_placeholder:{col}")

        key = (row["use_case"], row["component_id"])
        if key in seen:
            errors.append("duplicate_component")
        seen.add(key)

        expected_sha = spec_sha(row["component_name"], row["description"])
        row["stale"] = bool(row["spec_sha"]) and row["spec_sha"] != expected_sha
        row["current_spec_sha"] = expected_sha
        row["evidencing_step_ids"] = [s.strip() for s in row["evidencing_steps"].split(";") if s.strip()]
        row["errors"] = errors
        # Booleans for the counters. A check reads one field with one `where`, so a list
        # field like `errors` is unusable to it and every judgement is precomputed here.
        row["has_errors"] = bool(errors)
        row["override_breach"] = (row["override_human_evaluates"].lower() == "no"
                                  and row["declared_domain"] == "CAID")
        row["advisory_flags"] = _advisory_flags(row)
        row["advisory_flag_count"] = len(row["advisory_flags"])
        rows.append(row)

    return rows


def _advisory_flags(row: dict) -> list[str]:
    """The five nature-of-work questions. They report; they never overturn a declaration.

    Only the override is binding, which is the honest reading of the test and keeps the
    check from manufacturing certainty it does not have."""
    d, flags = row["declared_domain"], []
    y = {k: row[k].lower() == "yes" for k in BOOL_COLUMNS}
    if d == "CAID" and not y["human_between_steps"]:
        flags.append("caid_without_human_between_steps")
    if d == "OAID" and y["judgement_required"] and y["override_human_evaluates"]:
        flags.append("oaid_with_human_judgement")
    if d == "OAID" and not y["outcome_defined"]:
        flags.append("oaid_without_defined_outcome")
    if d == "OAID" and not y["correctness_verifiable"]:
        flags.append("oaid_without_verifiable_correctness")
    if d == "OAID" and not y["errors_recoverable"]:
        flags.append("oaid_unrecoverable_check_exception_path")
    return flags


def step_decision_quality(path: Path = D.LOG) -> list[dict]:
    """One row per (use_case, step), summarising whether human judgement is in evidence.

    `blind_n` counts records carrying the reviewer's prior reading. decisions.record()
    accepts `blind=` and no caller passes it yet, so a zero here means the field is unwired,
    not that reviewers skipped it — HAL-03 reports that leg NOT_TESTABLE rather than FAIL.
    """
    by: dict[tuple[str, str], dict] = {}
    for r in D.load(path):
        key = (r.get("use_case"), r.get("step"))
        e = by.setdefault(
            key,
            {
                "use_case": key[0],
                "step": key[1],
                "n": 0,
                "substantive_n": 0,
                "hollow_n": 0,
                "blind_n": 0,
                "lane_b_n": 0,
                "lane_b_rubber_stamp_n": 0,
                "named_reviewer_n": 0,
                "reviewers": set(),
            },
        )
        reason = (r.get("reason") or "").strip()
        reviewer = (r.get("reviewer") or "").strip()
        decision = (r.get("decision") or "").strip()
        hollow = bool(reason_error(reason, rating=decision))
        lane_b = (r.get("proposal") or {}).get("source") == "lane_b"

        e["n"] += 1
        e["hollow_n" if hollow else "substantive_n"] += 1
        if r.get("blind"):
            e["blind_n"] += 1
        if lane_b:
            e["lane_b_n"] += 1
            if decision == "accept" and hollow and not r.get("blind"):
                e["lane_b_rubber_stamp_n"] += 1
        if reviewer and reviewer.lower() not in NON_PERSON:
            e["named_reviewer_n"] += 1
            e["reviewers"].add(reviewer)

    out = []
    for e in by.values():
        e["reviewers"] = sorted(e["reviewers"])
        # the functional-OAID pattern: a human present, no judgement in evidence
        e["functionally_oaid"] = e["n"] > 0 and e["substantive_n"] == 0 and e["blind_n"] == 0
        out.append(e)
    return out


def lane_b_by_step(latest_lane_b: dict[str, dict]) -> list[dict]:
    """Controls covering each step, with their verdicts.

    `latest_lane_b` is pipeline.latest_lane_b() output: control_id -> row carrying
    `play_refs` (step ids) and `machine_verdict`.
    """
    by: dict[str, dict] = {}
    for r in (latest_lane_b or {}).values():
        for step in r.get("play_refs", []) or []:
            e = by.setdefault(step, {"step": step, "control_ids": [], "real_verdict_control_ids": []})
            e["control_ids"].append(r.get("control_id"))
            if r.get("machine_verdict") not in INCONCLUSIVE_VERDICTS:
                e["real_verdict_control_ids"].append(r.get("control_id"))
    return list(by.values())


# --- helpers ----------------------------------------------------------------


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    # utf-8-sig defensively: a BOM must not become part of the first column name, which is
    # how the Lane B joins broke.
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


# --- joined sources (the judgement is precomputed; the check only counts) ----


def uc_case_coverage(root: Path) -> list[dict]:
    """One row per use case. HAL-01 counts the ones with nothing classified.

    The use-case register is the population, not the component register, so a use case
    nobody has classified is a row here rather than an absence of rows. Absence of rows
    is what the evidence floor reads as NOT_TESTABLE, and "nobody classified anything"
    must not read the same as "there are no use cases".
    """
    comps = uc_components(root)
    by_case: dict[str, list[dict]] = {}
    for r in comps:
        by_case.setdefault(r["use_case"], []).append(r)

    rows = []
    for uc in U.load():
        mine = by_case.get(uc.id, [])
        usable = [r for r in mine if not r["errors"]]
        rows.append({
            "use_case": uc.id,
            "components": len(mine),
            "components_usable": len(usable),
            "no_components": len(mine) == 0,
            "no_usable_components": len(usable) == 0,
        })
    return rows


def caid_step_oversight(root: Path, path: Path | None = None) -> list[dict]:
    """One row per (CAID component, evidencing step). HAL-03 counts the unevidenced ones.

    `unevidenced` is true when the step has no decision at all, or when every decision on
    it is hollow with no blind reading. A step whose only record is a ratified machine
    proposal has a human in the loop on paper and none in evidence.

    `blind_absent` is reported separately and deliberately NOT folded into `unevidenced`:
    decisions.record() accepts blind= and no caller passes it, so a zero there is an
    unwired field rather than reviewer conduct.
    """
    quality = {(r["use_case"], r["step"]): r
               for r in step_decision_quality(path or D.LOG)}
    rows = []
    for c in uc_components(root):
        if c["declared_domain"] != "CAID" or c["stale"] or c["has_errors"]:
            continue
        for step in c["evidencing_step_ids"]:
            q = quality.get((c["use_case"], step))
            rows.append({
                "use_case": c["use_case"],
                "component_id": c["component_id"],
                "step": step,
                "decisions_n": (q or {}).get("n", 0),
                "substantive_n": (q or {}).get("substantive_n", 0),
                "blind_n": (q or {}).get("blind_n", 0),
                "rubber_stamp_n": (q or {}).get("lane_b_rubber_stamp_n", 0),
                "no_decision": q is None,
                "blind_absent": (q or {}).get("blind_n", 0) == 0,
                "unevidenced": q is None or q["substantive_n"] == 0,
            })
    return rows


def oaid_step_coverage(root: Path, latest_lane_b: dict[str, dict] | None = None) -> list[dict]:
    """One row per (OAID component, evidencing step). HAL-04 counts the uncovered ones.

    `uncovered` is true when no control carries a play_ref to the step, or when every
    control that does returned an inconclusive verdict. An OAID component evidenced only
    by a judge proposal is uncovered — that is the boundary crossing, inside the tool.
    """
    cover = {r["step"]: r for r in lane_b_by_step(latest_lane_b or {})}
    rows = []
    for c in uc_components(root):
        if c["declared_domain"] != "OAID" or c["stale"] or c["has_errors"]:
            continue
        for step in c["evidencing_step_ids"]:
            cv = cover.get(step)
            rows.append({
                "use_case": c["use_case"],
                "component_id": c["component_id"],
                "step": step,
                "controls": len((cv or {}).get("control_ids", [])),
                "controls_with_real_verdict": len((cv or {}).get("real_verdict_control_ids", [])),
                "no_control": cv is None,
                "uncovered": cv is None or not cv["real_verdict_control_ids"],
            })
    return rows
