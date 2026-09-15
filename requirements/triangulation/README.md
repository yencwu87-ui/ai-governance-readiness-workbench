# WB-100 Requirement Triangulation Store

This directory is the governance workspace for proving that a canonical element list is relevant, complete enough to review, and temporally correct.

## Transparency rule

A triangulation run is **not complete** unless the report records an online-check manifest. The manifest must show:

- whether online research was attempted and completed;
- the exact search queries;
- retrieval timestamp;
- every URL/source checked;
- source classification and authority tier;
- purpose/result of the check;
- limitations.

Online evidence may corroborate, challenge, or surface a future candidate. It cannot create a canonical element.

## Human decision rule

Every element must have an explicit human disposition:

`pending_human | include | exclude | merge | split | candidate_pending_source | parallel_context`

The engine does not infer final element membership from confidence, RAG, web results, or testing metadata.

## Temporal rule

The effective requirement is evaluated as of an `as_of` date. Proposed, consultation, superseded, expired and historical material cannot silently become current requiredness.

## Runtime

For a transparent audit gate:

```bash
python tools/validate_triangulation.py \
  --control M3.6 \
  --elements eval/corpus/M3.6/elements.yaml \
  --findings requirements/triangulation/M3.6_findings.yaml \
  --sources requirements/triangulation/sources.yaml \
  --web-log requirements/triangulation/web_research_log.yaml \
  --decisions requirements/triangulation/M3.6_element_decisions.yaml \
  --as-of 2026-09-14 \
  --out requirements/triangulation/M3.6_transparent_audit_2026-09-14.json
```

A non-zero exit means the control is **not yet ready for element-list promotion**.

## Human disposition

Use `tools/decide_elements.py` to record the final reviewer decision. For example:

```bash
python tools/decide_elements.py \
  --decisions requirements/triangulation/M3.6_element_decisions.yaml \
  --element e13 --status candidate_pending_source \
  --reviewer reviewer-name \
  --rationale "Residual-risk requirement is source-supported; named-owner component needs explicit source anchor." \
  --decided-at 2026-09-14T12:30:00+08:00
```

The decision remains separate from the triangulation score and is carried into the audit report.
