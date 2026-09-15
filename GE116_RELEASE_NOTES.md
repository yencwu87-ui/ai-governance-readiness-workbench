# GE-116 — UI/service boundary + governed deterministic predicates

## Delivered

- Added `services/governance_service.py` as the service boundary used by the Governance Engine UI.
- Added `ui/governance_engine.py` as a projection-only render surface.
- Replaced the old inline Governance Engine tab logic in `app.py` with the service/UI seam.
- Kept predicate execution, contract interpretation and result aggregation outside `app.py`.
- Added `governance/specs.py` and the governed M3.6 predicate specification at `governance/knowledge/predicate_specs.yaml`.
- Added `governance/control_evaluator.py` to evaluate governed element specifications and aggregate them into a deterministic control result.
- Added `fields_truthy` to the deterministic check registry so boolean evidence cannot pass merely because a field exists.
- Added applicability handling for conditional M3.6 elements.
- Kept e14 out-of-band: it has no observation verdict and is not scored by the evaluator.
- Added tests pinning the predicate specification text to the governed M3.6 contract text.
- Added tests for temporal ordering, conditional applicability and false boolean evidence.
- Fixed the `app.py` `_contract_report` definition-order runtime failure in the base package.

## Verification

- GE-focused regression suite: 203 passed.
- `python -m py_compile` across governance/services/ui and `app.py`: passed.
- Full historical pytest run: timed out at ~21% without a reported test failure; no full-suite pass is claimed.

## Scope boundary

This increment decomposes the Governance Engine surface into a service layer and projection module. The legacy Scan/Review/Report/Outcomes/Audit/History/Lifecycle tabs remain in the existing Streamlit entrypoint; a full `st.navigation` page migration is intentionally separate from the deterministic-engine work.
