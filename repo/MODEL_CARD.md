# Model card — readiness-assessor

**Model id:** readiness-assessor
**Owner:** Yen-Ching
**Risk tier:** medium
**Current version:** v0.2.0 (see `deploy.yml`)
**Provider:** Anthropic API or local Ollama, selected in `assessor.py` (`PROVIDER`)

## Intended use

Proposes an evidence-sufficiency rating (none / partial / full) and a maturity score (1 to 5) for one governance control at a time, given evidence text or a PDF located by the workbench scanner or supplied by the reviewer. The proposal is advisory input to a named human reviewer.

## What it must not decide

- It never records a rating. `propose()` returns a proposal; only `record_decision()` writes to the playbook, and only a named reviewer calls it.
- It never determines regulatory compliance. Ratings describe how far the supplied evidence supports a control, not whether the organisation meets MAS, ISO 42001 or any other requirement.
- It never runs a Lane B control check. Deterministic control tests in `caa/checks.py` do not call a model.
- It never sees evidence the reviewer has not chosen to scan or upload. Nothing leaves the machine until `propose()` is called.

## Harness

- Input is bounded: evidence text is truncated to 20,000 characters; retrieval is BM25 over local documents with a reviewer-set match threshold.
- Output is structured: sufficiency, proposedMaturity, rationale, excerpt, gaps, remediation, flags, reviewerPrompt. A malformed or failed response returns `model: error` and sufficiency `none`, never a silent rating.
- Validation flags surface in the UI before the reviewer can accept.
- Every recorded decision stores the AI's proposal alongside it (`aiSufficiency`, `aiMaturity`) so overrides are visible in the report.
- The reviewer's name and timestamp are attached to every recorded decision.

## Evaluation

- Eval set: `golden_20_controls` — 20 control/evidence pairs hand-labelled by the reviewer. Metric is agreement with the reviewer's sufficiency rating.
- Results are recorded per version in `governance/eval_results.json` and checked by MCM-03 (eval before deploy) and MCM-04 (no regression).
- Known limitation: 20 items is too small for a meaningful tolerance band; exception EXC-001 covers MCM-04 until the set reaches 100.

## Known limitations

- Ratings depend on retrieval: a control with no matching document is reported as "no evidence located", not as failing.
- The assessor cannot verify that a document is current, approved or in force. That judgement is the reviewer's.
- Behaviour differs between providers; results from Ollama and Anthropic are not interchangeable and the provider is recorded on every proposal.

## Change control

Any change to the assessor prompt, provider, model name, harness, or eval set is a model change: raise a `WB-` ticket, run the eval set, update `deploy.yml`, and reference the ticket in the commit message.
