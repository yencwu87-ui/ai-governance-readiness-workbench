# WB-096 — Inference Engineering + Plugin/Tool Foundation

## 1. Start the workbench

```bash
cd /path/to/ge_14Sep
source .venv/bin/activate   # if your environment uses one
python -m pytest -q tests/test_inference_engineering_wb096.py tests/test_element_drafting_wb070.py
streamlit run app.py
```

## 2. Recommended Ollama routing

Start conservatively. The fast tier defaults to your existing role model unless explicitly overridden.
Use a stronger model only when escalation is configured.

```bash
export ASSESSOR_PROVIDER=ollama
export OLLAMA_URL=http://localhost:11434
export WB_MODEL_FAST=llama3.1:8b
export WB_MODEL_STRONG=qwen2.5:14b
export WB_MODEL_CRITICAL=qwen2.5:14b
export OLLAMA_TIMEOUT=120
export OLLAMA_NUM_CTX=16384
export OLLAMA_NUM_PREDICT=1200
```

Because `qwen2.5:14b` previously timed out in the reviewer workflow, do not configure it as the first
tier merely because it is stronger. Verify the model responds locally before enabling escalation.

## 3. Inspect the policy without making an LLM call

```bash
python tools/inspect_inference.py --role challenge --control M3.6 --elements 14 --disagreement
```

## 4. Draft M3.6 elements

```bash
python tools/draft_elements.py --control M3.6 --instrument instruments/Final_Consultation_Paper_on_Guidelines_on_AI_Risk_Management_ForRelease.txt
```

The tool removes running headers/page-number spill, rejects function-word fragments, checks each element
against its own anchor, rejects actor swaps, limits per-sentence fan-out to three and records element
quality failures before promotion.

## 5. What the new inference layer does

`inference/policy.py` classifies work into routine/strong/critical using observable signals.
`inference/orchestrator.py` can escalate a failed quality-gated task to a stronger model.
`governance/inference_tasks.jsonl` records task-level completion, escalation, validation failures and latency.

The layer never writes the governance decision. Assess/Challenge still produce proposals for the existing
validation and human decision gates.

## 6. Plugin/tool boundary

Plugins remain observation providers. The built-in GitHub plugin is read-only. Tool contracts explicitly
declare `read_only`, `write`, or `destructive` side-effect classes. No remediation plugin is introduced by
this build.

## 7. M3.6 element contract

The authoritative MAS overlay now contains 14 atomic elements. Verification metadata in
`governance/knowledge/element_testing.yaml` tells the engine how an element can be tested; it does not
create additional requirements. The M3.6 evaluation corpus is structurally rebound to the new 14-element
contract and intentionally awaits human re-labelling, so the evaluation remains NOT TESTABLE rather than
reusing labels from the old 7-element contract.
