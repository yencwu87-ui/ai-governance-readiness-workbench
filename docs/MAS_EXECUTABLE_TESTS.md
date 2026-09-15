# MAS executable control tests

All 30 MAS controls have executable evidence-floor tests in `caa/mas_tests.py`. The test engine consumes a normalized evidence JSON file and produces `PASS`, `FAIL`, or `NOT_TESTABLE`. It never invents evidence and never writes a human governance decision.

Run all 30 controls:

```bash
PYTHONPATH=. python -m caa.mas_tests --evidence evidence.json --type both
```

Run one control:

```bash
PYTHONPATH=. python -m caa.mas_tests --evidence evidence.json --control M3.12 --type operating
```

The machine test is an executable floor, not the complete regulatory judgement. The human gate remains authoritative.

## Regulatory change workflow

Never edit `requirements/mas.yaml` directly for a new regulatory requirement. Create a draft under `requirements/drafts/`, compare it to the live version, review the impacted controls and associated test IDs, run the draft in shadow mode, approve it under a change ticket, then promote it to `requirements/releases/`. The live pointer is changed only in the approved deployment change.
