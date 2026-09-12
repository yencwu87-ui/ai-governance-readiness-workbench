# WB-030 rev 2 — domain classification and the Halocline checks

Supersedes rev 1. Rev 1 was drafted without the code. Reading `lifecycle_cards.py`,
`decisions.py` and the 51-record log changed the unit of classification and retired two of
the five controls.

---

## 0. Why rev 1 was wrong

Rev 1 classified **use-case step cards** CAID or OAID, with the override question as the
binding rule: does any human evaluate this output before it influences the next step?

In this codebase that question answers `yes` for every step card, by construction.
`decisions.record()` refuses a write without a named reviewer, and `play_status()` will not
return `gate_passed` until every step of the play carries a decision. There is no path by
which a step's output influences the next play without a person having clicked. Declaring the
domain of a step card is therefore vacuous — HAL-02 would have passed 51 of 51 and measured
the architecture's own guarantee back to itself.

The log says what the real exposure is. All 51 records are `UC-001`, reviewer `wyc`, written
between 09:47:48 and 09:58:35 on 2026-09-06 — the entire 11-play lifecycle in eleven minutes:

| | count |
|---|---|
| records | 51 |
| reasons failing `reason_error` | 51 (46 empty, 5 the decision word) |
| records carrying a `blind` reading | 0 |
| Lane-B-fed proposals | 20 — 17 accepted with an empty reason |
| judge proposals | 5 |
| decisions with no proposal at all | 26, all `accept`, all empty reason |

The 20 Lane-B-fed steps are the sharpest case. In `lifecycle_cards.render()`, when a step is
covered by a control the proposal is written into `st.session_state` with no button press:

```python
if lb and not include_docs:
    if key not in st.session_state:
        prop = lane_b_proposal(lb)
```

The sufficiency selectbox then defaults to it, and Accept is one click. Seventeen times it was
one click with the reason box left blank.

So the step card is nominally CAID and evidentially empty. A component where a human is
present but demonstrably exercises no judgement is functionally OAID whatever the design says.
**The override question does not need declaring. It needs measuring.** That is the check worth
building, and the machinery is already in the repo — `reasons.reason_error`, `decisions.hollow()`,
and the `blind` / `supersedes` fields added for exactly this.

## 0.1 What the two populations actually are

Rev 1 merged them. They are separate:

1. **The governed operation** — the components of the organisation's AI use case. This is where
   CAID/OAID is load-bearing and where the override question has a real, non-obvious answer.
   Register: `governance/uc_components.csv`. Controls HAL-01, HAL-02, HAL-05.
2. **The workbench's own review** — the 11 plays and their steps. Always CAID by construction,
   so nothing to declare. What it needs is evidence that the human judgement it assumes actually
   happened. Control HAL-03, reading `step_decisions.jsonl`.

HAL-04 joins them: an OAID component must be evidenced by a Lane B control, not by a judge.

---

## 1. `governance/uc_components.csv`

Plain UTF-8, no BOM, LF, edited as text.

| Column | Type | Rule |
|---|---|---|
| `use_case` | string | resolves via `usecases.load()`; matches the `use_case` key in the decision log |
| `component_id` | string | `UC-001.C1` style; unique within the use case |
| `component_name` | string | |
| `description` | string | what the component does — the text the classifier read |
| `spec_sha` | 64 hex | sha256 over `component_name` + `description`, canonicalised |
| `outcome_defined` | `yes`\|`no` | is the correct outcome defined in advance? |
| `correctness_verifiable` | `yes`\|`no` | checkable without judgement? |
| `errors_recoverable` | `yes`\|`no` | |
| `human_between_steps` | `yes`\|`no` | does a person act between this component and the next? |
| `judgement_required` | `yes`\|`no` | is quality subjective or complex? |
| `override_human_evaluates` | `yes`\|`no` | **binding** — does any human evaluate this output before it influences the next step? |
| `declared_domain` | `CAID`\|`OAID` | no third value |
| `evidencing_steps` | `;`-separated step ids | e.g. `P3.2;P6.1`; ids in `P<n>.<n>` form, matching `decisions.calibration()`'s `step.split(".")[0]` assumption |
| `rationale` | string | validated by `reasons.reason_error` |
| `classified_by` | string | a named person |
| `classified_on` | ISO 8601 date | |

Constraints carried over from rev 1 and still right: no `hybrid` / `unknown` / blank; no model
proposes a domain; `rationale` uses the one reason predicate rather than a second dialect.

**Step id format corrected.** Rev 1's template used `P01.S03`. The log and `calibration()` use
`P1.2`.

---

## 2. The derivation rule

Binding, on the component register:

```
override_human_evaluates == no  ->  declared_domain MUST be OAID
```

Advisory flags unchanged from rev 1 §2 — they report, they never overturn a declaration.

---

## 3. Controls

All report `records_examined` and honour the policy evidence floor.

### HAL-01 — component classification coverage
Population: every use case from `usecases.load()`. Rule: at least one component row, every
required column present and well-formed, `classified_by` a person, `rationale` passing
`reason_error`. A use case with no components is FAIL, not NOT_TESTABLE — the use case exists,
so the population is known. Waivable.

### HAL-02 — override consistency
Population: non-stale component rows. Rule: no row with `override_human_evaluates == no` and
`declared_domain == CAID`. Critical, non-waivable. Advisory flags reported alongside without
severity.

### HAL-03 — declared human evaluation is demonstrated *(replaces rev 1 HAL-03)*
Population: decisions in `step_decisions.jsonl`, grouped by `(use_case, step)`, for steps named
in the `evidencing_steps` of any CAID component.

Rule, per step:
- at least one decision with a reason passing `reason_error`, **and**
- not the pattern: every decision is `accept`, against a `source == "lane_b"` proposal, with a
  hollow reason and no `blind` reading.

The second clause is the functional-OAID test. A step that only ever ratifies a machine
proposal with no recorded reasoning has a human in the loop on paper and none in evidence.

Today this fails on every step: 51 of 51 reasons are hollow and 0 records carry a blind
reading. That is the correct result and the control should ship failing.

The `blind`-reading component of this check reports NOT_TESTABLE rather than FAIL until
`lifecycle_cards.py` starts passing `blind=` to `decisions.record()` — the parameter exists and
no caller uses it. Absence of a field no caller writes is not reviewer misconduct.

Waivable, with a dated expiry. The 51 existing records are append-only and cannot be honestly
retro-filled.

### HAL-04 — OAID components are evidenced deterministically
Population: non-stale rows where `declared_domain == OAID`. Rule: for each, at least one step in
`evidencing_steps` appears in some control's `play_refs` in `pipeline.latest_lane_b()`, and that
control's `machine_verdict` is a real verdict rather than an inconclusive one. An OAID component
evidenced only by a judge proposal is FAIL. Waivable.

### HAL-05 — classification staleness
Population: all component rows. Rule: recomputed `spec_sha` equals the recorded one. Stale rows
are excluded from HAL-02 and HAL-04 and counted here; if exclusion pushes those populations
below the floor they report NOT_TESTABLE. Waivable.

**Retired:** rev 1 HAL-06 (declared domain vs the runtime lane) is not needed once the register
describes the governed operation rather than the step card. `data_step = bool(lb) or
is_data_step(expected)` classifies which lane produces a *proposal*, which is a fact about the
workbench, not about the use case.

---

## 4. Gate wiring

```yaml
golden_state:
  classification:
    register: governance/uc_components.csv
    unit: component                  # of the governed use case, not of the review process
    permitted_domains: [CAID, OAID]
    classifier: named_person
    binding_rule: override_human_evaluates
    stale_on: component_spec_change
  oversight:
    decision_reason: reasons.reason_error   # one rule, already imported by every write path
    blind_reading: recommended              # NOT_TESTABLE until a caller passes blind=

gates:
  play_exit:
    inconclusive_on: [HAL-01, HAL-05]
    non_waivable: [critical]
```

---

## 5. Adapter corrections against the real code

| Rev 1 assumed | Actually |
|---|---|
| `use_case_id`, `play_ref` keys in the log | `use_case`, `step` |
| step ids `P01.S03` | `P1.2` |
| `usecases.csv` read as CSV, with a `status` column | `usecases.load()`; no status column, every loaded case is live |
| a local `_hollow()` predicate | `from reasons import reason_error` — `decisions.py` states the rule lives in one place and is imported by every write path; a second copy is the exact defect that was fixed |
| bundle status vocabulary invented | `pipeline.latest_lane_b()` rows carry `control_id`, `play_refs`, `machine_verdict` |
| reparse the JSONL | `decisions.load()`, `decisions.latest()`, `decisions.hollow()` already exist |
| sha over a whole step card | sha over `component_name` + `description` only |

Check names still need registering in `schemas/control.schema.json` before the pack validates.

---

## 6. What this does not catch

- A person can answer the six questions untruthfully. HAL-01 and HAL-02 bind the declaration to
  itself; HAL-03 and HAL-04 bind it to the record.
- HAL-03 measures whether reasoning was *recorded*, not whether it was *sound*. A reviewer who
  writes forty plausible characters passes.
- `spec_sha` covers the description the classifier read. A component whose description is
  unchanged but whose implementation became agentic will not go stale.
- HAL-04 proves a Lane B control exists and returned a verdict, not that it tests the right
  thing.
