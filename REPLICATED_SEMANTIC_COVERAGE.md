# Replicated Governed-Control Semantic Coverage

This pass extends the instrument-first semantic decomposition beyond MGF Agentic.

## Coverage

- MAS: **101 semantic elements**
- MGF Agentic: **126 semantic elements**
- SAFR: **84 semantic elements**
- NIST AI RMF: **212 semantic elements**
- ISO 42001: **39 semantic elements**

- Total governed controls: **195**
- Total semantic elements: **562**
- Deterministic elements: **19**
- Human-judgement elements: **542**
- Out-of-band elements: **1**

## Method

- **MGF Agentic**: existing source-grounded decomposition retained and used as the pattern.
- **MAS**: existing 101-element audited decomposition retained; no blanket inflation was applied where the existing three-per-control elements were already purposeful.
- **SAFR**: decomposed from the SAFR white paper plus repository design-test guidance; SAFR is a reference white paper, not regulatory guidance.
- **NIST AI RMF**: decomposed from the NIST AI RMF Playbook suggested-action text where available; source language is retained as semantic guidance, not promoted into a new legal obligation.
- New elements remain HUMAN_JUDGEMENT unless an independent deterministic predicate exists. Instrument matches remain provenance candidates.
