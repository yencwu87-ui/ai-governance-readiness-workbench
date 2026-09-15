# WB-103 / WB-104 — the completeness pass, and element identity

Built on the WB-102 package. 429 passed, 1 skipped, 0 failed.

---

## WB-103 — completeness pass

`governance/completeness.py`, wired into `core/cycle.py` as `gap_scan()` and
`rebind_evidence()`.

### The order

```
scan → gap_scan (deterministic) → human tops up → rebind_evidence → blind read
     → assess → compare → challenge → decide
```

`proposal_for_reviewer()` still returns `None` until a read is recorded. Blindness is unchanged.

### Why the gap scan can run before the blind read

Because it returns no verdict. It answers one question — which declared artefacts have no
candidate document — and nothing else. `test_the_pass_never_emits_a_rating_or_an_element_verdict`
asserts that no key named `sufficiency`, `maturity`, `elementVerdicts`, `element_verdicts` or
`rating` appears anywhere in its output, at the top level or in any artefact row.

A list of what is missing carries no opinion about what is met, so there is nothing for the
reviewer to agree with. That is the entire difference between this and the assessor-first
ordering, and it is why this one is safe.

### Why it is not the assessor

"Declared artefact X has no candidate document in this bundle" is a matching problem. Answering
it with code gives a reproducible result with a counted population that can be tightened when it
misfires. You have the precedent: WB-022's first artefact matcher used two-way substring and read
a gap reading "Validation & test reports for the specific test cases..." as total absence.
Tightening that rule moved the corpus probe 1/6 → 2/6 → 4/6. There is nothing to tighten in a
paragraph of model prose.

The matching rule, and what each part is defending against:

| rule | why |
|---|---|
| Share ≥2 content stems with the artefact name (or the single stem, for one-word artefacts) | Substring matching over-fires. "reports" occurs in almost any governance document. |
| Filename hits and body hits reported separately | `change_records_Q1.xlsx` is a change record. A policy *describing* what change records should contain is not one. Filename hit → `present`; body-only → `ambiguous`. |
| Category labels reported `unmatchable` | The workbook artefact column often holds a category ("as applicable") rather than a nameable artefact. That cannot be found or not found, so it is not counted as a gap. |
| Below the document floor → `NOT_TESTABLE`, `gaps` empty | Finding nothing in an empty folder is a fact about the bundle, not about the organisation. This is the check that would have refused the Lane A scan that produced 78 partials against the tool's own outputs. |

Statuses are `present` / `ambiguous` / `absent` / `unmatchable` / `NOT_TESTABLE`. Never
`met`.

### Top-up and re-bind

`rebind_evidence()` exists because a bundle assembled against a checklist is not an independent
sample of what the organisation had. It records `evidence_added_after_gap_scan`, for the same
reason `label.py` records `assessor_shown` — the number stays usable, but not as eval material,
and the record says which rather than leaving a later reader to guess.

It also closes the ordering. `assess()` now compares the current bundle hash against
`bundle_hash_at_scan` and refuses when the bundle moved without a recorded re-bind, so the blind
read, the assessment and the challenge cannot end up attacking three different objects.

One refusal worth knowing about: `rebind_evidence()` rejects a top-up after a read has been
recorded. Editing the bundle under an existing reading would leave that reading attached to
evidence it never saw. Start a new cycle instead.

`events.py` folds `gap_scanned` into the cycle projection. It deliberately creates no stage —
completeness is a bundle fact, not an assessment step.

---

## WB-104 — element identity

`governance/element_identity.py` and `tools/element_identity.py`.

### The answer to "are the element IDs good"

No. Not understanding them is the correct reaction, and the previous M3.6 contract proves it
without needing an argument.

`e1, e2, e14` are ordinals. `draft_one` assigns them with `f"e{len(elements) + 1}"`, so the id
records the order the element came out of the drafter and nothing else. It is not a name.

That would be harmless if it stayed inside one version. It does not — element ids are the join
key for reviewer verdicts in `compare.py`, the challenger's `requirement_pointer.element_id`,
`step_decisions.jsonl`, the corpus a/b/c labels, `M3.6_element_decisions.yaml`, and
`element_testing.yaml`. Every stored judgement in this system hangs off a positional number.

The prior contract ran `e1, e2, e3, e3b, e4, e4b, e5, e5d, e5b, e5c`. Those suffix letters are
what happens when a scheme with no room for insertion has to take one: a new obligation was
needed between `e3` and `e4`, no number was available, so the id grew a letter. `e5d` sits before
`e5b`. That is the identifier telling you it cannot carry the load.

The bill arrived at the 10 → 14 revision. Ten elements carried real per-document labels and not
one could be carried across, because there was no way to ask whether old `e3` and new `e3` were
the same obligation. The ids matched and the requirements did not.

### What replaces it

Two handles derived from the obligation itself:

- **uid** — `el-<10 hex>` over the normalised text. Same obligation, same uid, any contract, any
  order. Reword it and the uid changes, which is correct: that is precisely the event that should
  invalidate a stored label rather than let it be silently inherited.
- **slug** — `independent-validation-before-deployment` rather than `e7`. A handle a reviewer can
  hold in their head and a disagreement can be conducted in.

`diff_contracts(old, new)` then answers the previously unanswerable question. Identical
obligations **carry** their labels automatically. Similar-but-not-identical ones are **proposed**
with their similarity and never applied — rewording an obligation can change what evidence
satisfies it, and only a person can say whether it did. Everything else is **new** or **retired**,
and retired elements are named with their labels so orphaned judgements are visible rather than
lost.

Similarity is Jaccard over content terms, deliberately not an embedding. A score used to propose
a carry-over has to be inspectable by the person deciding — they can see which words two
obligations share. A cosine gives them a number to defer to, which is the wrong relationship to a
judgement they are meant to be making.

### The real M3.6 revision, measured

`tools/element_identity.py --old requirements/contracts/M3.6_elements_v1_10el.yaml --new eval/corpus/M3.6/elements.yaml`

```
10 element(s) -> 14 element(s)

  carried automatically        0
  proposed for a person        0
  need fresh labels           14
  retired                     10   stored judgements now orphaned
```

The highest similarity to any prior obligation is 0.308. Nothing came close to the 0.62 near-match
threshold. So the decision to abandon the ten labels was right — and it is now demonstrated rather
than asserted, with the retired list naming exactly which judgements were lost
(`validation-recorded-outcome-dated` held `a: Y`, and so on).

The prior contract is preserved at `requirements/contracts/M3.6_elements_v1_10el.yaml` so this
stays reproducible.

`duplicate_obligations()` also catches something `validate_elements` structurally cannot: two ids
carrying the same requirement. That check rejects a duplicate *id*; it has never been able to see
a duplicate *obligation*, which is the thing that actually inflates an element count.

### Scope

This is additive. `e1..e14` remain the display ordinals and no existing consumer was repointed.
Migrating the join key to uids touches `compare`, `challenge`, `step_decisions`, the corpus and
the decisions file, and is a separate decision with its own blast radius — worth doing, not worth
doing quietly inside another ticket.

---

## Still open

The challenger will still restate your read. That is the quote gate, unchanged here: every
challenge needs `factual_pointer.quote` copied verbatim from the evidence, which makes absence,
reasoning and scope challenges impossible to express. It needs the absence pointer and the
reviewer pointer, and it is independent of everything above.

---

## WB-105 — the UI wiring that WB-103 was missing

WB-103 built the completeness pass in `core/cycle.py` and did not touch `app.py`. The flow
existed headless and nowhere else. This closes that.

### What was added to the Review workspace

A **Completeness** step now sits between Evidence and Your reading, in
`_render_review_progress` and in the step machine. "Save evidence & continue" runs `gap_scan()`
and lands there instead of jumping to the reading.

The step shows the per-artefact result — `✓` named document, `~` mentioned only in a body, `✗`
no candidate, `—` the declared artefact is a category label, `?` bundle too thin — with the
matched terms and the document each hit came from. It shows the bundle hash and the document
count. It shows no rating, because the pass produces none.

"Add evidence & rescan" appends the top-up as a `reviewer_topup` source, calls
`rebind_evidence()` and re-runs the scan. Continuing is always available: **open gaps do not
block the reading.** A gate there would push a reviewer to fill boxes, and recording that
someone read incomplete evidence is more useful than a forced clean bundle.

`review_queue.project_control` now returns `has_completeness`, `completeness_gaps`,
`completeness_testable` and `evidence_topped_up`, so the queue can show scan state. In the
progress bar the step is done when the scan has *run* — gaps are a result, not an unfinished
step.

### The larger finding

`app.py` calls four cycle functions — `start`, `bind_evidence`, `record_read`, `decide` — and
writes `proposed`, `compared` and `challenged` to the event log directly. The middle of the
cycle is implemented twice: once in the library, once in the UI.

`core/cycle.py` was extracted precisely to stop that, and its own docstring says a UI is not a
control. The extraction happened; the migration did not. The practical consequence is that any
guard added inside `assess()`, `compare_reads()` or `challenge()` does not exist for anyone
using the app — including WB-103's own bundle-hash check, which was written inside `assess()`.

Fixed for this guard by making it public: `cycle.check_bundle_unchanged(cycle_id, evidence)`,
called at all three review-path `proposed` writes in `app.py`. It is a no-op on an unknown cycle
or where no scan has run, so it can never be the thing that breaks a review.

Not fixed generally. `cycle.challenge()` raises when there are no disagreements and
`compare_reads()` refuses without a recorded read; neither guard reaches the UI, because the UI
writes those events itself. Routing `assess`, `compare_reads` and `challenge` through the library
is the right next change and is its own ticket — it touches the Streamlit control flow in several
places and deserves to be done deliberately rather than inside this one.

### Verification

433 passed, 1 skipped. Four new tests cover the UI path: that completeness and the challenger
split evidence with the same function (a gap nobody can quote against is unfalsifiable), that
manual evidence is one document rather than several, that the bundle guard is public and
callable outside `assess()`, and that the review row exposes completeness without gaps blocking
progress.

---

## WB-106 — the two step indicators disagreed

Two defects visible in one screenshot of the Review workspace.

**Three hand-maintained step lists.** `_render_review_progress` carried seven steps; three
inline `stages(...)` calls inside the step blocks each carried their own five. WB-105 added
Completeness to the first and not the others, so the pill row read
Evidence · Completeness · Your reading · AI assessment · Compare · Challenge · Decision while the
strip directly beneath it read Evidence › Your reading › AI assessment › Compare › Decision —
Completeness and Challenge simply absent. My error in WB-105, and the kind that recurs as long
as the list is written down more than once.

There is now one definition, `REVIEW_STEPS`, and one projection, `_review_step_states(row, current)`.
Both indicators render from it. A test asserts no inline strip comes back and that only one
`REVIEW_STEPS` definition exists.

**A ticked step ahead of the step that gates it.** `AI assessment` showed a green ✓ while
`Your reading` was still the current step, because the assessor runs concurrently so the reviewer
never waits on it. No rating leaked — `proposal_for_reviewer()` still withholds it — but the tick
announced that a proposal was ready and had succeeded, which is a nudge to hurry the reading, and
it made the enforced order look broken in the one place that advertises the order.

There is now a fourth display state, `held`, rendered `⏸` with the caption *"The assessor has
finished and its proposal is withheld until your reading is recorded."* Ready-but-gated instead
of done.

**One stale test rewritten.** `test_stage_includes_ai_assessment_state` grepped `app.py` for the
literal `("AI assessment",`, which pinned the hand-written lists in place — the test was holding
the defect. It now calls `_review_step_states` and asserts what the strip contains rather than
how it is spelled.

438 passed, 1 skipped.

---

## WB-107 — one crash, and the same conflation in three more places

### The crash

`app.py` line 1401 raised `KeyError: 'aiSufficiency'` on **every** decision recorded through the
review workspace, not on an edge case. The line guarded with `d.get('aiSufficiency')` and then
read `d['aiSufficiency']`. `cycle.decide()` has never written that key — only
`pipeline.record_decision` does, and the app no longer uses that path — so `.get()` returned
`None`, `None != 'partial'` was true, and the body raised every time.

The bug underneath the crash is the interesting one. The guard read `None != 'partial'` as *the
AI proposed something different*. Absent is not a value. There are three cases and the report now
names each: the assessor agreed, the assessor proposed something else, or the assessor produced
nothing. Reporting a missing or failed assessment as a difference of opinion would have written a
disagreement into the record that never happened.

### The Challenge step showed ✓ on a pass that produced nothing

In the second screenshot the challenger had just failed with an Ollama timeout — the app said so
correctly, *nothing was recorded and your reading stands unchallenged* — and the progress bar
showed a green ✓ beside **Challenge** with the next action set to Record decision.

`challenge_counts` counted rows. Zero rows meant zero unresolved meant done. But zero rows has
three causes:

| cause | before | now |
|---|---|---|
| ran cleanly, nothing to say | ✓ done | ✓ done |
| ran, output failed validation | ✓ done | ⚠ blocked |
| never ran | ✓ done | · waiting |

It now returns `ran`, `blocked` and `produced_a_result`, and the step is complete only when a
pass actually produced a result. A blocked pass renders ⚠ with the caption *"The challenge pass
ran but no challenge survived validation. Your reading is unchallenged — this is not the same as
nothing being found."*

### The dossier called a blocked run `no_challenges`

Third screenshot: *"Challenge blocked after structured validation failure; no challenge was
admitted"* followed by `status: no_challenges`. The prose was right and the stored field was
wrong, and the stored field is the one an auditor reads later.

`create_dossier` now takes `validation_status`, sets `status` and `challenge_outcome` to
`blocked`, and records `reading_was_challenged: false`. An unchallenged reading and an
unchallengeable run are different records.

### Why this keeps happening

WB-102 fixed exactly this distinction in `decision_engine.evaluate()` and I treated it as done.
It was one instance of a rule this system holds everywhere — `compare.py` for the assessor call,
the evidence floor for thin bundles, `propose()` refusing to manufacture a `none` from a failed
call. Three more places were still counting rows and calling silence success, and all three were
on the screen rather than in the log, which is why they surfaced only when you used it.

445 passed, 1 skipped. Nine new tests cover the three fixes.

---

## WB-108 — the queue row, fourth location of the same bug

Asked what the ticks on the review-queue rows mean, and the answer was `AI ✓ · Read —`.

WB-106 fixed the workspace progress bar to show a ready-but-gated proposal as `⏸ held` rather
than ticking it ahead of the blind read. The queue row was left alone, and it is the more
exposed of the two: it is the first screen, and it announced a finished proposal on every row
at once, before the reviewer had read anything.

The row also showed four of the seven steps — Completeness and Challenge were missing, the same
drift WB-106 was meant to end.

`_queue_markers(row)` now derives from `REVIEW_STEPS` via a `QUEUE_LABELS` map, with a test
asserting `set(QUEUE_LABELS) == set(REVIEW_STEPS) - {"decision"}` so a step added to the workflow
cannot silently drop out of the queue summary. Decision stays out because the row already carries
it as its `Next:` label.

Marker semantics, now consistent with the workspace:

| | meaning |
|---|---|
| `✓` | step produced a result |
| `⏸` | assessor finished, withheld pending the blind read |
| `!` | assessor call errored |
| `⚠` | challenge ran, nothing survived validation |
| `—` | not run |

Before: `Evidence ✓ · Read — · AI ✓ · Compare —`
After: `Evidence ✓ · Completeness — · Read — · AI ⏸ · Compare — · Challenge —`

450 passed, 1 skipped.
