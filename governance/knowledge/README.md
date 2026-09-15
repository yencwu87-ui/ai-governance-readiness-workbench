# Governance Knowledge Brain

The knowledge brain is advisory institutional context for the AI assessor and AI challenger. It is not a decision engine.

## Authority order

1. `authoritative` — formal requirement/policy material
2. `approved_interpretation` — approved governance interpretations
3. `organisational_precedent` — prior human decisions
4. `example` — evidence/failure examples
5. `heuristic` — model-supporting heuristics

Lower tiers may explain or challenge, but never override higher-authority requirements, evidence, or human decisions.

Every assessment identity hashes `governance/knowledge/brain.yaml`, so changing the brain changes the governed assessment configuration.

Memory records should be treated like governed control content: change them through a WB ticket, review them, and keep prior versions for auditability.

## Challenge dossiers

`governance/challenge_dossiers.jsonl` is an append-only review trail for `Challenge My Read`.
A dossier snapshots the reviewer's read, the structured challenges, the evidence/requirement/
knowledge bases used by each challenge, and the human response to each challenge. Dossier
responses never change the governance rating directly; the normal reviewer decision path remains
the only rating/write-back authority.

## Challenge requirement authority

`Challenge My Read` uses `requirements/mas.yaml` as the authoritative source for the control requirement,
applicable Lane-A elements, scope and none/partial/full boundaries. The Governance Knowledge Brain is
advisory context only: it supplies approved interpretations, precedents and challenge patterns, but it
cannot override the governed requirement or submitted evidence.

Challenge factual pointers are independently verified against the supplied evidence and now include a
human-actionable locator such as `line:12` or `lines:12-13`. Requirement pointers resolve back to the
specific `requirements/mas.yaml` element used by the challenge.
