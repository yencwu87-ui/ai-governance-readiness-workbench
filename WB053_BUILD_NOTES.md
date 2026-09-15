# WB-053 build notes

This build rewires the Ollama/web-search path into the governed assurance pipeline.

## Included changes

- `ollama_search.py` is now a reusable DDGS knowledge adapter plus CLI.
- `governance/knowledge_resolver.py` uses that single retrieval adapter.
- `challenge.py` uses the dedicated `challenge` / `challenge_disagreement` Ollama role.
- Challenger model calls can be observed with the existing telemetry seam.
- Common model spellings such as `Revisit_read` are canonicalised to `revisit_read`.
- JSON extraction is more tolerant of wrapper text.
- Deterministic validation failures trigger a bounded repair retry (`WB_CHALLENGE_RETRIES`, default 2).
- Evidence quotes, requirement pointers, claim tests, and allowed actions remain hard gates.
- Web knowledge remains advisory and cannot become organisational evidence.
- `docs/WB053_OLLAMA_CHALLENGER_HARDENING.md` documents the new controls and configuration.
- `tests/test_challenger_hardening.py` covers action normalisation and retry-on-validation.

## Validation performed

Targeted regression suite: **41 passed** across the Challenger, disagreement, claim-rebuttal, hardening, and core-cycle tests.

Full repository suite: **290 tests collected**. The full run exceeded the available execution window after substantial progress; no claim is made that every test completed in this build environment.

# WB-053 next change: claim-vetted Challenger + evidence-element reviewer assistance

## Changes in this revision

1. Reviewer-read claim vetting now runs before rebuttal generation. The reviewer read is decomposed into explicit claims and each claim is classified against the supplied evidence as supported, contradicted, unsupported, or unclear. The result is recorded in the challenge output as `reviewer_claims` and `reviewer_claim_vet_status`.

2. The main Challenger prompt receives those pre-vetted claims. Substantive challenges are expected to arise from contradicted claims; unsupported claims can lead to evidence requests or read refinement, but absence of evidence is not treated as a strong contradiction.

3. Added `governance/evidence_element_matcher.py`. It deterministically finds candidate evidence passages for governed elements and returns reviewer-assistance suggestions. It never infers `not_evidenced` from a missing match and never records a verdict.

4. The Review workspace now shows evidence-match suggestions and lets the reviewer explicitly apply only high-confidence positive matches to the draft. The reviewer still eyeballs and can override every element before saving the reading.

5. Added an LLM role `challenge_claim_vet` using the Challenger model configuration. Claim-vetting failure is non-fatal and is visible in the recorded challenge rather than being silently treated as success.

## Validation

Targeted regression suite for the new behaviour and adjacent challenge/disagreement paths: 34 passed.
Additional comparison/disagreement suite: 30 passed.
