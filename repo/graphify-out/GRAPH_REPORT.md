# Graph Report - repo  (2026-09-05)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 62 nodes · 110 edges · 11 communities (7 shown, 4 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f75e64bf`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- assessor.py
- playbook.py
- scanner.py
- app.py
- index_folder
- Path
- Chunk
- pipeline.py
- build_evidence
- propose
- record_decision

## God Nodes (most connected - your core abstractions)
1. `assess()` - 9 edges
2. `scan_documents()` - 6 edges
3. `index_folder()` - 6 edges
4. `extract()` - 6 edges
5. `load_controls()` - 5 edges
6. `write_back()` - 5 edges
7. `Control` - 4 edges
8. `Chunk` - 4 edges
9. `_validate()` - 4 edges
10. `scan_environment()` - 4 edges

## Surprising Connections (you probably didn't know these)
- `propose()` --calls--> `assess()`  [EXTRACTED]
  pipeline.py → assessor.py
- `export_playbook()` --calls--> `write_back()`  [EXTRACTED]
  pipeline.py → playbook.py
- `index_folder()` --calls--> `scan_documents()`  [EXTRACTED]
  pipeline.py → scanner.py
- `index_folder()` --calls--> `scan_environment()`  [EXTRACTED]
  pipeline.py → scanner.py
- `_load()` --calls--> `load_controls()`  [EXTRACTED]
  app.py → playbook.py

## Import Cycles
- None detected.

## Communities (11 total, 4 thin omitted)

### Community 0 - "assessor.py"
Cohesion: 0.25
Nodes (12): _anthropic(), assess(), model_name(), _norm(), _ollama(), _parse(), pdf_text(), _prompt() (+4 more)

### Community 1 - "playbook.py"
Cohesion: 0.29
Nodes (8): _load(), cache_data, Control, _header_map(), load_controls(), Load control libraries from the AI Governance Playbook workbook and write…, Write accepted decisions into a copy of the workbook. Returns number of rows…, write_back()

### Community 2 - "scanner.py"
Cohesion: 0.43
Nodes (6): chunk_text(), iter_files(), Scan local folders for evidence and map it to controls. Two scans:…, scan_documents(), scan_environment(), Signal

### Community 4 - "index_folder"
Cohesion: 0.40
Nodes (5): Index, index_folder(), match_controls(), Stage 1 — deterministic. Read documents, build the search index, detect…, Stage 2 — deterministic. Best passages per control; controls with no match are…

### Community 5 - "Path"
Cohesion: 0.70
Nodes (5): Path, _docx(), extract(), _pdf(), _xlsx()

### Community 7 - "pipeline.py"
Cohesion: 0.50
Nodes (3): gap_analysis(), Pipeline nodes. Each function is one stage; the graph of calls is the…, Stage 5a — report. Everything below full, prioritised: none, then no evidence,…

### Community 8 - "build_evidence"
Cohesion: 0.67
Nodes (3): build_evidence(), Assemble the evidence record a control will be assessed on., signals_for()

## Knowledge Gaps
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `index_folder()` connect `index_folder` to `scanner.py`, `app.py`, `pipeline.py`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Why does `export_playbook()` connect `app.py` to `playbook.py`, `pipeline.py`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Why does `Index` connect `Chunk` to `scanner.py`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._