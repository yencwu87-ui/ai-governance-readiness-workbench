# Graph Report - repo  (2026-09-05)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 88 nodes · 157 edges · 10 communities (7 shown, 3 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `dbba0441`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- docs/pipeline.py
- scanner.py
- playbook.py
- assessor.py
- pipeline.py
- app.py
- run_scan
- build_evidence
- record_decision
- Index

## God Nodes (most connected - your core abstractions)
1. `assess()` - 10 edges
2. `run_scan()` - 8 edges
3. `scan_documents()` - 7 edges
4. `index_folder()` - 7 edges
5. `index_folder()` - 6 edges
6. `run_scan()` - 6 edges
7. `extract()` - 6 edges
8. `write_back()` - 6 edges
9. `scan_environment()` - 5 edges
10. `load_controls()` - 5 edges

## Surprising Connections (you probably didn't know these)
- `build_evidence()` --calls--> `signals_for()`  [EXTRACTED]
  docs/pipeline.py → scanner.py
- `export_playbook()` --calls--> `write_back()`  [EXTRACTED]
  docs/pipeline.py → playbook.py
- `index_folder()` --calls--> `scan_documents()`  [EXTRACTED]
  docs/pipeline.py → scanner.py
- `index_folder()` --calls--> `scan_environment()`  [EXTRACTED]
  docs/pipeline.py → scanner.py
- `propose()` --calls--> `assess()`  [EXTRACTED]
  docs/pipeline.py → assessor.py

## Import Cycles
- None detected.

## Communities (10 total, 3 thin omitted)

### Community 0 - "docs/pipeline.py"
Cohesion: 0.13
Nodes (18): build_evidence(), export_playbook(), gap_analysis(), index_folder(), match_controls(), propose(), Index, Pipeline nodes. Each function is one stage; the graph of calls is the… (+10 more)

### Community 1 - "scanner.py"
Cohesion: 0.22
Nodes (14): Path, Chunk, chunk_text(), _docx(), extract(), Index, iter_files(), _pdf() (+6 more)

### Community 2 - "playbook.py"
Cohesion: 0.24
Nodes (9): _load(), cache_data, Control, _header_map(), load_controls(), Load control libraries from the AI Governance Playbook workbook and write…, Write accepted decisions into a copy of the workbook. Returns number of rows…, write_back() (+1 more)

### Community 3 - "assessor.py"
Cohesion: 0.29
Nodes (11): _anthropic(), assess(), model_name(), _norm(), _ollama(), _parse(), pdf_text(), _prompt() (+3 more)

### Community 4 - "pipeline.py"
Cohesion: 0.32
Nodes (5): Headless scan: python run_scan.py <folder> [--scope MAS,SAFR] [--min-score 4]…, gap_analysis(), Pipeline nodes. Each function is one stage; the graph of calls is the…, Stage 5a — report. Everything below full, prioritised: none, then no evidence,…, Headless scan: python run_scan.py <folder> [--scope MAS,SAFR] [--min-score 4]…

### Community 5 - "app.py"
Cohesion: 0.29
Nodes (4): export_playbook(), propose(), Stage 3 — probabilistic under a harness. Returns a proposal; records nothing., Stage 5b — write-back. Only recorded decisions are written.

### Community 6 - "run_scan"
Cohesion: 0.33
Nodes (7): index_folder(), match_controls(), Index, Stage 1 — deterministic. Read documents, build the search index, detect…, Stage 2 — deterministic. Best passages per control; controls with no match are…, Headless orchestration of stages 1–3. Returns (evidence, proposals). Never…, run_scan()

## Knowledge Gaps
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `index_folder()` connect `run_scan` to `scanner.py`, `pipeline.py`, `app.py`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `index_folder()` connect `docs/pipeline.py` to `scanner.py`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Why does `write_back()` connect `playbook.py` to `docs/pipeline.py`, `app.py`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Should `docs/pipeline.py` be split into smaller, more focused modules?**
  _Cohesion score 0.13450292397660818 - nodes in this community are weakly interconnected._