# WB-101 — Multi-Modal Retrieval Plane & Episodic Challenge Memory

WB-101 replaces the assessor/challenger's source-ambiguous knowledge block with a typed,
read-only retrieval contract. The contract does not alter governed requirements, evidence,
model validation, or the human decision path.

## Lanes

`semantic` carries the existing governed-brain and element-level lexical/embedding/RRF results.
`episodic` queries only previously **decided** cycles in the append-only event log; curated
`brain.yaml` precedents remain semantic material and are not misrepresented as history.
`procedural` carries the existing control-testing and element testing metadata (ToD, ToE,
plays, expected artefacts and capability hints). `regulatory` carries versioned source-registry
records separated into effective, proposed and superseded groups, plus the optional web check.

## Receipt and audit boundary

Each resolution exposes `retrieval_receipt` with attempted, completed, result-count, degraded
and error states per lane. It is persisted in the knowledge monitor and returned with assessor
and challenger outputs. A zero episodic result therefore means “no matching decided episode,”
not “episodic retrieval was never attempted.”

The model-facing package is JSON with named lanes. The old flattened context formatter remains
for display compatibility only. Historical episodes are decision context; they never become
evidence for the current assessment and cannot change its rating or requirement boundary.
