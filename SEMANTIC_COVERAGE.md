# Full Governed-Control Semantic Coverage

Registry SHA-256: generated in `governance/knowledge/semantic_registry.sha256`.

- Controls covered: **195 / 195**
- Requirement elements covered: **562 / 562**
- Deterministic elements: **19**
- Human-judgement elements: **542**
- Out-of-band elements: **1**
- Instrument-match candidates: **523**
- ISO/internal governed-source elements: **39**
- Source-review-required elements: **0**
- Audit-linked controls PASS: **135** · REVISE: **47** · not in audit sheet: **13**

## Framework coverage

| Framework | Controls | Elements |
|---|---:|---:|
| MAS | 30 | 101 |
| MGF Agentic | 34 | 126 |
| SAFR | 21 | 84 |
| NIST AI RMF | 72 | 212 |
| ISO 42001 | 38 | 39 |

## Meaning

Every governed control has an explicit semantic record and every governed element has intent, source basis, expected evidence, applicability and verification mode. This is semantic coverage; it is not a claim that every element is automatically deterministic.

## Verification modes

`DETERMINISTIC` = executable predicate exists. `HUMAN_JUDGEMENT` = semantically defined but not converted into an invented Boolean rule. `OUT_OF_BAND` = authoritative evidence is outside the current evidence-bundle boundary.

## Grounding

MGF Agentic, MAS, SAFR and NIST AI RMF elements use the supplied instrument corpus as the semantic grounding layer. ISO 42001 remains grounded to the internal Requirement Element Audit/workbook because no ISO instrument text is in the repository. Instrument matches are provenance candidates, not human source-signoff.
