
## GE-117 / Canonical Observation Provider Milestone

The repository now has one authoritative Observation type in `governance.observation.Observation`.
The legacy `observations.py` module is a compatibility facade only. Built-in plugins emit the canonical type directly.

A read-only `validation_pack` provider is included for M3.6 structured observation sources. It consumes a producer-owned fact manifest and performs no governance interpretation. The fixture at `eval/observation_fixtures/M3.6_g_observations.json` is a demonstration observation source, not a gold judgement set.

The integration path is:

`validation_pack provider → canonical Observation → M3.6 predicate specifications → ControlResult`

A current fixture run produces 13 observations and a deterministic `FAIL` ControlResult; conditional elements are evaluated only when their contract preconditions hold, and e14 remains out-of-band.

This milestone proves the canonical observation/evaluation spine. It does not claim that the fixture is a measurement corpus or that the full Streamlit application has been exercised against a live external provider in this environment.

## Current maturity

The architecture is now at the read-only, continuous-assurance / Puppet-like-without-remediation phase:

- governed contracts define what must be verified;
- providers/plugins produce observations;
- predicates evaluate observations deterministically;
- resources/selectors define scope;
- planners identify required verification capabilities;
- findings and freshness represent state over time;
- human authority remains above the engine;
- there is intentionally no remediation executor.

The next work is breadth, provider coverage, production endpoint verification, predicate catalogue expansion, and operational hardening rather than another foundational architecture layer.

## GE-118 / MGF Agentic D1.2 predicate redesign

MGF Agentic D1.2 is now decomposed into six audited requirement elements rather than one generic "right-size controls to the level of risk" sentence. The executable predicates are grounded in the MGF Agentic instrument and the Requirement Element Audit. The contract deliberately tests whether the organisation has a reproducible, approved, load-bearing tiering method; it does not invent a mandated numeric Tier 1/2/3 scheme.

See `MGF_D1_2_REDESIGN.md` for the element and predicate mapping.

## Full governed-control semantic coverage

The governance engine now carries a semantic registry for the full governed inventory:

- **195/195 controls** have a reviewer-facing semantic record.
- **284/284 requirement elements** have intent, governed text, applicability, expected evidence, verification mode, and source basis.
- **19 elements** currently have executable deterministic predicates (M3.6 and MGF Agentic D1.2).
- **264 elements** remain explicitly `HUMAN_JUDGEMENT`; no invented Boolean predicates are used to create a false sense of automation.
- **1 element** is explicitly `OUT_OF_BAND`.

The instrument corpus is used as a grounding source for MAS, MGF Agentic, SAFR and NIST. ISO 42001 is grounded to the repository's Requirement Element Audit/workbook because no ISO instrument file is present. Instrument matches are provenance candidates, not regulatory sign-off.

The registry is in `governance/knowledge/semantic_registry.yaml`; the coverage summary is in `SEMANTIC_COVERAGE.md`.

Importantly, the semantic registry is separate from runtime verdicts: **semantic coverage tells the reviewer what the element means and how it is intended to be verified; ControlResult tells the reviewer what the currently observed evidence establishes.**


### Complete semantic review wiring

The review workspace separates requirement elements from verification procedures. Assessor gaps must be anchored to canonical elements; ToD/ToE material is advisory verification guidance and cannot silently become requirements. MAS controls support session-only upload of an updated source document for side-by-side source review.
