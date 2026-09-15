# WB-098 — Challenge/RAG failure diagnosis

## Root cause observed
The D2.1 failure is **not evidence that local RAG failed**. The canonical MGF Agentic contract for D2.1 currently governs only `e1`:

`playbook_workbook` → `D2.1` → `e1`

The challenger model emitted `requirement_pointer.element_id = e3`. The deterministic validator correctly rejected that pointer because `e3` does not exist in the governed contract.

## Local retrieval check
A direct resolver check on D2.1 returned:
- 5 governance memories: `GOV-MEM-0005`, `GOV-MEM-0003`, `GOV-MEM-0004`, `GOV-MEM-0001`, `GOV-MEM-0002`
- 2 control-testing records, including D2.1
- `local_error = None`

Therefore local RAG is functioning.

## Separate internet issue
The web channel was attempted but returned:
`the ddgs package is not installed, so no web search was performed - pip install 'ddgs>=9.0'`

`requirements.txt` already declares `ddgs>=9.0`; the runtime environment simply needs its dependencies installed.

## WB-098 changes
1. Challenge and claim-vetting prompts now print the **canonical element catalog and IDs** and explicitly forbid IDs from evidence, memory, another control, or a prior run.
2. Validation remains fail-closed for invalid element IDs.
3. The UI-facing challenge call no longer turns a final model-validation error into an unrecorded exception. It returns a structured `validation_status=blocked` result containing the error plus retrieval provenance, so the audit trail shows exactly why no challenge was admitted.
4. Challenge outputs now expose `local_knowledge_used`, `control_testing_knowledge_used`, `external_knowledge_attempted`, and the actual external query.

This does **not** silently remap `e3` to `e1`. That would contaminate requirement provenance. Instead, the model is constrained to the authoritative element list and a failed response is retryable/escalatable.
