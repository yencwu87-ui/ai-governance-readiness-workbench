# Merge notes — Lane B (continuous control testing) into the workbench

## What changed

| File | Change |
|---|---|
| `caa/` | New package. Deterministic pipeline: adapters → checks → hashed bundle → review. |
| `caa/adapters/environment_scan.py` | Wraps your `scanner.scan_environment()` as a Lane B evidence source. `scanner.py` itself is unchanged. |
| `caa/review.py` | The only code that writes `human_verdict`. Refuses to sign a tampered bundle. |
| `controls/mcm.yaml`, `controls/discovery.yaml` | 12 controls as data. Discovery controls use scanner signals. |
| `schemas/` | Contracts for control, inventory, evidence bundle. |
| `audit.yaml` | Source → adapter mapping. `target` is overridden by the app's folder field or `--target`. |
| `pipeline.py` | Lane A functions untouched. Lane B functions appended: `run_audit`, `sign_result`, `unsign_result`, `list_bundles`, `load_bundle`, `open_items`, `control_history`. |
| `app.py` | Two new tabs, **Audit** and **History**. Existing four tabs unchanged except they now show an info message instead of stopping the app when no playbook is loaded. |
| `requirements.txt` | + `pyyaml`, `jsonschema`. |
| `.github/workflows/audit.yml` | CI gate on push, nightly scheduled run. |
| `examples/sample_repo/` | Seeded git repo with planted defects for demos. |

Not touched: `assessor.py`, `playbook.py`, `scanner.py`, `data/`.

## How to apply

1. Unzip over the repo root. Only `pipeline.py`, `app.py`, `requirements.txt` are overwritten; back them up first if you have local edits since 5 Sep.
2. `pip install -r requirements.txt`
3. Add `evidence/` to `.gitignore` for now (decide later whether bundles live in git, an evidence branch, or object storage).
4. `streamlit run app.py` → Audit tab → point at `examples/sample_repo` → Run audit. Expect 9 FAIL.
5. Point it at the workbench repo itself. Expect mostly NOT_TESTABLE for MCM-01..04, 08..10 until you create `governance/` exports. That list is your adapter backlog.

## Two lanes, one reviewer

| | Lane A (existing) | Lane B (new) |
|---|---|---|
| Question | Does the evidence support the control? | Is the control operating? |
| Method | BM25 retrieval + LLM proposal | Deterministic checks over artefacts |
| Output | sufficiency / maturity proposal | PASS / FAIL / NOT_TESTABLE + findings |
| Human | `record_decision()` | `sign_result()` |
| Persistence | `data/assessments.json` + playbook write-back | `evidence/bundles/*.json`, hashed, append-only |
| Trigger | reviewer-initiated | on_commit / on_deploy / scheduled / manual |

Lane B answers "is it running"; Lane A answers "is it designed right". A mature programme needs both, and the Report tab is the natural place to eventually join them per control id.

## Next

- Build governance exports for your own repo (tickets, registry, evals as CSV/JSON).
- Add `DISC-03` (prompts under version control) once you build a derived source that flattens `git_log.paths`.
- Join lanes in the Report tab: for each Lane A control id, show the latest Lane B verdicts of controls that reference it in `framework_refs`.
