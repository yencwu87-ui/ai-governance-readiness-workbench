# Proposed amendment to policy/ai-lifecycle.yaml — v1.2.0 → v1.3.0

**Not applied.** `policy/` is a governed path: the file's own header states that an edit
without a ticket reference fails MCM-06, and the bundle records the file's hash next to every
verdict. So this is a proposal to be tabled, not a change made. Raise a ticket, amend
`amends:` and `version:`, regenerate POLICY.md, and let MCM-06 see the ticket.

---

## The gap

`governance/link_check.py` reports it directly:

```
Lane B coverage: 7 of 30 controls
Of those, severity CRITICAL and untested by any pack:
  F1, F3, M1.1, M3.7, M3.9, M3.11
```

The policy says `non_waivable: [critical]`. That rule can only bite on a control that
produces a machine verdict — the gate reads bundle results, and a bundle only contains what a
control pack produced. Six controls now marked critical in `requirements/mas.yaml` have no
pack at all. They are assessed by a model reading documents, and the assessor's output is a
*proposal*, never a verdict.

So today the policy asserts an obligation it cannot enforce over a fifth of the critical
population, and nothing in the repo says so. That is the same shape as the inert BM25
threshold in WB-019 and the disconnected slider in WB-023: a control that reads as operating
and is not.

## What the amendment does

It does not paper over the gap. It makes the policy state which lane a control's assurance
comes from, and what the gate may conclude from each.

### 1. New block: `assurance_lanes`

```yaml
assurance_lanes:
  # Which lane produces the assurance for a control, and what a gate may conclude from it.
  #
  # lane_b — a control pack produces a machine verdict, signed by a named reviewer. This is
  #          the only lane a gate can act on. fail_on / inconclusive_on read these.
  # lane_a — an assessor proposes an evidence-sufficiency rating from documents and a named
  #          reviewer records a decision. A gate must NOT read a Lane A rating: the rating is
  #          a judgement about documents, not a test of an operating control, and the
  #          assessor has no write path by design.
  #
  # A control whose only assurance is lane_a cannot be gated. Saying so is the point: the
  # alternative is a gate that appears to cover it and does not.
  lane_a:
    may_produce: [proposal, reviewer_decision]
    may_gate: false
    recorded_in: data/assessments.json, governance/step_decisions.jsonl
  lane_b:
    may_produce: [machine_verdict, human_verdict]
    may_gate: true
    recorded_in: evidence/

  # Severity floor at which a control is expected to have Lane B assurance. Controls at or
  # above this floor with no pack are reported by governance/link_check.py and are a
  # programme gap, not a build failure — the runner does not fail on them, because failing on
  # a control nobody built is noise. They are re-tabled at the monthly forum with exceptions.
  lane_b_expected_at_or_above: critical
```

### 2. Amend `gates` to say what non_waivable actually covers

```yaml
gates:
  ...
  non_waivable: [critical]
  # Scope: applies to controls producing a machine verdict (assurance_lanes.lane_b). A
  # critical control with Lane A assurance only is outside this rule — not because it is less
  # important, but because there is no verdict for an exception to waive. Coverage of critical
  # controls by Lane B packs is reported by governance/link_check.py and tracked as a
  # programme gap.
  non_waivable_scope: lane_b
```

### 3. Amend `evidence_floor` for the same reason

The floor turns a PASS into NOT_TESTABLE below a minimum examined population. It has no
meaning for Lane A, where there is no population count — the assessor read whatever retrieval
returned. Add:

```yaml
evidence_floor:
  applies_to: lane_b
  # Lane A has its own floor, enforced in assessor.py rather than here: a rating with no
  # surviving verbatim excerpt is downgraded to "none" (WB-020), and an empty evidence body is
  # flagged rather than rated. Those are harness rules, not gate rules, and they cannot block
  # a deploy — only a reviewer can.
```

### 4. Reference the requirement text as governed

`requirements/mas.yaml` now carries requirement text, elements and severity that the assessor
reads at run time. It is load-bearing and currently ungoverned. Add to `scope:` or a new block:

```yaml
governed_paths_note: >
  requirements/mas.yaml supplies the requirement text and elements the Lane A assessor is
  judged against, and the severity the gates read. It is load-bearing: an edit changes what
  the assessor asks for. It should be a governed path under MCM-06 on the same footing as
  policy/.
```

---

## What this does not fix

**Six critical controls still have no machine test.** The amendment makes that visible and
honest; it does not close it. Closing it means writing control packs for F1, F3, M1.1, M3.7,
M3.9 and M3.11 — and several of those may not be machine-testable at all. M1.1 is board
minutes. F3 is an accountability matrix. Those are properly Lane A, and the right outcome may
be to mark them `lane_a_only: true` with a rationale rather than to build a pack that tests
a proxy.

Two of the six look genuinely testable and are the candidates:

- **M3.9** release gate — approval timestamp versus first production action is a data
  comparison. This is the control an examiner reaches for first, and it is binary.
- **M3.11** notification clock — discovery timestamp versus notification timestamp against a
  1-hour bound. Deterministic, given both timestamps exist.

**M2.2 SBOM** is a third candidate from a different direction: `requirements/mas.yaml` already
carries a `lane_b_candidate` note saying a generated SBOM either matches the running artefact
or it does not. M2.2 already has GOV-02, so this extends a pack rather than creating one.

## Suggested sequence

1. Table this amendment with a ticket. Nothing else here can be enforced until the policy
   admits which lane it is enforcing over.
2. Correct the DRAFT severities in `requirements/mas.yaml`. They decide what
   `non_waivable` and `evidence_floor` reach, so they are load-bearing and currently mine.
3. Build M3.9 and M3.11 packs. Two controls, both binary, both high-consequence.
4. Mark the genuinely-Lane-A controls as such, with a rationale each. A control correctly
   assessed by a human and recorded by a named reviewer is not a gap; an unmarked one is.
