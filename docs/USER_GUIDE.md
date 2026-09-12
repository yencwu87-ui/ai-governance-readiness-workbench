# User guide — AI governance readiness workbench

## 1. What this tool is for

You have a set of AI governance controls (MAS AIRG, IMDA MGF Agentic, MAS SAFR, ISO/IEC 42001, NIST AI RMF) and an organisation that says it meets them. This tool helps you find out how much of that is evidenced. It reads the organisation's documents, matches them to controls, proposes an evidence-sufficiency rating for each, and asks you — the reviewer — to accept or override. It then produces a readiness report, a gap analysis with suggested actions, and an updated copy of the playbook workbook.

It does not decide compliance. The ratings are *none / partial / full evidence* plus a maturity score, always attributed to the reviewer who recorded them.

## 2. Setting up (once)

Requirements: macOS or Linux, Python 3.10+, the Ollama app with a model pulled (default `llama3.1:8b`).

```bash
cd <folder containing app.py>
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.1:8b
```

Put the playbook workbook in the `data/` folder. If `data/` does not exist, create it.

## 3. Starting the app (every time)

```bash
cd <folder containing app.py>
source .venv/bin/activate
streamlit run app.py
```

The app opens in your browser at http://localhost:8501. Leave the Terminal window open while you use it; press Ctrl-C there to stop.

The sidebar should show "Assessor: ollama/llama3.1:8b". If it shows a warning that Ollama is not reachable, open the Ollama app and refresh the page.

## 4. The sidebar

- **Playbook workbook** — upload here only if the workbook is not already in `data/`.
- **Organisation** and **Reviewer name** — appear on the report and on every recorded decision. Fill both in before recording anything.
- **Scope** — which control libraries apply to this organisation. MAS, MGF Agentic and SAFR are on by default. A non-financial organisation might use ISO 42001 and NIST only.

## 5. Two ways to work

### A. Scan a folder (fastest, for a whole engagement)

1. Collect the organisation's evidence into one folder — policies, procedures, committee minutes, registers, inventories, monitoring reports, assessments, and if available the code or config repository. Sub-folders are fine.
2. **Scan** tab → paste the folder's full path. (Finder: right-click the folder, hold Option, choose "Copy as Pathname".)
3. Click **Index folder**. It reads every PDF, Word, Excel, Markdown, text, CSV, JSON and YAML file and reports how many documents and passages it found, plus any environment signals.
4. Open **Environment signals** to see files that hint at a control — infrastructure code, CI pipelines, IAM policies, logging configs, prompt files, model cards, `.env` files — with a note on what to check.
5. Open **Preview matches** to see which control each document was matched to. If too many controls match irrelevant documents, raise the threshold slider; if too few match, lower it.
6. Click **Assess matched controls**. Each matched control is sent to the local model in turn; a progress bar shows which one is running. With an 8B model expect 15–30 seconds per control.
7. The **Gap analysis** table appears below: every control not rated full, prioritised, with gaps, suggested actions and the owning role. Proposed ratings are marked "not yet reviewed" until you act on them.

### B. One control at a time (for targeted review or supplementing a scan)

1. **Controls** tab → search or scroll → **Open** on the control.
2. **Assess** tab shows the control's requirement and crosswalk. Paste evidence text, or attach a file. If a scan already located evidence, it is pre-filled and the source files are listed.
3. **Reuse this evidence on…** copies the same evidence to another control (useful for cross-mapped controls). Each copy still needs its own assessment.
4. Click **Assess with AI**.

### C. Headless scan from Terminal

```bash
python run_scan.py /path/to/evidence --scope "MAS,SAFR"
```

Runs index → match → propose over the folder and writes `data/proposals_<date>.json` plus a Markdown gap analysis of unreviewed proposals. Useful for a first pass overnight; review the results in the app afterwards. It never writes to the playbook.

## 6. Reading an AI proposal

Each proposal shows:

- **Sufficiency** — none, partial or full — and **maturity** 1–5 (1 ad hoc, 2 documented, 3 implemented, 4 measured, 5 optimised).
- **Rationale** — two sentences.
- **Excerpt** — a phrase quoted from the evidence. This was checked against the evidence text; if it was not found, it is blanked and a validation line says so.
- **Gaps** — what the requirement needs that the evidence does not show.
- **Suggested actions** — what the organisation should produce to close each gap.
- **Validation** lines (yellow) — rules that corrected the model: a "full" with open gaps becomes partial; "none" caps maturity at 1; "partial" caps it at 3; an unverifiable excerpt is removed.
- **Before accepting, ask** — one question to put to the control owner.

Rules of thumb: policy text alone should never be *full* on a runtime control (the SAFR S-series, MGF D3–D4). A blank template is *partial* at best. A dated record, extract, log or signed-off assessment is what *full* looks like.

## 7. Recording a decision

Under **Reviewer decision**, the dropdowns are pre-set to the AI's proposal. Leave them and click **Accept proposal**, or change either and click **Record override**. Add a note when you override — it goes into the report and the playbook.

Only recorded decisions count. Proposals that have not been accepted or overridden appear in the gap analysis as "proposed, not yet reviewed" and are not written to the playbook.

**Reopen** clears a decision so it can be re-assessed.

## 8. Reporting

**Report** tab:

- **Readiness summary** — per library: controls, assessed, full / partial / none, average maturity.
- **Gap register** — every control below full, with gaps noted. Click a row to jump to it.
- **Download report (.md)** — Markdown with summary, gap register, gap analysis with suggested actions, and every accepted assessment with rationale, excerpt, flags and reviewer note. Opens in any Markdown viewer; paste into Word if a formatted document is needed.
- **Write results back to playbook** — creates `data/playbook_assessed_<date>.xlsx`. In each control library sheet, recorded decisions fill Status, Maturity (1–5), Evidence / artifact, Last reviewed and Gap / notes. The workbook's Maturity Dashboard rolls these up. The original workbook is not modified.

## 9. Where things are saved

| What | Where |
|---|---|
| Playbook | `data/*.xlsx` |
| Assessments, evidence text, decisions | `data/assessments.json` (survives restarts) |
| Uploaded PDFs | `data/evidence/` |
| Written-back playbooks | `data/playbook_assessed_<date>.xlsx` |
| Sample evidence for trying the scanner | `sample_evidence/` |

To start a fresh engagement, stop the app and delete `data/assessments.json`.

## 10. Changing the model

Any model pulled in Ollama works. Larger models follow the rubric more reliably.

```bash
OLLAMA_MODEL=qwen2.5:14b streamlit run app.py
```

To use Claude via the Anthropic API instead (evidence leaves the machine — check the organisation's data-handling rules first):

```bash
ASSESSOR_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... streamlit run app.py
```

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `command not found: streamlit` | venv not active | `source .venv/bin/activate` |
| `No such file: requirements.txt` | wrong folder | `cd` into the folder that contains `app.py` |
| Sidebar asks for upload every time | workbook not in `data/` | copy the xlsx into `data/` next to `app.py` |
| "Ollama not reachable" | Ollama app not running | open Ollama, refresh |
| "model not pulled" | model name not in `ollama list` | `ollama pull llama3.1:8b` |
| Assessment failed: JSON error | model returned malformed output | click Assess again; consider a larger model |
| "Folder not found" on Scan | path typed by hand | use Copy as Pathname from Finder |
| Every control matches the same document | threshold too low | raise the slider on the Scan tab |

## 12. Limits to be aware of

- Single user, local files, no login. Suitable for a practitioner's own engagement toolkit; not for shared or multi-tenant use without adding authentication and evidence-retention controls.
- Retrieval is keyword-based (BM25). It finds documents that use the control's vocabulary; it will miss evidence written in very different words. The threshold slider and the Preview matches table are there to catch this.
- Environment signals are filename patterns, not a live scan of any system. A file named `iam_policy.json` is a hint to look, not proof.
- The assessor is a language model. It proposes; the validation rules make it more conservative; the reviewer decides. Treat its ratings as a first pass, not a finding.
