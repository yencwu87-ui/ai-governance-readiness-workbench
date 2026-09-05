# governance/ — Lane B evidence exports and coverage register

## Data contracts

| File | Read by | Update when |
|---|---|---|
| tickets.csv | MCM-01, 02, 05, 06, 09 | any change to the assessor, prompts, harness, or Lane B controls |
| model_registry.csv | MCM-02 | a model is added or its tier changes |
| eval_results.json | MCM-03, 04 | every eval run |
| rollback_log.csv | MCM-08 | every rollback test (at least every 180 days) |
| exceptions.csv | MCM-10, CI gate | an exception is raised, extended or closed |
| ../deploy.yml | MCM-01, 03, STR-03 | every deployment |
| ../data/*.xlsx Stress-Test Tracker | STR-01, 02, 03 | every stress-test run (export to governance/stress_tracker.csv for CI) |
| ../data/assessments.json | OVS-01, 02 | written by the workbench on every recorded decision |

Rules: ISO dates (2026-09-06), lowercase booleans (true/false), edit as text not Excel, ticket ids in commit messages (`WB-007: …`), approver never equals git author.

## Coverage register — play-step evidence outputs

Status: **tested** = a Lane B control reads it · **planned** = export not yet built · **human-only** = judgement artefact, Lane A assesses it, Lane B may later test existence/recency only.

| Step | Evidence output (playbook) | Source / export | Lane B controls | Status |
|---|---|---|---|---|
| P1.1 | Intake form | — | — | planned |
| P1.2 | AI inventory entry | governance/model_registry.csv | MCM-02 | tested |
| P1.3 | Materiality score & rationale | — | — | human-only |
| P1.4 | Routing decision | — | — | human-only |
| P2.1 | Impact analysis | — | — | human-only |
| P2.2 | DPIA | — | — | planned |
| P2.3 | Failure-mode register | — | — | planned |
| P2.4 | Societal-impact note | — | — | human-only |
| P2.5 | Signed impact assessment | — | — | human-only |
| P3.1 | Data sign-off | — | — | human-only |
| P3.2 | Model documentation | MODEL_CARD.md | DISC-02 | tested |
| P3.3 | Test results | governance/eval_results.json | MCM-03 | tested |
| P3.4 | Validation report | governance/tickets.csv approver ≠ git author (proxy) | MCM-05 | tested |
| P4.1 | Release checklist | git commit ticket refs (proxy) | STR-03, MCM-03, MCM-06 | tested |
| P4.2 | Oversight & rollback plan | governance/rollback_log.csv | MCM-08, DISC-01 | tested |
| P4.3 | Signed deployment approval | governance/tickets.csv (approved_at, approver) | MCM-01 | tested |
| P5.1 | Monitoring dashboard | governance/eval_results.json (per-version metrics) | MCM-04 | tested |
| P5.2 | Periodic re-check note | — | — | human-only |
| P5.3 | Committee minutes | — | — | human-only |
| P6.1 | Incident ticket | — | — | planned |
| P6.2 | Severity classification | — | — | human-only |
| P6.3 | Containment record | governance/rollback_log.csv | MCM-08 | tested |
| P6.4 | MAS notification (≤1 hr); RCA & impact report (≤14 days); stakeholder notification log | — | — | planned |
| P6.5 | RCA & remediation | governance/tickets.csv (emergency flag) | MCM-09 | tested |
| P6.6 | Post-incident review | — | — | human-only |
| P7.1 | Due-diligence record | — | — | planned |
| P7.2 | Signed contract terms | — | — | planned |
| P7.3 | Concentration & versioning note | requirements.txt pins (proxy) | MCM-07 | tested |
| P7.4 | Vendor monitoring plan | — | — | planned |
| P8.1 | Updated materiality | governance/model_registry.csv (risk_tier) | MCM-02 | tested |
| P8.2 | Re-validation report | — | — | planned |
| P8.3 | Updated impact assessment | — | — | planned |
| P8.4 | Committee decision | governance/exceptions.csv | MCM-10 | tested |
| P9.1 | Phase-out plan | — | — | planned |
| P9.2 | Data disposal record | — | — | planned |
| P9.3 | Access-removal log | environment scan, secrets rule (proxy) | DISC-01 | tested |
| P9.4 | Archive & inventory update | — | — | planned |
| P10.1 | Scope note | Stress-Test Tracker | STR-03 | tested |
| P10.2 | Test plan | — | — | planned |
| P10.3 | Test evidence | Stress-Test Tracker (last_run, result) | STR-01 | tested |
| P10.4 | Updated tracker | Stress-Test Tracker (next_run) | STR-02 | tested |
| P10.5 | Committee sign-off | — | — | human-only |
| P11.1 | Disclosure notice | — | — | planned |
| P11.2 | Training records | — | — | planned |
| P11.3 | Oversight-metrics report | data/assessments.json (override rate) | OVS-01, OVS-02 | tested |
| P11.4 | Red-team review note | — | — | human-only |
| P11.5 | Committee minutes | — | — | human-only |

Coverage: 18 of 47 steps have an operating test.
