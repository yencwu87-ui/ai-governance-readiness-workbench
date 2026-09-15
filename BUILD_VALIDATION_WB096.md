# WB-096 build validation

## Completed checks

- Python compile check: passed (`python -m compileall -q inference tools governance plugins assessor.py challenge.py`)
- Focused regression suite: **70 passed**
- Additional tail suite (runs/drift, step8, v04/v05 governance): **41 passed**
- M3.6 corpus binding test: passed after recording the new requirement SHA
- Inference plan smoke test: routine/strong/critical routing returns a deterministic plan without an LLM call
- M3.6 element contract: **14 elements**, all present in both authoritative YAML and verification metadata

## Evaluation status

The M3.6 corpus is intentionally not scored against the new 14-element construct yet. Its element labels
are `?` pending human re-argument. This keeps the evaluator **NOT TESTABLE** rather than silently mapping old
7-element labels onto the new contract.

A full unsegmented `pytest -q` run was started but exceeded the execution window after substantial progress;
no full-suite pass is claimed. The targeted suites covering the modified assessor, challenger, element drafting,
plugin, corpus-binding and inference paths passed.
