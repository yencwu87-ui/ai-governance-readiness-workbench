# Challenge My Read — Factual Pointers

A challenge is not considered grounded merely because it contains a plausible explanation. Each challenge now carries a **factual pointer** that must be verifiable against the supplied evidence.

## Required reasoning chain

`Observation → Evidence basis → Requirement basis → Knowledge / precedent → Inference → Control risk → Factual pointer → Resolution pointer → Challenge → Reviewer action`

## Factual pointer

The factual pointer contains:

- `source`: the supplied evidence source label, or `reviewer_supplied` for manually entered evidence
- `locator`: currently `matched_quote`; this is deliberately conservative until page/row/line locators are available from the source adapter
- `quote`: the exact quoted fact from the supplied evidence
- `fact`: the same verified fact
- `what_it_supports`: what the fact establishes for the challenge

The validator rejects a challenge if the quoted fact cannot be found in the supplied evidence.

## Control-risk pointer

`risk_to_address` states the concrete control risk if the challenge is valid.

This is separate from `challenge`: the challenge asks the reviewer to answer; the risk states why it matters.

## Resolution pointer

`resolution_pointer` states the specific artefact, record, test result, field, or factual condition that would resolve the challenge.

Example:

> Provide the post-implementation verification record for WB-025.

This makes Challenge My Read actionable rather than merely argumentative.

## Evidence versus knowledge

Evidence is factual basis. Governance Knowledge is interpretive context. A knowledge memory can strengthen or explain a challenge but cannot substitute for factual evidence and cannot override a requirement.
