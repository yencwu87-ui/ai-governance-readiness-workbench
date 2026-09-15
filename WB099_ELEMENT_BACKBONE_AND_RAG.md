# WB-099 — Element Backbone + Sophisticated RAG

## What this build changes

The governed requirement element is now the shared key across the contract, retrieval, testing metadata, plugin capability hints, inference context, assessor output, challenge output, and runtime monitoring.

Canonical identity:

`control_id.requirement_id.element_id`

Example: `M3.6.R1.e7`.

The element registry is read-only. RAG, tools, plugins and models may attach observations or context to an element, but they cannot create, rename, or re-number governed elements.

## Runtime flow

1. Load the authoritative requirement contract.
2. Resolve the canonical element catalog.
3. For each selected element, expand the retrieval query with the element text, testing metadata, evidence types, failure condition and capability hints.
4. Retrieve local governance memories scoped to that element.
5. Retrieve control-testing knowledge scoped to that element.
6. Optionally use the existing local hybrid retriever (BM25 + Ollama embeddings) as a semantic rerank; results are fused with RRF and retained with retrieval-method metadata.
7. Internet retrieval remains advisory. By default it stays control-level to avoid N web calls for N elements. Set `WB_RAG_WEB_PER_ELEMENT=1` for bounded element-level regulatory searches.
8. Carry the resulting element context into assessor/challenger prompts.
9. Plugin observations and deterministic test results should attach using the same element key.
10. Persist the element-scoped retrieval digest in assessment/challenge output and the knowledge runtime monitor.

## Important governance invariant

RAG enriches an element. RAG never defines the element.

If a model produces an ungoverned pointer such as `e99`, validation remains fail-closed. A genuinely new governance concept should be reported as an unmapped observation/contract-gap candidate, not silently added to the contract.

## RAG controls

- `WB_RAG_HYBRID=1` (default): enable local BM25 + embedding rerank when Ollama embeddings are reachable.
- `WB_RAG_ELEMENT_K=4`: local memories retained per element.
- `WB_RAG_ELEMENT_TEST_K=3`: testing records retained per element.
- `WB_RAG_WEB_PER_ELEMENT=0` (default): keep web retrieval at control level.
- `WB_WEB_MAX_RESULTS=5`: per search result cap.

## Audit visibility

The runtime monitor records element-level counts under `elements`, including:

- local knowledge findings
- control-testing findings
- internet findings
- capability hints
- retrieval methods

Assessment and Challenge outputs expose an `element_knowledge` digest plus an `element_backbone` block.

## Validation

Targeted regression: 20 passed.

Full suite should be run in the target local environment because some repository tests depend on the configured Ollama daemon and optional web-search package.
