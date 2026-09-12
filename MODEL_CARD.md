# Model card — readiness-assessor

**Model id:** readiness-assessor
**Owner:** Yen-Ching
**Risk tier:** medium
**Current version:** v0.5.0 (see `deploy.yml`)
**Provider:** local Ollama (default) or Anthropic API, selected in `assessor.py` by
`ASSESSOR_PROVIDER`
**Model:** `llama3.1:8b` by default (`OLLAMA_MODEL`); `claude-sonnet-4-6` on the Anthropic path
(`ASSESSOR_MODEL`)

*Verified against `assessor.py`, `pipeline.py` and `requirements/mas.yaml` on 2026-09-10. Any
line here that the code does not support is a defect in this card.*

## Intended use

Proposes an evidence-sufficiency rating (none / partial / full) and a maturity score (1 to 5)
for one governance control at a time, given evidence text or a PDF located by the workbench
scanner or supplied by the reviewer. The proposal is advisory input to a named human reviewer.

## What it must not decide

- It never records a rating. `propose()` returns a proposal; only `record_decision()` writes to
  the playbook, and only a named reviewer calls it. The call graph enforces this — there is no
  directed path from `propose()` to `write_back()`.
- It never determines regulatory compliance. Ratings describe how far supplied evidence
  supports a control, not whether the organisation meets MAS, ISO 42001 or any other
  requirement.
- It never runs a Lane B control check. Deterministic tests in `caa/checks.py` do not call a
  model.
- It never sees evidence the reviewer has not chosen to scan or upload.

## What it is judged against

Since v0.5.0 the assessor is given the control's **requirement text and expected elements**
from `requirements/mas.yaml`, not only the control title. This matters: before that change the
MAS library had no requirement column, so every MAS control reached the model as
`"Expectation: <control title>"` and the assessor was rating evidence sufficiency against a
heading. Two controls (M3.6, M3.12) have written requirements today; the other 28 still load
the workbook heading.

## Harness

Deterministic checks applied after every model call. **They can only lower a rating, never
raise one.** Every rule that fires is shown to the reviewer and stored on the proposal.

1. Instruction-shaped text in the evidence is detected before the model sees it. Matching
   paragraphs are redacted whole — a planted claim beside an instruction is as untrusted as the
   instruction — and reported as a flag. Maturity caps at 2.
2. The excerpt must appear verbatim in the evidence, and must not come from a redacted
   paragraph. A quote that fails is discarded and `full` drops to `partial`.
3. Gaps and rating must agree in both directions: `full` with gaps drops to `partial`; a rating
   below full with no gaps is flagged and maturity capped.
4. A `partial` must evidence something. With declared artefacts, a proposal gapping every one
   of them drops to `none`. Without them, a `partial` carrying no surviving verbatim excerpt
   drops to `none`.
5. Maturity ceilings: `none` caps at 1, `partial` at 3.

An empty evidence body is flagged rather than rated — absence cannot be established from a run
that saw nothing.

**A failed model call returns no rating at all.** `propose()` returns `status: "error"` with no
`sufficiency` key. Until 2026-09-10 it returned `sufficiency: "none"` with the exception text in
the rationale, which put two Ollama read-timeouts into the assessment record as findings.
`none` means the evidence was read and the control is not evidenced; a timeout means nothing was
read.

## Input and output

- Evidence text assembled per control is truncated to 20,000 characters (`build_evidence`);
  PDF extraction is capped at 30,000 characters before that.
- Retrieval is hybrid — BM25 plus local embeddings, rank-fused — with a **relative** match
  threshold defaulting to 0.35 of the best-scoring passage for that control, and up to three
  passages kept. The threshold is recorded with every assessment. An earlier absolute threshold
  never bound and is documented in `docs/MATCH_THRESHOLD.md`.
- Output keys: `excerpt`, `gaps`, `rationale`, `sufficiency`, `proposedMaturity`, `remediation`,
  `reviewerPrompt`, plus harness-added `flags`, `injection_hits` and `model`.
- Temperature 0 with a fixed seed on both providers, so a rating is reproducible for a given
  prompt and model.
- Every recorded decision stores the proposal beside it (`aiSufficiency`, `aiMaturity`) with the
  reviewer's name and timestamp, so disagreement is measurable.

## Evaluation

**Eval set:** `golden_20_mas_v1`, sha `753bd05241f7`. 19 scored cases (1 ambiguous, excluded).
Label distribution 9 none / 2 partial / 8 full; 10 real, 9 synthetic.

An earlier version of this card named `golden_30_mas_v2`. No such set existed — see the
correction note in `governance/eval_results.json`, where placeholder values from a scaffolding
template had been recorded as results.

**Results, v0.5.0, 2026-09-10:**

| model | accuracy | adjacent | over-credit | under-credit |
|---|---|---|---|---|
| `ollama/mistral:latest` | 58% | 89% | 0% | 42% |
| `ollama/llama3.2:latest` | 42% | 95% | 16% | 42% |

**Read these against the constant baselines**, which the scorer now prints: always-`none`
scores 47% on this set, always-`full` 42%. So mistral clears the majority-class baseline by 11
points, and **llama3.2 is below it** — that model would score higher by answering the same
thing every time. Accuracy without the baseline is not interpretable.

**Neither model has ever produced a `full` rating** across 19 golden cases or the 6-document
constructed corpus. Under-credit of 42% is exactly the 8 `full` cases. That share of the set is
currently unreachable, and it is a property of the assessor, not of the evidence.

Results are recorded per version in `governance/eval_results.json` and checked by MCM-03 (eval
before deploy) and MCM-04 (no regression).

## Known limitations

- **`full` appears unreachable.** See above. Until that changes, a `partial` should be read as
  "the assessor's ceiling", not as a judgement that something is missing.
- **Errors cluster at one step.** Adjacent accuracy is 89–95% while exact accuracy is 42–58%:
  the assessor compresses toward `partial` from both directions.
- **22 of 30 MAS controls still lack hand-authored requirement text.** v0.4 now operationalises the eight critical controls (M1.1, M3.6, M3.7, M3.9, M3.11, M3.12, F1, F3); the remaining 22 still require semantic definitions.
  title, and results for them should be read accordingly.
- Ratings depend on retrieval. A control with no matching document is reported as "no evidence
  located", not as failing.
- The assessor cannot verify that a document is current, approved or in force. That is the
  reviewer's judgement.
- Behaviour differs materially between models, not only between providers. The model name is
  recorded on every proposal and results are not interchangeable.
- 19 items is too small for a meaningful tolerance band. Exception EXC-001 covers MCM-04 until
  the set reaches 100 — **confirm this exception is still in force and covers the current
  MCM-04 failure before relying on it.**

## Change control

Any change to the assessor prompt, provider, model name, harness, requirement text or eval set
is a model change: raise a `WB-` ticket, run the eval set, update `deploy.yml`, update this
card, and reference the ticket in the commit message.

The requirement text and elements in `requirements/mas.yaml` are load-bearing — they are what
the assessor is judged against — and should be a governed path under MCM-06 on the same footing
as `policy/`. They are not one today.

## Open defects in the assessor

- `_validate` has two blocks both numbered `4a` (the artefact gate and the empty-evidence
  flag). Cosmetic, but the numbering is referenced in commit messages and this card.
- The declared-artefact gate matches gaps to artefacts by normalised string comparison. It is
  deliberately conservative — a phrasing mismatch leaves the rating alone — so it under-fires
  rather than over-fires.
