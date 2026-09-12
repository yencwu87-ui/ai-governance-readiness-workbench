# Demo Evidence Pack

The workbench does **not** require a folder scan for a single-control assessment. Evidence can be pasted or attached on the Assess tab.

For whole-library demonstrations, the app can generate a synthetic evidence pack outside the workbench installation with **195 control-specific Markdown files** covering MAS, ISO/IEC 42001, NIST AI RMF, MGF Agentic, and SAFR.

## Demo modes

- **Mixed: full/partial/none** — deterministic mixture for testing retrieval, assessor discrimination, gap analysis and challenge behaviour.
- **All complete** — complete synthetic evidence for every control, useful for testing the upper sufficiency boundary.

## Safety

Every generated document is explicitly marked `SYNTHETIC DEMO EVIDENCE — NOT REAL ORGANISATIONAL EVIDENCE`. The pack is not regulatory evidence, client evidence, or an assurance conclusion.

## Runtime behaviour

The app's **Load demo evidence** action creates the pack outside the repository and indexes it with the normal scanner. This keeps synthetic fixtures separate from the engine's own source, evaluation corpus, and governance records, and avoids the self-scan guard.
