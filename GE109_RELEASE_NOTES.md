# GE-109 — the event/control-plane boundary

Built on WB-108. **477 passed, 1 skipped.** Six increments.

The rule, stated once: **the UI may not write to the governance ledger.** It asks `core.cycle`
to, and `core.cycle` decides whether the write is allowed.

---

## Increment 1 — `gap_scanned` registered, and the guard that should have caught it

`events.append` rejects any kind not in `KINDS`. `gap_scanned` was never added, so
**`cycle.gap_scan()` raised `ValueError` on every call from the day it shipped in WB-103.** The
WB-103 tests exercised `completeness.scan` directly and never went through the cycle, so nothing
caught it.

`KINDS` now has it. More usefully, `test_every_kind_the_cycle_appends_is_registered` parses
`core/cycle.py`, collects every literal passed to `events.append`, and asserts each is in
`KINDS`. The next omission fails at test time rather than at the reviewer's first click.

## Increment 2 — cycle functions for every write the UI legitimately needs

The UI could not route through the cycle because for five of its writes there was nothing to
route to. `assess()` both runs the assessor and writes the result, but the UI runs `propose()`
on a background thread so the reviewer is never blocked, and only has a finished proposal to
hand.

| new function | guard it carries |
|---|---|
| `record_proposal` | refuses a failed call (`is_error`) — `propose()` returns `status: "error"` with no sufficiency rather than manufacturing a `none` (WB-021), and writing that would record a rating the assessor never made. Also runs `check_bundle_unchanged`. |
| `record_compare` | refuses a diff that does not say whether it was comparable. NOT_COMPARABLE is a result and is recorded; a dict missing the field is not a comparison. |
| `challenge_read` | first-pass challenge (attacks the reviewer's reading), distinct from `challenge()` which is scoped to the disagreement. Refuses without a recorded read. |
| `record_challenge` | refuses an empty record — a pass that produced nothing must still say which of the three it was: ran clean, blocked, never ran. |
| `record_note` | requires a named actor, same reason `decide()` does. |
| `record_observation` | widened to take `control_id`/`framework`; refuses an empty observation. |

## Increment 3 — eight direct writes routed

`proposed` ×4, `compared`, `challenged`, `note`, `observed`. `events.append(` count in `app.py`:
**8 → 0**.

## Increment 4 — reads stay

The boundary is on writes. `events.state`, `events.decided`, `events.cycle` remain in the UI and
a test asserts they do, so nobody "fixes" the boundary by banning the module — the UI has to
project governed state to render anything honest.

## Increment 5 — `assessments.json` demoted to cache in fact, not in comment

The file already carried a comment saying it was cache only. It wasn't:
`_sync_authoritative_decisions` overwrote `decisions` only `if projected`, so a cache holding
decisions and a ledger holding none left the cache standing as the record.

`_LEDGER_OWNED = ("decisions",)` is now stripped on load and rebuilt from the ledger
unconditionally. Deleting `assessments.json` must cost the reviewer their scan folder and their
scroll position, never a decision. A behavioural test loads a state file containing a decision
and asserts the org name survives and the decision does not.

## Increment 6 — `tests/test_ge109_boundary.py`, 27 tests

AST check (no `events.append` in `app.py`), textual check for dynamically built calls, KINDS
completeness, a parametrised check that `core.cycle` exposes and publishes every write the UI
needs, four guard tests, and two cache tests.

One note on the AST check: the first version matched any `.append(` and flagged six
`rows.append("LOCAL")` calls. It now matches on the full attribute path.

---

## Found while verifying: the declared-artefact column is corrupted for two controls

Running the cycle end to end against the workbook in `data/`, the completeness pass reported
these as M3.12's missing artefacts:

> Change categories, impact assessment, required testing and approval criteria are defined.
> Post-implementation verification and closure or exception handling are required.

Those are requirement sentences, not artefact names. Checking across the MAS library:

| control | declared artefacts |
|---|---|
| M1.2 | `AI use policy` ✓ |
| M2.3 | `Approved materiality methodology defines impact, complexity and relian…` — element text |
| **M1.1** | `Evaluation measures aligned to the AI's objectives and acceptable perf…` — **M3.6's elements** |
| M3.6 | same string as M1.1 |
| M3.12 | element text |

M1.1 is board and senior management accountability. It is carrying M3.6's evaluation elements.
29 of 30 artefact strings are distinct, so this is not systemic broadcast — it is a handful of
controls whose column has been overwritten, and it matches the known `write_back` defect: the
exported workbook has its "Evidence / artifact" column overwritten with evidence text, and
`data/` currently holds an exported file (`…_requirement_elements_audited.xlsx`).

Consequence: the WB-103 completeness pass matches against whatever that column holds. For the
two pathfinder controls you work on most, it is matching against requirement sentences, which no
document will ever be named after. The pass is not wrong; its input is. Fixing `write_back` to
leave the column alone, and restoring the column from a clean source, is the prerequisite for
completeness output being worth reading on M3.6 and M3.12.

---

## Target architecture — feasibility

Roughly seven of the ten layers already exist. The three that do not are the three that would
change the shape of the system.

| layer | state |
|---|---|
| Authoritative policy | **exists** — `policy/ai-lifecycle.yaml`, `requirements/mas.yaml`, versioned source registry with lifecycle status |
| Governance contracts | **mostly** — controls, elements, gates all exist. **Applicability does not.** |
| Verification planner | **does not exist** — the largest gap |
| Providers / evidence / human review | **exists** — `caa/adapters`, `scanner`, `core.cycle` |
| Observation store | **exists** — hash-chained append-only ledger with provenance |
| Predicate engine | **partial** — the caa runner evaluates, but predicates are embedded in adapters rather than first-class |
| Control results | **partial** — PASS/FAIL/NOT_TESTABLE exist. **STALE does not.** |
| Finding / state | **partial** — history exists, a finding state machine does not |
| Decision engine | **exists** — `governance/decision_engine.py` |
| Governance posture | **exists** |
| No remediation | **already true** |

### The one thing the target resolves that you have been working around

The diagram has a single pipeline. You have two lanes — Lane A judgement and Lane B
deterministic — and they have never sat comfortably together.

The target dissolves that, and the resolution is in the layer ordering. The assessor's proposal
is not an evaluation, it is an **observation**: a model, given this evidence, under this prompt,
with this retrieval receipt, produced this reading. It belongs in the observation store with its
provenance, alongside a provider's API response and the reviewer's blind read. The predicate
engine then evaluates deterministically over observations, and a predicate can legitimately say
"reviewer and assessor agree on element e9 and both cite a verbatim excerpt" without ever asking
a model to decide anything.

That is a better fit than what you have now, and it is the argument for the target rather than
just a redrawing of it.

### What is genuinely new work

**Verification planner with capabilities** is the piece with no analogue. It answers "can this
control be tested in this environment at all" before anything runs — which is the evidence floor
and NOT_TESTABLE generalised from a per-check afterthought to a planning input. The completeness
pass is its natural first tenant.

**Applicability** is the smaller gap but shows up everywhere once you have it: five of M3.6's
fourteen elements are conditional on "where relevant", and mutual `not_applicable` is currently
handled as a compare-time special case rather than as a declared property.

**STALE as a first-class result** is the staleness cascade — an artefact whose inputs changed
is neither PASS nor FAIL. You have the input hashes to compute it.

### Sequencing, and the honest risk

Order: applicability → predicates first-class → STALE → planner. Each is usable alone, and the
planner is last because it needs the other three to plan over.

The risk is not technical. It is that this is a rewrite of the middle of a system whose
measurement loop does not currently work — the challenger has admitted zero challenges in every
run you have shown me, and M3.6's corpus is 42 unlabelled cells. Rebuilding the engine while
blind means you cannot tell whether the rebuild made anything better.

Fix the challenger and label one corpus first. Then the architecture has something to be
measured against.
