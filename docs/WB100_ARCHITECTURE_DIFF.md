# WB-100 Architecture Diff vs WB-099

## Before

```text
Control
  -> Canonical Element
  -> Element-scoped RAG
  -> Testing metadata
  -> Observations
  -> Deterministic tests
  -> Assessor
  -> Challenger
  -> Human decision
```

## After

```text
Control / Instrument Set
        |
        +--> Versioned Source Registry
        |       - authority tier
        |       - normative status
        |       - lifecycle status
        |       - effective window
        |       - supersession
        |       - content hash
        |
        +--> Requirement Triangulation
        |       - direct source corroboration
        |       - supervisory/context evidence
        |       - proposed/future signals
        |       - failure/near-miss signals
        |       - parallel regulatory dependencies
        |
        +--> Canonical Element
        |       |
        |       +--> Assurance Card
        |              - TOD
        |              - TOE
        |              - failure / near-miss
        |              - resolution
        |              - sufficiency boundary
        |              - test provenance
        |              - change / re-validation
        |
        +--> Sufficiency + Gap Vector
        |
        +--> Evidence / Deterministic Testing
        |
        +--> Assessor / Challenger
        |
        +--> Human promotion / release
```

## Key invariants

1. RAG may enrich and challenge an element; it may not redefine its canonical identity.
2. A proposed source cannot establish current requiredness.
3. A parallel regulatory source can affect assurance/testing context without creating a new element in the target control.
4. Every promoted element needs traceable source-obligation references.
5. Assurance dimensions do not automatically become elements.
6. Historical assessments must resolve against the source state at the assessment `as_of` date.
