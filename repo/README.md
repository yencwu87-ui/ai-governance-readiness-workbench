# AI governance readiness workbench

A small Streamlit app that turns a multi-library AI governance control playbook
(MAS AIRG, IMDA MGF Agentic, MAS SAFR, ISO/IEC 42001, NIST AI RMF) into an
evidence-driven readiness assessment with AI-assisted review and reporting.

The design principle is second-line-of-defence discipline: the AI **proposes**
an evidence-sufficiency rating with rationale, excerpt, gaps and a challenge
question. A **named reviewer** accepts or overrides, and only that decision is
recorded. The app never labels anything "compliant" — it reports how far
supplied evidence supports each control.

## What it does

- **Scan tab** — point it at a folder; it indexes PDF/Word/Excel/Markdown/text files, maps passages to in-scope controls (BM25), detects environment signals (IaC, CI, IAM, logging, prompts, secrets files) by filename pattern, runs the assessor on every matched control, and produces a prioritised gap analysis with suggested actions

- Loads control libraries directly from the playbook workbook
- Scope selection per library, search, per-control evidence (text or PDF)
- AI assessment with a fixed rubric — local Ollama model by default, Anthropic API optional
- Reviewer accept / override with an audit trail (who, when, what the AI proposed)
- Evidence reuse across cross-mapped controls
- Readiness summary, gap register, Markdown report
- Writes accepted results back into a copy of the workbook
  (Status, Maturity, Evidence, Last reviewed, Gap / notes)

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.1:8b               # any local model; set OLLAMA_MODEL to change
streamlit run app.py
```

To use Claude instead of a local model:

```bash
export ASSESSOR_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-...
streamlit run app.py
```

PDF evidence is text-extracted locally for Ollama; nothing leaves the machine.

Place the playbook workbook in `data/` (it, assessments and uploaded evidence are git-ignored). `sample_evidence/` holds a fictional evidence set to try the Scan tab on. You can also upload the workbook from the sidebar.

## Documentation

- [User guide](docs/USER_GUIDE.md) — setup, daily use, reading proposals, reporting, troubleshooting
- [Architecture](docs/ARCHITECTURE.md) — pipeline stages, what can and cannot change a rating, data flow

## Layout

```
app.py        Streamlit UI, scan orchestration and report
scanner.py    Folder scan, text extraction, environment signals, BM25 retrieval
assessor.py   Claude call and rubric prompt
playbook.py   Workbook loader and write-back
data/         playbook, assessments.json, evidence/ (not committed)
```

## Limits

Single-user, local file persistence, no authentication. Suitable for a
demonstrator or a practitioner's own engagement toolkit, not for multi-tenant
use without adding auth, tenancy and evidence-retention controls.
