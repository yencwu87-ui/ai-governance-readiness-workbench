# WB-100 Release Notes - Requirement Triangulation & Element Sufficiency

Date: 2026-09-14

## What changed

WB-100 adds a requirement-proof layer above the WB-099 element backbone.

### New capabilities

- Versioned source registry with authority tier, normative status, lifecycle status, publication date, effective window, supersession and content hash.
- Temporal `as_of` assessment so historical assessments are reproducible and future proposals cannot silently become current requirements.
- Requirement triangulation across authoritative source text, supervisory material, proposed consultations, implementation guidance and failure observations.
- Explicit distinction between `required`, `future_candidate`, `supporting_context`, `challenge`, `parallel_regulatory_context` and `out_of_scope` treatments.
- Element assurance dimensions for TOD, TOE, failure/near-miss, resolution, sufficiency boundary, test provenance and change/re-validation.
- Control-level source mapping coverage and element sufficiency checks.
- Regulatory-change drafts now carry a source snapshot and temporal change alerts.
- P012-2026 TRM consultation paper added as an immutable source snapshot with SHA-256 provenance.
- M3.6 assurance overlay and triangulation findings demonstrating the model.

## Important design decision

WB-100 does not make the web, RAG, or any consultation paper an automatic requirement author. External material can corroborate, challenge, or propose future candidates. Promotion into the governed requirement layer remains a human-controlled release decision.

## MAS change handling

The P012-2026 consultation is represented as `proposed` / `consultation`. It is never treated as an effective replacement for the baseline TRM Notices until a final Notice and effective date are explicitly recorded. The attached paper itself states that comments were due 31 July 2026 and that the revised requirements were proposed to take effect 12 months after final publication.

The same model applies to MAS P017-2025 AI Risk Management consultation material used for M3.6: useful for triangulation and future-state challenge, but not a final binding requirement by itself.

## Validation

Targeted WB-100 and adjacent regression tests: **13 passed**.

Full repository test execution reached >200 passing tests before stopping on an unrelated existing failure in `tests/test_disagreement_pass_wb030.py::test_unverifiable_quote_is_rejected`. That failure concerns the pre-existing challenge quote-verification path and is outside WB-100's changed code path.
