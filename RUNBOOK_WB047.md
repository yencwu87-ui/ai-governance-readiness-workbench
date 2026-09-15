# WB-047 End-to-End Runbook

## 1. Prerequisites

- Python 3.11+
- Ollama installed and running
- A local chat model, e.g. `qwen3:8b` or `llama3.1:8b`
- `nomic-embed-text` for local hybrid retrieval

## 2. Install

```bash
cd fix_work
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 3. Ollama

```bash
ollama pull qwen3:8b
ollama pull nomic-embed-text
ollama list
```

Choose the model without editing code:

```bash
export OLLAMA_MODEL="qwen3:8b"
export WB_EMBED_MODEL="nomic-embed-text"
```

The existing default remains `llama3.1:8b` if `OLLAMA_MODEL` is not set.

## 4. Internet knowledge

WB-047 adds `governance/knowledge_resolver.py`.

```bash
export WB_WEB_KNOWLEDGE="auto"
export WB_WEB_MAX_RESULTS="5"
```

Modes:

- `auto`: use web for current/regulatory/update-oriented controls
- `always`: web for every assessor/challenger knowledge resolution
- `off`: local knowledge only

Web results are advisory. They are never compliance evidence and cannot override the control contract or supplied organisational evidence.

## 5. Build control-testing knowledge

The workbook remains the upstream source for control/test requirements. Build the normalized KB:

```bash
python tools/build_control_testing_kb.py
```

## 6. Test

```bash
pytest -q
```

## 7. Start the workbench

```bash
streamlit run app.py
```

Or use:

```bash
./run.sh
```

## 8. Architecture

```text
Workbook / Control Contract
          |
          +--> Local governance brain
          |
          +--> Control testing KB (ToD / ToE / evidence floor / failure modes)
          |
          +--> Optional DDGS web knowledge
                       |
                       v
                 Knowledge Resolver
                       |
                       v
                  Ollama / Qwen
                  /           \
             Assessor       Challenger
                  \           /
                   deterministic validation
                           |
                       human review
```

## 9. Important governance boundary

The model may use local and internet knowledge to understand a control, design a test, interpret a requirement, or identify a challenge. It must not convert a web statement into proof that the assessed organisation complied.

The workbook itself states that Test of Design verifies that a control is formally defined, approved, scoped, owned and testable, while Test of Operating Effectiveness requires sampled evidence that the control operated as designed. Testing procedures require control-owner / assurance-authority approval before authoritative use.
