# WB-102 — merge of the retrieval-plane build onto ge_14sep, and four honesty fixes

## What this package is

`ge_14sep` is the baseline. The WB-096..WB-101 build (`ge_WB101_multi_modal_retrieval_plane`)
was overlaid on top of it, and then five defects were fixed — four of them instances of the
same failure, plus one inverted guard.

**The baseline won on three files the overlay had dropped**, which matters more than it looks:

| file | why it was preserved from ge_14sep |
|---|---|
| `governance/events.jsonl` (955 KB) | The append-only ledger. The WB-101 package shipped without it, which is why the episodic retrieval lane returned zero results in every trial run — there was no history to retrieve. The lane was not broken; it was empty. |
| `governance/challenge_dossiers.jsonl` | Prior challenge dossiers. |
| `requirements/drafts/*.yaml` | The 14 Sep M3.6 and S4.2 element drafts, kept as the record of what the pre-guard decomposer actually emitted. |

Everything else was taken from the newer build: `governance/triangulation.py`,
`retrieval_plane.py`, `element_registry/contract/graph/rag.py`, `knowledge_monitor.py`, the
rewritten `knowledge_resolver.py` and `knowledge.py`, the `inference/` orchestrator, the
`requirements/triangulation/` artefacts, the updated `requirements/mas.yaml`, the 14-element
M3.6 contract, and the WB-096..101 tests.

## The one argument behind four of the five fixes

A governance record must never let a check that did not happen look like a check that happened
and found nothing. `compare.py` already held that line for the assessor — a failed call is
`NOT_COMPARABLE`, not agreement. Four places had not inherited it.

### 1. A blocked challenge run could clear a `full` rating

`challenge_disagreement()` no longer raises when structured validation rejects every candidate;
it returns `challenges: []` with `validation_status: "blocked"`. That envelope is correct. But
`governance/decision_engine.py` only ever read the challenge *rows*, so zero rows meant no
unresolved strong challenge, and a `full` came back **Adequate** — with no challenge having
survived at all.

`evaluate()` now takes `challenge_run` (the envelope, not the rows). A blocked run adds the
blocker `CHALLENGE_RUN_BLOCKED` to a `full` rating and forces posture `defer`.
`core/cycle.py:decide()` passes it via a new `_last_challenge_run()` helper.
`challenge_summary.run_completed` is `True`, `False` or `None` — the third value meaning no run
was recorded at all, which is also not success. Engine version 0.8.0 → 0.8.1.

### 2. The episodic receipt could not report its own failure

`retrieve_episodes()` wrapped the ledger read in `except Exception: return []`, and
`receipt_for()` hardcoded episodic as `completed: True, degraded: False, error: None`. A
missing or unopenable ledger therefore produced a clean receipt reporting zero episodes — the
exact confusion `WB101_MULTI_MODAL_RETRIEVAL_PLANE.md` says the receipt exists to prevent, in
the one lane that could not express it.

`retrieve_episodes()` now raises `EpisodicUnavailable`; `build_plane()` catches it and threads
the message into the receipt; `episodic` joins the `degraded` list.

Deliberately left alone: `events.read_all` turns a malformed *line* into a visible
`__unparseable__` record rather than throwing. That is the right behaviour and is unchanged.

### 3. `regulatory.attempted` was a constant

The expression was `bool(web_attempted) or True`, which can never be `False`. The field carried
no information. The registry half of the lane always runs and the web check may not, so they are
now reported separately: `attempted` (registry, always true), `web_attempted`, `registry_count`
and `web_count`. A non-zero count can no longer imply that the half which failed succeeded.

### 4. Mutual `not_applicable` counted as agreement

`compare.py` treated both sides answering `not_applicable` as a compared element that agreed.
Two people agreeing a requirement does not apply have said nothing about whether any requirement
was met. It is now reported as `n_scope_agreed` and excluded from the compared population, with
row `direction: "scope_agreed"`. Schema `wb030.compare.1` → `wb030.compare.2`.

This was about to bite: five of the fourteen M3.6 elements (e3, e4, e5, e7, e9) are conditional
on "where relevant". Under the old rule a reviewer and assessor who both marked all five
not-applicable would have scored 5/5 agreement on them and lifted the headline rate. Under the
new rule the compared population shrinks instead — which may fall below `MIN_COMPARED = 3`, and
that is the honest answer, not a worse one.

## 5. The element subject guard was inverted

Separate from the above, and the more embarrassing one. `_subject_markers()` read only the
clause *before* the first modal. Given the anchor

> An FI should ensure that **the AI system** is secure, well-governed, and supported by
> appropriate controls.

it extracted `{fi}` and stopped at "should", never seeing the nested real subject. The guard
therefore **rejected the faithful element** ("the AI system should be secure") as unsupported,
while **admitting the drifted one** ("the FI should be well-governed") — the precise error it
was written to catch, passed clean.

Anchors are now scanned whole; elements keep prefix scope. And where an anchor names more than
one actor, the guard does not pretend to know which one the predicate attaches to — that needs a
parser, not a token set. The element is neither dropped nor silently kept: it is flagged
`subject_ambiguous:<actors>` and surfaced in the draft and the render as `[subject unproven]`,
for a person to settle.

| element vs the anchor above | before | after |
|---|---|---|
| "The AI system should be secure" (faithful) | **dropped** | kept, clean |
| "The FI should be well-governed" (drifted) | **kept, clean** | kept, flagged |
| "The vendor should retain the model" (invented) | dropped | dropped |

### Also in the drafting tool

The headline count divided the *capped* selection by the offered count, so a selector that
accepted 15 of 18 sentences (83%) printed as "8/18 selected (44% selection rate)" — the header
was hiding the number the footer was warning about. It now prints the selector's own acceptance
and shows the cap separately.

The other guards from WB-071 were already present in the overlay and were verified rather than
rewritten. Against the eight defective elements the 14 Sep run actually produced, all eight are
now rejected and a real obligation survives:

- `of`, `and`, `for`, `taken`, `clear records` → `too_short_to_state_an_obligation`
- `Perform 25 formal independent validations` → `running_header_in_anchor` (the 25 was a page
  number), and `clean_instrument_text` strips the header before sentencing
- the two elements carrying a Training-and-Awareness anchor that does not contain them →
  `element_tokens_not_supported_by_own_anchor`

## Gate consistency

`tools/triangulate_requirements.py` reported `reviewable` / exit 0 on the M3.6 set while
`tools/validate_triangulation.py` reported `blocked` / exit 2 on identical inputs, because only
the latter loaded the human-decision file. Two gates that disagree are one gate and one rubber
stamp. The first tool now loads the decisions file (conventional path by default), refuses to
call an undispositioned set reviewable, and treats a *missing* decisions file as worse than a
file full of pendings. `--allow-pending` exists for exploratory runs and is recorded in the
report so it cannot pass for a clean result.

Both now return `blocked` on M3.6 — correctly, since all 14 elements sit at `pending_human`.

## M3.6 status, written into the file

`eval/corpus/M3.6/elements.yaml` now carries a header stating what it is. The 14 elements are a
**governed draft against consultation material**: both backing sources are `lifecycle_status:
proposed`, and the registry's own rule is that consultation material cannot establish canonical
requiredness. That is why the triangulation report returns all 14 as `future_change_signals`.
The header also records that the a/b/c labels are `?` by choice — the prior 7-element labels
were not carried across the 7 → 14 contract change, because a label decided against a different
requirement is not evidence about this one.

The cost is real and should be booked, not absorbed: M3.6 currently has no usable eval case, and
the known gap that it has no `full` case is now harder to close, since a `full` document must
satisfy fourteen elements rather than seven.

## Verification

413 passed, 1 skipped, 0 failed (`pytest tests/ test_*.py`).

`tests/test_wb102_fixes.py` adds 13 tests, each pinning a distinction the code previously could
not express — including that a blocked run and a silent run produce byte-identical
`challenges: []` and are told apart only by the envelope.

`tests/test_disagreement_pass_wb030.py::test_unverifiable_quote_is_rejected` was rewritten. It
asserted `pytest.raises(ValueError)` and was the last thing still holding the pre-soft-fail
contract; it now asserts the blocked envelope, and a companion test asserts that blocked and
silent runs are distinguishable.

`tests/test_v04_governance.py::test_ticket_register_references_are_reconciled` failed on the
first merged run — correctly, since WB-096..WB-102 had code but no register rows. Seven rows
were appended to `governance/tickets.csv` as text, preserving CRLF, with `approver:
NOT_RECORDED` and `record_status: historical_reconstructed` rather than inventing approvals.

## Not done, deliberately

The assessor-first UX reordering is not in this package. It would remove `proposal_for_reviewer()`
returning `None` — described in `core/cycle.py` as the blindness control expressed as code rather
than screen order — and it would starve the challenger, which is scoped by the disagreement and
raises when there is none. If it is wanted, the path is a declared mode in
`policy/ai-lifecycle.yaml` with its own gate consequence, not a screen preference.
