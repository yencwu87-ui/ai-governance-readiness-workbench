# MAS requirement text — draft for review

Two controls, drafted to be corrected. The format below is proposed as the pattern for all
30; settle it on these two before writing the rest.

**Read this first.** The requirement text is a second-line judgement about what MAS expects
and what evidences it. It is the most defensible artefact in the project and the most
exposed to challenge, so every line needs to be yours. What follows is a starting draft:

- Lines marked `[MRM]` are supported by the Dec 2024 AI MRM thematic review, which I know
  reasonably well.
- Lines marked `[PRACTICE]` are drawn from general MAS supervisory expectation and standard
  2LoD practice, not from a specific paper. Defensible, but not citable as written.
- Lines marked `[CHECK P017]` are where I would expect the AIRG consultation paper to be the
  anchor and cannot verify it. **Do not ship these without reading the paper.** I do not know
  P017-2025 well enough to paraphrase it, and a requirement that misattributes a source is
  worse than one with no source at all.

---

## Proposed format

Each control gets four fields. Only the first two go in the prompt; the last two are for the
reviewer and for the corpus labels.

| Field | Purpose |
|---|---|
| `requirement` | One sentence: what the evidence must show. Goes in the prompt as `Requirement:` |
| `elements` | The things that must each be evidenced. Replaces the artefact string as the checklist |
| `boundary` | What separates full from partial from none. For the reviewer and the corpus |
| `source` | The instrument and, where known, the section |

`elements` is deliberately not the same as the workbook's "Evidence / artifact" column.
That column names the document; `elements` names what the document has to demonstrate.
"Change records" is an artefact. "Authorisation recorded before the first production
action" is an element.

---

## M3.12 — Change management

**requirement**
Changes to deployed AI models — including retraining, feature pipeline changes, threshold
adjustments and decommissioning — are authorised before implementation, and the change that
reached production is verifiably the change that was approved.

**elements**
1. Model changes are raised as changes, including scheduled retraining `[MRM]`
2. Authorisation is recorded before the first production action, including for emergency
   changes `[PRACTICE]`
3. Privileged access used to implement the change reconciles to the approved change and its
   named implementer `[PRACTICE]`
4. Production state after implementation is verified against the approved plan, with
   deviations approved rather than closed silently `[PRACTICE]`

**boundary**
- **none** — a procedure, target operating model or intent, with no change records
- **partial** — change records exist and cover the AI estate, but one or more of elements
  2–4 does not operate consistently across the tested population
- **full** — all four elements evidenced across a tested population. Observations or
  housekeeping findings in an assurance review do not prevent full

**source** — AIRG P017-2025 `[CHECK P017]`; AI MRM Paper (Dec 2024) on change and version
control over models `[MRM]`

**My reasoning, for you to attack.** Element 1 is the one I am most confident about and the
one most often missed in practice — retraining treated as BAU rather than as change is the
classic finding. Elements 3 and 4 come from your own audit experience rather than from any
paper, so they are defensible as good practice but you should decide whether they belong in
a *MAS* requirement or in an internal standard the requirement points at. If MAS does not
reach privileged-access reconciliation, putting it here overstates the regulator.

---

## M3.6 — Evaluation, testing & independent validation

**requirement**
Models are tested against their intended use before deployment and at material change, and
the results are reviewed by a function independent of the team that built the model, whose
opinion is issued without the builder's agreement.

**elements**
1. Test results exist for the specific model version deployed, not a testing policy or plan
   `[MRM]`
2. Testing covers performance against intended use and behaviour across material customer
   segments `[MRM]`
3. Review is performed by a function with no reporting line into the developing team and no
   contribution to the build `[MRM]`
4. The reviewer's opinion is issued independently — the model owner may correct facts, but
   does not approve the opinion `[PRACTICE]`
5. The depth of validation is proportionate to the model's assessed materiality `[MRM]`

**boundary**
- **none** — a testing standard, validation plan or intent, with no results
- **partial** — test results exist but independence is absent or not evidenced. Reciprocal
  peer review inside the developing team is partial credit, not independence
- **full** — results exist and the review is independent. Conditions, exceptions or open
  items recorded in the reviewer's own opinion do not prevent full; they evidence that the
  control operates

**source** — AI MRM Paper (Dec 2024), independent validation proportionate to materiality
`[MRM]`; AIRG P017-2025 `[CHECK P017]`

**My reasoning, for you to attack.** Element 5 is doing quiet work: it means a tier 4 model
peer-reviewed within the team may be *full*, while the same evidence for a tier 1 model is
*partial*. That is closer to how MRM actually operates, but it makes the rating dependent on
a materiality tier the assessor may not be able to see in the evidence. You may prefer to
drop element 5 and hold the independence bar constant, accepting that the tool is stricter
than the regulator. I would drop it for now — a requirement the assessor cannot evaluate is
worse than one that is slightly conservative.

---

## Open questions for you

1. **Where does this live?** The MAS sheet has no requirement column. A separate
   `controls/mas_requirements.yaml` keyed by control id is easier to version and review, and
   avoids the workbook — which matters because `write_back` already overwrites the artefact
   column, so load-bearing text on that sheet has a known failure mode.
2. **Do `elements` replace the artefact string in the prompt, or sit alongside it?**
   Replacing is cleaner. Keeping both risks the model treating the artefact name as a
   separate requirement, which is what produced today's misses.
3. **How far does a MAS requirement go?** Elements 3 and 4 of M3.12 are good practice you
   have audited against. Whether they belong in a requirement attributed to MAS, or in an
   internal standard the requirement references, is a judgement about how much the tool
   should assert on the regulator's behalf.
4. **Does the boundary belong in the prompt?** It is written above for the reviewer and for
   corpus labels. Putting it in the prompt would tell the model directly what full looks
   like — which is the thing today's probe showed is missing. Worth testing on these two
   before deciding.

## Test before you write the other 28

Both controls have three labelled documents. Wire these two requirements, run
`python eval/probe_corpus.py M3.6 M3.12`, and see whether 4/6 becomes 6/6. If two
requirements fix both misses, the format works and the remaining 28 are mechanical. If they
do not, you have spent an hour rather than a day.
