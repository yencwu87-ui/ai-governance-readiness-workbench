# WB-071 — M3.6 requirement-element hardening

## Finding

The previous M3.6 draft was being measured mainly at sentence-selection level. In the failing run,
15/18 sentences were accepted (83%), while eight selected sentences produced 28 elements and one
sentence produced 13. That allowed PDF header text, function words, wrong-anchor paraphrases and
out-of-scope material to contaminate the requirement-element matrix.

## Implemented guards

1. **PDF hygiene before sentencing.** `tools/draft_elements.py` removes the known running header
   (`Proposed Guidelines on AI Risk Management | <page>`) and obvious footnote prefixes before
   sentence enumeration. A header joined to an obligation therefore cannot become a candidate.
2. **Element obligation-shape gate.** Model-generated elements must contain enough meaningful tokens
   and an action/modal signal. Function-word fragments such as `of`, `and`, and `for` are rejected.
   This is an action+target heuristic, not a full natural-language parser.
3. **Own-anchor provenance gate.** Material element tokens must overlap the element's own source
   sentence. A lexical provenance check is used deliberately: semantic similarity can hide a copied
   obligation that was not actually present in the source sentence.
4. **Subject-preservation gate.** Explicit actor markers are compared before the first obligation verb
   or modal. A change such as `the AI system` -> `the FI` is rejected even when the remaining words
   overlap.
5. **Clean-anchor gate.** A verified anchor must not contain a running header, obvious footnote prefix,
   or sentence fragment.
6. **Fan-out cap.** No more than three accepted elements may be promoted from one source sentence.
   Additional model outputs are not silently discarded; they are recorded as overflow flags.
7. **Separate diagnostics.** The renderer now reports sentence selection rate separately from element
   acceptance/rejection/overflow and shows an `element integrity: PASS|FLAGGED` line. This prevents the
   sentence-rate headline from hiding element-level contamination.

## M3.6 contract revision

The governed M3.6 requirement remains the source-aligned statement:

> AI systems are evaluated and independently validated against defined criteria before deployment,
> with results, limitations, residual risk and re-validation triggers documented.

It is now decomposed into seven model-scoped elements covering: pre-defined measures/thresholds;
actual use-case evaluation results; relevant performance/failure testing; risk-proportionate
pre-deployment independence; high-risk formal independent validation and effective challenge; the
substantive validation scope (conceptual soundness, data, implementation, testing, explainability,
fairness, assumptions/limitations/mitigants); and recorded outcomes/residual risk/re-validation
triggers. The high-risk validation element is explicitly conditional.

The revised corpus was re-argued against `M3.6_a/b/c` on 2026-09-14 and its requirement SHA is
`6a57b78f6b44`. Derived labels are `_a=partial`, `_b=partial`, `_c=none`.

## What this does not do

The guards do not decide compliance, maturity or the final reviewer decision. They only prevent
malformed source decomposition from entering the draft contract and make decomposition failures
visible to the reviewer.

## Local Ollama hardening

`assessor.py` now defaults to a 120s request timeout, 16k context and 1200 output tokens, all
overridable with `OLLAMA_TIMEOUT`, `OLLAMA_NUM_CTX`, and `OLLAMA_NUM_PREDICT`. The timeout message
reports the configured value. This addresses the observed 300s qwen2.5:14b timeout by failing faster
and bounding the local request; it does not claim that a particular local model will meet a given
latency target on all hardware.
