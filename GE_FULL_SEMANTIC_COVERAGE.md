# Full Governed-Control Semantic Coverage

Registry SHA-256: `832e21e3e325057a5ea639f09cdd27fafdb709d5516c7449a3d23cec90b7a2a4`

- Controls covered: **195 / 195**
- Requirement elements covered: **284 / 284**
- Deterministic elements: **19**
- Human-judgement elements: **264**
- Out-of-band elements: **1**
- Instrument-match candidates: **245**
- ISO/internal governed-source elements: **39**
- Source-review-required elements: **0**
- Audit-linked controls PASS: **135** · REVISE: **47** · not in audit sheet: **13**

## Framework coverage

| Framework | Controls | Elements |
|---|---:|---:|
| MAS | 30 | 101 |
| MGF Agentic | 34 | 39 |
| SAFR | 21 | 22 |
| NIST AI RMF | 72 | 83 |
| ISO 42001 | 38 | 39 |

## Meaning

Every governed control has an explicit semantic record and every governed element has intent, source basis, expected evidence, applicability and verification mode. This is semantic coverage; it is not a claim that every element is automatically deterministic.

## Verification modes

`DETERMINISTIC` = executable predicate exists. `HUMAN_JUDGEMENT` = semantically defined but not converted into an invented Boolean rule. `OUT_OF_BAND` = authoritative evidence is outside the current evidence-bundle boundary.

## Grounding

IMDA/MGF, MAS, SAFR and NIST elements receive instrument-match candidates from the supplied instrument corpus. ISO 42001 has no ISO instrument text in the repository, so its elements are grounded to the internal Requirement Element Audit/workbook. Instrument matches are provenance candidates, not human source-signoff.
