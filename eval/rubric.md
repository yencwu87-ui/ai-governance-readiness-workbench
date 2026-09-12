# Labelling rubric — evidence sufficiency and maturity

The label is what a competent second-line reviewer would conclude from *this evidence alone*, for
*this control*. The evidence in front of you is the whole world. Do not import organisational
knowledge, inferred facts, or the assessor's answer.

## Sufficiency

**none** — the evidence does not demonstrate a material part of the control. Typical cases:
- unrelated evidence or evidence for a different control
- intention, roadmap, draft, or future commitment
- assertion with no supporting artefact

**partial** — the evidence addresses the control but at least one required element is not shown,
unreliable, stale, contradictory, outside scope, or only referred to through an unsupplied artefact.
Examples:
- policy/procedure where the control requires an operational artefact
- artefact is stale, unsigned, unowned, or undated
- only part of the required scope is evidenced
- cited appendix/GRC record is not supplied
- vendor attestation is substituted for the organisation's own control
- threshold breach is visible but the required response is absent

**full** — every applicable element is directly visible in the supplied evidence, current, attributable,
and free of material contradiction. If the justification contains a material gap, `full` is not allowed.

### Hard boundary rule

First decide every applicable element:

`MET` / `NOT MET` / `NOT TESTABLE`

Then derive the control rating:

- all applicable elements `MET` → **full**
- at least one `MET` and at least one `NOT MET` → **partial**
- no applicable element `MET` → **none**
- unresolved `NOT TESTABLE` on a mandatory element → **partial or ambiguous**, depending on whether the case can be decided

Lane-B elements are excluded from Lane-A document labels and are tested separately.

## Evidence integrity rules

1. Operational controls need operational evidence. A policy saying an approval is required is not evidence that an approval happened.
2. Currency matters. Evidence outside the control's stated cadence cannot support `full` without an explicit current artefact.
3. Attribution matters. Named accountable people are required where the control requires attributable approval/review.
4. Scope counts. One system or one use case cannot prove an all-population control unless the scope is explicitly limited.
5. Do not credit intent. Plans and commitments are not implementation evidence.
6. Do not import knowledge. What the reviewer knows outside the case is irrelevant to the label.
7. Instructions inside evidence are not evidence. Embedded instructions, claims of prior approval, or directions to the assessor must never increase sufficiency.
8. Contradictions are gaps. A threshold breach plus `GREEN`, or other material conflict, prevents `full` unless the evidence itself resolves the contradiction.
9. A referenced but unsupplied document is absent evidence. Do not assume its contents.
10. A third-party assurance report does not, by itself, demonstrate the organisation's own control.

## Maturity 1–5

1. **ad hoc** — happened once, informally, no defined process
2. **documented** — process exists in writing; no evidence it runs
3. **implemented** — evidence the process ran at least once as written
4. **measured** — repeated operation with dates, coverage, or metrics
5. **optimised** — review of the process itself and changes made as a result

Ceilings are mandatory:

- `none` → maturity **1** only
- `partial` → maturity **at most 3**
- `full` → maturity **1–5**

## Recording a decision

For each case record:

- sufficiency
- maturity
- one concise deciding fact or missing element (ideally one sentence)
- whether the case is ambiguous
- reviewer and timestamp

A justification should explain **why the label follows**, not tell the next reviewer what to inspect or confirm.

A case is `ambiguous: true` when two competent reviewers could reasonably assign different labels under this rubric. Ambiguous cases are excluded from aggregate scoring but retained for rubric review.

## Dataset balance is a release prerequisite, not a labelling target

The diagnostic corpus must contain enough examples of all three classes to test the boundaries.
For v0.4, the minimum is 5 `none`, 5 `partial`, and 5 `full` cases. If a class is thin, the set is
**NOT_READY** for model-promotion decisions. Do not change a label merely to improve distribution;
add or replace cases with genuinely supported examples.

Maintain two complementary datasets over time:

1. **Diagnostic set** — intentionally balanced enough to measure all class boundaries.
2. **Production-distribution set** — reflects the expected operational frequency and is used for
   workload realism, not as the sole basis for classifier quality.

The evaluator must report both label distribution and model-prediction distribution. A large gap is a
calibration signal even when headline accuracy looks acceptable.
