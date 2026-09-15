# Where the model reasons, and where it is not allowed to

This note describes how much reasoning the language model does in the readiness workbench, what surrounds it, and why the design keeps the model's share deliberately small.

## The short version

The model is asked one question per control, once, with a fixed rubric, and its answer is checked by rules before a human sees it. Everything upstream of the model (finding evidence) and downstream of it (recording, reporting, writing back) is deterministic code. The model contributes judgement about *whether a passage evidences a requirement*. It contributes nothing else.

## What the model is given

For each control, a single prompt containing:

- the control's library, ID, title, requirement text, owning role and crosswalk references, taken verbatim from the playbook
- up to three passages of evidence, each labelled with the source file and part number, selected by BM25 retrieval rather than by the model
- any environment signals matched to the control by filename rule, with the note on what to check

The model never sees the whole folder, other controls' ratings, the reviewer's previous decisions, or the maturity dashboard. It cannot browse, retrieve or call tools. Its context is exactly what the retrieval stage hands it, which means every rating is traceable to named passages.

## What the model is asked to do, in order

The system prompt fixes the rubric and the output order:

1. **Excerpt** — quote the single most relevant phrase verbatim from the evidence, or leave it empty.
2. **Gaps** — list what the requirement needs that the evidence does not show.
3. **Rationale** — two sentences.
4. **Sufficiency** — none, partial or full.
5. **Maturity** — 1 to 5 on a fixed scale (ad hoc, documented, implemented, measured, optimised).
6. **Remediation** — one concrete action per gap, naming the artefact to produce.
7. **Reviewer prompt** — one question the human should ask before accepting.

The order is the reasoning effort. Small models rate first and rationalise afterwards if allowed to; forcing the excerpt and the gap list before the rating makes the rating a consequence of the analysis rather than the other way round. The prompt states the consequence explicitly: if any gap remains, the rating cannot be full.

Two rubric rules are also stated in the prompt because they are where small models most often go wrong:

- a policy or intent statement alone is at most *partial* for any control that requires a running artefact (logs, monitoring output, test results, inventory records)
- unrelated evidence is *none*, not a charitable *partial*

## How the call is made

- Local model via Ollama (default `llama3.1:8b`), JSON mode on, temperature 0.1, 8k context.
- One call. No chain-of-thought scratchpad, no self-critique pass, no second model, no retries on disagreement.
- Output parsed into a fixed shape: sufficiency coerced to one of three values, maturity clamped to 1–5, gaps and remediation normalised to lists, malformed JSON raised as an error rather than silently accepted.

This is the minimum viable amount of model reasoning. It was chosen on purpose: every additional pass adds latency on a laptop, adds a second place for the model to be wrong, and makes the audit trail harder to read. The reviewer gate is where the second opinion lives.

## What checks the model's answer

`_validate()` runs after every call. It is plain Python and can only downgrade:

| Rule | Effect |
|---|---|
| Excerpt not found verbatim in the evidence text (case- and whitespace-insensitive) | Excerpt blanked; a *full* becomes *partial*; flag raised |
| Gaps listed and rating is *full* | Rating becomes *partial*; flag raised |
| Rating *none* | Maturity capped at 1 |
| Rating *partial* | Maturity capped at 3 |

Flags are shown to the reviewer, written to the report, and carried into the playbook notes on write-back. The reviewer therefore sees both what the model said and what the harness corrected.

## What the model is not allowed to do

- Choose which documents to read. Retrieval is keyword-based and reproducible; the model rates what it is handed.
- Rate a control with no matching evidence. Those are reported as "no evidence located", never sent to the model.
- Record anything. The proposal is stored as a proposal. `record_decision()` takes a human's inputs; `export_playbook()` writes only what `record_decision()` produced. The call graph has no path from `propose()` to `write_back()`.
- Declare compliance. The vocabulary is evidence sufficiency throughout — prompt, UI, report and workbook status values ("Evidenced", "Partially evidenced", "Not evidenced").

## Known limits of this level of effort

- **Vocabulary mismatch.** BM25 finds documents that use the control's words. Evidence written in different terms is missed, and the model never gets the chance to rate it. The threshold slider and the match preview are the mitigation; a semantic retriever would be the upgrade.
- **Small-model over-rating.** An 8B model will sometimes call a policy paragraph *full*. The gaps-before-rating order reduces this; the harness catches the cases where the model lists gaps anyway; the reviewer prompt exists for the cases where it does not.
- **Excerpt paraphrase.** Models paraphrase quotes. The verbatim check catches this and blanks the excerpt rather than trusting it, at the cost of occasionally discarding a nearly-right quote.
- **No measured accuracy yet.** There is no golden set of evidence–control pairs with reviewer ratings, so under- and over-rating rates per model are not yet known. That is the next piece of work, mirroring the eval harness in the governed-incident-triage repository.

## Why not more reasoning

More model effort — a critique pass, a stronger model, a chain-of-thought scratchpad — would raise the proposal's quality. It would not change the governance position, because the reviewer decides either way. The design spends its effort where the regulator will look: the trail from a named passage, through a stated rubric and visible corrections, to a named person's decision.
