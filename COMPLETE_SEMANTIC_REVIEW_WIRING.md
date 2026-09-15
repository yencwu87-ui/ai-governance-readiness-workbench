# Complete Semantic Review Wiring

## Purpose

The review workspace now treats semantic requirement elements, verification guidance, assessor output, reviewer judgement, and challenge as separate layers across all 195 governed controls.

## Runtime separation

1. **Requirement element** — what must be true.
2. **Expected evidence** — artefacts that may demonstrate the element.
3. **Verification guidance** — how a reviewer/tester may inspect the evidence. This never becomes a requirement.
4. **Reviewer reading** — the human marks each element met / not evidenced / n/a.
5. **AI assessment** — an independent proposal against the same canonical elements.
6. **Comparison** — deterministic element-by-element comparison.
7. **Challenge** — interrogates the human reviewer reading; it cannot become the recorded decision.
8. **Decision** — remains with the human authority.

## Gap hygiene

Visible assessor gaps are now required to be anchored to canonical requirement elements. Unanchored output, including copied ToD/ToE procedures, is retained only as assessor diagnostics and is not rendered as a governed finding.

## MAS source review

The sidebar supports staging an updated MAS consultation paper/whitepaper as PDF, TXT, Markdown or DOCX. The uploaded source is session review context only. It does not replace the authoritative contract and is not treated as organisational evidence. Each MAS control displays the strongest matching source passages for manual review.

Adopting an uploaded source into the authoritative contract remains a separate governed action; upload alone never changes requirements.

## Current semantic inventory

- Controls: 195
- Semantic elements: 562
- MAS: 30 controls / 101 elements
- MGF Agentic: 34 / 126
- SAFR: 21 / 84
- NIST AI RMF: 72 / 212
- ISO 42001: 38 / 39
- Deterministic: 19
- Human judgement: 542
- Out-of-band: 1
