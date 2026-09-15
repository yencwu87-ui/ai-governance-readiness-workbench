# MGF Agentic D1.2 — Tiered Risk Classification Redesign

## Why this control was redesigned

The original D1.2 contract had one generic element:

> The organization must ensure that right-size controls to the level of risk.

That was not sufficient to support deterministic verification of an agentic risk-tiering process.

The Requirement Element Audit identifies six atomic obligations, and the MGF Agentic instrument provides the source context for why tiering is a load-bearing control rather than a descriptive label.

## Audited elements now in the governed contract

1. Approved methodology with defined criteria.
2. Tier/outcome thresholds stated by rule rather than unaided judgement.
3. Assessment completed before the decision it informs.
4. Outcome approved by a role independent of the requester.
5. Each outcome turns on a defined set of controls or gates.
6. Reassessment triggers are defined and detected.

## Instrument basis

The specification is grounded in:

- `instruments/Mgf_for_Agentic_AI_(atx_Release)_July_2026.txt`, section 2.1.1, which describes agentic risk as likelihood and impact and identifies relevant factors including domain/use case, sensitive-data access, external-system access, scope of actions, reversibility, autonomy, task complexity, third-party operation, and system complexity.
- The Dayos example in the same instrument, which demonstrates risk tiering using severity of impact, reversibility, and feasibility of human oversight and shows that the tier determines the permitted autonomy response.
- `Requirement Element Audit` for MGF Agentic D1.2, which defines the six atomic elements used by the executable contract.

The framework does **not** prescribe that every organisation must use the Dayos example's exact three-tier scoring scheme. Therefore the predicates test whether the organisation has an approved, discriminating, load-bearing tiering method rather than hard-coding an invented Tier 1/2/3 numeric threshold.

## Predicate mapping

| Element | Deterministic test |
|---|---|
| e1 | Approved methodology record contains methodology identity, criteria reference, tier scheme, and approval date. |
| e2 | Tier-rule records contain a rule identifier, explicit rule expression, and outcome. |
| e3 | Assessment timestamp precedes the decision timestamp. |
| e4 | Approval record exists and approver identity is distinct from requester identity. |
| e5 | Every observed assessment outcome has a corresponding tier-to-control/gate mapping. |
| e6 | Reassessment control defines triggers, accountable detection owner and review date; trigger detection status is recorded. |

## Result semantics

The six elements are ordinary governed observations. Missing required sources produce `NOT_TESTABLE`; contradictory or failed predicates produce `FAIL`; all applicable predicates passing produces `PASS`.

The engine does not infer a tier from prose or invent thresholds. The organisation's approved methodology remains the governing classification rule.

## UI consequence

The Review workspace now exposes six requirement elements for D1.2 instead of the former generic one-line element. The human can independently read each element, then inspect the deterministic engine result, predicates, observations and lineage after their reading is recorded.
