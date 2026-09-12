# Control Testing Brain

The Control Testing Brain is the normalized, local testing knowledge layer derived from the governed
AI Governance Playbook workbook:

`data/AI_Governance_Playbook_MGF_SAFR_FINAL_v3_CSA_backref.xlsx`

It covers 195 populated control rows across ISO/IEC 42001, NIST AI RMF, MAS, IMDA MGF Agentic AI and SAFR.
Three workbook rows without a usable control ID/title are excluded from the runtime KB rather than inventing identities.

## Authority model

- `exact` means the workbook provided a Test of Design and/or Test of Operating Effectiveness value.
- `draft_derived` means the workbook test cell was blank and the engine generated a draft testing procedure from the control row,
  declared evidence, objective/requirement and linked playbook steps.

`draft_derived` entries are advisory examples until an accountable reviewer approves them.

## Runtime role

The Assessor and Challenger can retrieve the testing record for the control they are assessing.
The testing record tells the model what to test and what evidence to look for; it is not a governance decision and must never be treated as evidence itself.

### Source separation

`requirements/mas.yaml` answers **what the MAS control requires**.

The Control Testing Brain answers **how the control can be tested**.

The Governance Knowledge Brain answers **what approved interpretations, precedents and failure patterns may inform reasoning**.

Submitted evidence answers **what actually happened**.

This separation is intentional and should be preserved.
