# WB-052 — Requirement Element Audit & Revision

## Purpose

This release audits and revises the **Requirement elements (atomic — the unit of challenge)** field across all 195 controls in the governed workbook.

The core rule is now explicit:

> A requirement element is an atomic proposition traceable to the source requirement/outcome. Test procedures, playbook references, evidence floors, challenge failure modes, maturity guidance, and internet knowledge do not create new requirement obligations.

## What was wrong

The audit found structural problems in the previous element field:

- NIST AI RMF: rows used `Not tested` in the requirement-element field in multiple cases.
- MGF Agentic and SAFR: rows used `Play X` references rather than requirement propositions.
- MAS: some workbook rows contained operating-test material in the element field. Runtime MAS contracts remain governed by `requirements/mas.yaml`, which already supplies the authoritative MAS requirement semantics and elements.
- ISO 42001: several rows carried generic archetype-derived elements that did not match the specific control requirement (for example, resource/documentation controls receiving generic methodology or change-control elements).

## Revision rule

### 1. Requirement = obligation

The source requirement/outcome defines what must be true.

### 2. ToD/ToE = test method

Test of Design and Test of Operating Effectiveness explain how to test the requirement. They are not additional requirements.

### 3. Evidence floor = testability boundary

An evidence floor can make a result `NOT TESTABLE`; it does not create a new control obligation.

### 4. Challenge bank = failure-mode context

Near-miss failure modes tell the challenger what can defeat a conclusion. They do not expand the requirement.

### 5. Internet = contextual knowledge

Current external knowledge may help the assessor/challenger understand a topic, but it cannot create a new compliance obligation or become organisational evidence.

## Framework treatment

- **ISO 42001:** elements are derived from the `Requirement (summary)` text; explanatory rationale is excluded from the obligation where separable.
- **NIST AI RMF:** the `Subcategory outcome` is treated as the normative source; the category statement is contextual.
- **MAS:** the workbook's `MAS expectation area` is used for the local workbook proposition. Runtime authoritative semantics continue to come from `requirements/mas.yaml`.
- **MGF Agentic / SAFR:** the `Objective — what it bounds` text is converted into requirement propositions; play references are removed from the element field.

## Result

All **195 controls** were rewritten into a traceable requirement-element set. The audit sheet preserves the previous element field and records the structural defect classification.

The revised workbook is:

`AI_Governance_Playbook_MGF_SAFR_v0.5.2_requirement_elements_audited.xlsx`

## Expected reasoning behaviour

If every explicit requirement element is `MET`, a challenger can still raise a maturity or robustness concern, but that concern should not silently create a new requirement element. A challenge should invalidate the control conclusion only when it points to an explicit requirement/evidence/test condition that is actually contradicted or unsatisfied.
