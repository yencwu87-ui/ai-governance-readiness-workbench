# WB-100 - Requirement Triangulation & Element Sufficiency Engine

## Objective

Prevent a control's canonical element list from becoming an unproved interpretation. WB-100 adds a versioned source registry, temporal lifecycle, triangulation findings, assurance sufficiency dimensions, and a challenge-only external back-test layer.

## Architecture

```text
Authoritative source(s)
        |
        +--> source registry / lifecycle / hashes
        |
        +--> obligation extraction
        |
        +--> canonical element
        |
        +--> triangulation findings ----------------+
        |                                            |
        +--> TOD / TOE -------------------------------+
        +--> failure + near-miss ----------------------+
        +--> resolution -------------------------------+
        +--> sufficiency boundary ---------------------+--> assurance card
        +--> test provenance ---------------------------+
        +--> change / re-validation --------------------+
                                                     |
                                             sufficiency / gap vector
                                                     |
                                            assessor / challenger
                                                     |
                                                human promotion
```

## Core design rules

1. **Canonical requiredness is gated by source authority and lifecycle.** Proposed/consultation material cannot overwrite a live requirement.
2. **External/web evidence is challenge material.** It can corroborate, expose a gap, or create a future candidate; it cannot silently create a canonical element.
3. **Temporal assessment is explicit.** Every assessment has an `as_of` date. Source records carry publication, consultation, effective and supersession windows.
4. **Parallel reads are explicit.** A source can be related as `parallel_regulatory_context` without becoming an additional element of the target control.
5. **Assurance dimensions are orthogonal to canonical elements.** TOD, TOE, failure modes, resolution, sufficiency boundary, test provenance, and change/re-validation belong in the assurance contract. They become separate canonical elements only when the authoritative source creates a distinct obligation.
6. **Promotion remains human-governed.** A triangulation report is not a requirements release.

## Requirement confidence model

```text
ObligationConfidence =
    Authority
  x NormativeNecessity
  x TemporalValidity
  x ScopeFit
  x Lexical/semantic support
  x (1 - ConflictPenalty)
```

This is an engineering confidence indicator, not a legal conclusion.

Hard rule:

```text
proposed / consultation / voluntary / industry
    -> cannot establish current canonical requiredness
```

## Sufficiency model

Each element may require:

- `tod`
- `toe`
- `failure_modes`
- `resolution`
- `sufficiency_boundary`
- `test_provenance`
- `change_revalidation`

The engine returns a coverage vector and a list of missing dimensions. It deliberately avoids a single opaque score.

## MAS temporal model

The source registry contains, at minimum, the November 2025 MAS AI Risk Management consultation, the June 2026 MAS TRM consultation P012-2026, the effective TRM baseline, and the December 2024 AI Model Risk Management paper.

P012-2026 is stored as `proposed` because it was a consultation paper. The source material states that MAS invited comments by 31 July 2026 and proposed that the revised Notice take effect 12 months after finalisation. It therefore remains a future-change signal until a final Notice and effective date are separately verified.

## M3.6 result

WB-100 deliberately does **not** promote every testing concern into an element. The current 14-element M3.6 decomposition is retained as a governed-draft candidate, while the triangulation report evaluates:

- direct source corroboration,
- future-change signals,
- source mapping gaps,
- assurance dimension sufficiency,
- parallel TRM dependencies.

The parallel TRM finding is intentionally classified as technology-risk context rather than an M3.6 element expansion.

## Runtime entry point

```bash
python tools/triangulate_requirements.py \
  --control M3.6 \
  --elements eval/corpus/M3.6/elements.yaml \
  --findings requirements/triangulation/M3.6_findings.yaml \
  --sources requirements/triangulation/sources.yaml \
  --as-of 2026-09-14 \
  --out requirements/triangulation/M3.6_2026-09-14.json
```

A non-zero exit means the element set is not yet sufficiently proven for review/promotion.

## Future work hook

A live web collector can feed the same `findings` contract. Required fields should include:

```yaml
source_id:
url:
retrieved_at:
locator:
excerpt:
excerpt_sha256:
supports:
finding_type:
```

The collector is deliberately decoupled from promotion so a transient website change cannot rewrite the governed requirement set.
