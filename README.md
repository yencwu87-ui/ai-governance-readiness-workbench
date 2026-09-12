<h1 align="center">AI Governance Readiness Workbench</h1>

<p align="center">
  <em>A governed second-line AI assurance workbench.<br>
  AI proposes. Deterministic controls constrain. A named human decides.</em>
</p>

<p align="center">
  <img src="docs/pipeline.svg" alt="Operating model: evidence feeds an AI assessor and a reviewer independently, a deterministic compare step diffs them element by element, a scoped challenger attacks the disagreement, and only a human writes the decision record." width="100%">
</p>

---

## What it does

The workbench reads supplied evidence against governed control requirements, proposes an assessment, records a reviewer's independent read, compares the two element by element, challenges the disagreement, and writes a reasoned decision attributable to a named person.

It does **not** declare regulatory compliance. It rates how far supplied evidence supports a control, and it is built so that every number it produces can be traced to a quote, a requirement version and a person.

Coverage spans five control libraries — MAS AIRG, MAS SAFR, IMDA Model AI Governance Framework for Agentic AI, ISO/IEC 42001 and NIST AI RMF — across 195 controls. Inference is local by default, so evidence never leaves the machine.

## The design rule

Every model call in this repository is followed by deterministic checks that can only **downgrade**, never upgrade. A model cannot talk its way past them, and neither can a reviewer in a hurry.

| Rule | Why it exists |
|---|---|
| A quote not verbatim in the evidence is dropped | Fluent invention is the failure mode that survives review |
| An element neither side decided is `unset` | Silence is not agreement and must not be counted as it |
| Below the evidence floor, a `PASS` becomes `NOT_TESTABLE` | A result over one record is not a result |
| A failed model call is an error, never a rating | A run that did not happen must not resemble one that found nothing |
| A stale requirement binding makes label comparison `NOT_TESTABLE` | A label means something only while it describes the requirement it was argued against |
| A decision reason that repeats the decision word is refused | 47 accepts to 4 amends, every reason reading "accept", is not an accountability record |

## Operating model

**Assess with AI** answers *what does this evidence support?* It receives the evidence, the control contract, the ToD/ToE methodology, the near-miss bank and advisory knowledge. It returns a rating and a verdict per requirement element, each `met` carrying a verbatim quote. It cannot write.

**Your read** is recorded blind. The AI proposal is computed ahead of time and held hidden until the reviewer has committed their own reading — blindness is about what the reviewer was shown, not when the call was made, so batch assessment still runs ahead.

**Compare** is a pure function with no model call. It diffs the two reads element by element against the same contract and reports what was compared, what was not, and where they disagree.

**Challenge** attacks the disagreement rather than either read. It must state which side the evidence supports — `reviewer`, `assessor` or `neither` — and a challenge naming an element outside the disagreement is dropped before validation. It never rates and never agrees. An empty result is a valid result.

**Human final gate** is the only step that writes. Accept, reject, request evidence, override or escalate, with a reason that is checked for substance.

## Getting started

```bash
git clone https://github.com/<you>/ai-governance-readiness-workbench.git
cd ai-governance-readiness-workbench
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

ollama pull llama3.1:8b
ollama pull nomic-embed-text

streamlit run app.py
```

On the Scan tab, choose **Try it with synthetic evidence** to generate a document for every control and walk the whole workflow without client material.

> The synthetic pack is generated **from** the control contracts, so it reuses the requirement wording. Retrieval and assessment both look better against it than against real documents. Use it to learn the workflow, never as a measurement.

## Models

| Variable | Default | Used by |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.1:8b` | assessor, element pass, both challengers |
| `WB_JUDGE_MODEL` | `llama3.1:8b` | lifecycle step judge |
| `WB_EMBED_MODEL` | `nomic-embed-text` | hybrid retrieval |
| `ASSESSOR_MODEL` | `claude-sonnet-4-6` | the Anthropic path, which policy requires a registered exception to use |
| `WB_ELEMENT_PASS` | `split` | `split`, `combined` or `off` |

The challenger sets the floor on model size, not the assessor: its schema carries thirteen required fields per challenge plus two independently verifiable pointers, and validation raises rather than degrades. `llama3.1:8b` is the recommended minimum. Everything runs at temperature 0 with a fixed seed, so a run reproduces.

## Measuring it

Nothing here is trusted because it looks articulate.

```bash
python -m pytest -q
python tools/probe_wb031.py --controls M3.6 --evidence eval/corpus/M3.6 --mode both
```

The probe reports whether the model returns usable element verdicts at all — `unset`, `downgraded` and `met` — separately from whether those verdicts are correct. The second question is gated on the corpus still being bound to the requirement its labels were argued against, and the probe refuses to report label agreement when it is not.

## Repository layout

```
app.py                  Streamlit workbench
assessor.py             rating + element verdicts, and the validators over both
challenge.py            challenge pass 1 (the reviewer) and pass 2 (the disagreement)
compare.py              deterministic element-level diff
judge.py                lifecycle step judge
retriever.py            hybrid BM25 + embedding retrieval
scanner.py pipeline.py  evidence indexing and matching
folder_picker.py        evidence folder browsing
caa/  controls/         deterministic control testing lane
governance/             contracts, knowledge brains, ticket register, decision log
policy/                 policy-as-code — the golden state and the gate rules
eval/                   golden set, constructed corpus, scoring
stress/                 adversarial probes against the assessor and the judge
tools/                  build and measurement scripts
```

## Status and limitations

This is a working research build, not a product. Stated plainly, because a governance tool that overstates itself is the thing it exists to catch:

- **Element decomposition is authored for 30 MAS controls.** The other 165 carry archetype-derived drafts marked `DRAFT, requires second-line authoring`. That marker is currently dropped between the contract and the assessor prompt — a known gap.
- **No accuracy claim is supported today.** The evaluation corpus labels were argued against a superseded requirement decomposition, so label comparison correctly reports `NOT_TESTABLE` until they are re-argued.
- **The constructed corpus covers two controls** of the six to eight planned.
- **51 historical step decisions carry hollow reasons.** The validation that prevents this now exists; the existing records cannot be honestly retro-filled and are kept as they are.
- **Streamlit UI code is not unit-tested.** The rest of the repository is.

## License

See `LICENSE`.
