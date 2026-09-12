# P1-09 — Rubric & Label Governance

## Purpose

Treat the evaluation rubric and human labels as governed artefacts. Model performance must not be interpreted from headline accuracy alone.

## v0.4 controls

1. Every labelled case has a concrete one-line reviewer justification.
2. `none`, `partial`, and `full` are governed by explicit element-level boundaries.
3. `none` and `partial` maturity ceilings are enforced.
4. Diagnostic evaluation sets require at least 5 examples of each class and reject a dominant class above 60%.
5. Aggregate scoring reports actual and predicted class distributions.
6. Aggregate scoring reports a 3x3 confusion matrix, per-class precision/recall/F1, macro-F1, and balanced accuracy.
7. Ambiguous cases are excluded from scoring but retained for review.
8. Synthetic and real evidence remain separately attributable.
9. Optional second-reviewer labels can be added later; the governance layer intentionally does not fabricate inter-rater agreement.

## Current diagnostic corpus

The v0.4 golden set has 25 labelled cases:

- none: 11
- partial: 8
- full: 6
- real: 10
- synthetic: 15

The set is distribution-ready for diagnostic purposes because every class is sufficiently represented and no class exceeds the 60% dominance threshold.

It remains too small for a production promotion gate. The target remains 50+ cases for v0.4 and 75–100 for a stronger release corpus.

## Interpretation

The diagnostic set is intentionally not a forecast of operational class frequencies. A separate production-distribution set should be maintained for workload realism.
