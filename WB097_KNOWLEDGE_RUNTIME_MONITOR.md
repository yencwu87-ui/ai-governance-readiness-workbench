# WB-097 — Knowledge Runtime Monitor

## Purpose

Shows exactly when `assessor`, `challenger`, and disagreement challenge retrieval consulted:

- local governance memories;
- control-testing knowledge;
- live internet search;
- returned internet findings actually available to the model.

This is observability only. It does not alter ratings, decisions, routing, or evidence.

## Runtime log

The monitor writes JSONL to:

`governance/knowledge_usage.jsonl`

Override with:

`WB_KNOWLEDGE_MONITOR=/path/to/knowledge_usage.jsonl`

Each row distinguishes:

- `local.attempted` / `local.used` / `local.memory_ids`
- `control_testing.attempted` / `control_testing.used`
- `internet.attempted` / `internet.used` / `internet.sources` / `internet.query`
- `internet.error`
- `channels_used`

`internet.attempted=true` does **not** mean internet findings were returned. `internet.used=true` means search results were actually returned and were therefore included in the advisory web context.

## UI

The Audit tab now contains a **Knowledge runtime monitor** with counters and a table of recent retrievals. The Review > AI assessment and Review > Challenge panes also show the latest retrieval trace for the current control.

## Important boundary

Local governance knowledge and control-testing knowledge remain advisory context. Internet material is advisory only and never becomes organisational evidence. A search failure is visible as degraded retrieval; it is not silently treated as a successful search.
