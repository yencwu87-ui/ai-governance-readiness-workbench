# ai-lifecycle — policy v1.0.0

**Owner** AI Risk (second line) · **Approved by** AI Risk Committee · **Effective** 2026-09-06 · **Policy hash** `b37d9916d9eb5255`

> Generated from `policy/ai-lifecycle.yaml`. Do not edit by hand — edit the policy and re-render, so the approved policy and the enforced gate cannot drift apart.

**Scope.** The readiness-assessor and any model, agent or prompt deployed from this repository, across the eleven lifecycle plays in the AI Governance Playbook.

## 1. Golden state

| Clause | Requirement | Enforced by |
|---|---|---|
| Inference residency | local-only; providers ollama, mlx; any locally-served model permitted | GOV-01 |
| Non-local providers | anthropic permitted only under a registered, unexpired exception | GOV-01 |
| Dependencies | pinned in `requirements.txt` | MCM-07 |
| Artefacts, all models | model_card, registry_entry, change_ticket | DISC-02, GOV-02, MCM-01, MCM-02 |
| Artefacts, high tier | eval_before_deploy, impact_assessment, independent_validation, stress_test_pre_release | GOV-04, STR-03 |
| Evaluation | golden set ≥ 20 items; run before deploy | MCM-03 |
| Segregation of duties | approver is not the author | MCM-05 |

## 2. Gates

| Trigger | Blocks on | Must pass |
|---|---|---|
| on_commit | FAIL at severity high or above, not covered by an exception | — |
| on_deploy | FAIL at severity high or above, not covered by an exception | MCM-03, STR-03 |
| scheduled | FAIL at severity none or above, not covered by an exception | — |
| manual | FAIL at severity none or above, not covered by an exception | — |

## 3. Exceptions

An exception exempts a control from the gate. Maximum life 180 days. Required fields: exception_id, control_id, owner, expires_on, rationale. Re-tabled at the monthly service governance forum. Enforced by GOV-03, MCM-10.

## 4. Cadence

| Activity | Limit |
|---|---|
| Stress test | per tracker cadence (quarterly 100d, semi-annual 190d, annual 380d) |
| Rollback test | every 180 days |
| Emergency change closed | within 7 days |

## 5. Human oversight

A named reviewer records every decision. AI may: propose, retrieve, summarise, triage. AI may not: record a decision, sign a result, set a gate outcome, edit an evidence bundle, edit the tracker, edit this policy. Reviewer override rate of AI proposals is monitored within 5–60%; outside that band is a finding, not a target. Enforced by OVS-02, OVS-01.

## 6. Controls enforcing this policy

| Control | Policy clause |
|---|---|
| DISC-02 At least one model card is present in the scanned folder | required_artefacts.all |
| GOV-01 Every configured and deployed inference provider is in the policy's al | inference.residency, inference.provider_exceptions |
| GOV-02 Every registered model has the artefacts the policy requires for all m | required_artefacts.all |
| GOV-03 Every open exception carries the policy's required fields and expires  | exceptions.max_days |
| GOV-04 Every registered model has the artefacts its risk tier requires, beyon | required_artefacts.high, required_artefacts.medium |
| GOV-05 Every tier obligation (review cycle, eval before deploy, independent v | tier_obligations |
| MCM-01 Every deployed model or prompt version in production has a matching ch | required_artefacts.all |
| MCM-02 Every change ticket references a model_id that exists in the model reg | required_artefacts.all |
| MCM-03 An evaluation run exists for the released version with a timestamp bef | evaluation.run_before_deploy |
| MCM-04 Released version's key metrics are within tolerance of the prior versi | evaluation.tolerances |
| MCM-05 Approver on the change ticket is not the author of the code or prompt  | segregation_of_duties.approver_not_author |
| MCM-07 All dependencies are pinned to exact versions | dependencies.pinned |
| MCM-08 A rollback test has been exercised within the last 180 days | cadence.rollback_test_days |
| MCM-09 Emergency changes complete full approval evidence within 5 working day | cadence.emergency_change_close_days |
| MCM-10 Every open exception has an owner and an expiry date not yet passed | exceptions.max_days |
| OVS-01 Override rate of AI proposals in the last 90 days is between 5% and 60 | oversight.override_rate_band |
| OVS-02 No recorded decision carries an empty or placeholder reviewer name | oversight.reviewer_required |
| STR-01 Each tracker row has a last-run date within the days implied by its ca | cadence.stress_test_days |
| STR-03 Each deployment is preceded by at least one tracker run within the pri | required_artefacts.high |

Controls with no policy clause test operating discipline rather than the golden state; see `controls/*.yaml`.
