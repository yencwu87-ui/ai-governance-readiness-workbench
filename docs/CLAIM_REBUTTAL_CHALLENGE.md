# Claim-Rebuttal Challenge Engine

`Challenge My Read` is governed as a claim-rebuttal workflow, not a relevance search.

For each challenge the model is asked to identify:

1. the exact reviewer claim being tested;
2. the factual evidence actually established by the supplied material;
3. the applicable requirement element from `requirements/mas.yaml`;
4. the interpretation/precedent used from the local Governance Knowledge Brain;
5. the inference connecting fact to concern;
6. whether the fact materially rebuts the reviewer claim;
7. the control risk affected; and
8. the artefact/fact that would resolve the risk.

## Rebuttal strengths

- `strong`: evidence materially contradicts or changes the disputed reviewer proposition;
- `weak`: evidence is relevant and may refine the read, but does not overturn it;
- `rejected`: the alleged rebuttal is unsupported or not actually tied to the evidence.

Only `strong` challenges count as a substantive challenge. `weak` challenges remain visible as
review refinements. `rejected` challenges remain auditable but must not be presented as grounds
for overturning the reviewer.

## Authority boundary

`requirements/mas.yaml` is the authoritative requirement source. Submitted evidence is the
factual source. The local Governance Knowledge Brain is advisory context only.

The Challenger never issues or changes a governance rating.
