# stress/ — hotspot scanner for Play 10

    python -m stress.runner --target workbench            # run whatever the tracker says is due
    python -m stress.runner --target workbench --all      # run every implemented hotspot
    python -m stress.runner --target ollama:mistral --hotspots 2   # scan another model

| Hotspot | Runner | Engine | Needs |
|---|---|---|---|
| 1 Hallucination | h01_hallucination_garak | garak | `pip install garak`; Ollama or OpenAI-compatible target |
| 2 Prompt injection | h02_injection | native | nothing extra; works on workbench and raw targets |
| 3 Agent behaviour | h03_agent_promptfoo | promptfoo | Node + `npx promptfoo`; fill `corpora/h03_promptfoo.yaml` |
| 4–14 | not yet | — | add `hotspots/hNN_*.py` with `@hotspot(NN, name)` |

Outputs go to `stress/results/`. The runner **proposes** tracker rows (`tracker_proposal_*.csv`); a person applies
them to the Stress-Test Tracker. The engines' raw reports are kept beside the normalised result as evidence.

Targets: `workbench` (the assessor via pipeline.propose), `ollama:<model>`, `http(s)://…` (OpenAI-style chat,
`TARGET_API_KEY` for auth). Hotspots that need structured ratings use `target.assess`; others use `target.ask`.

Engine output formats change between versions — the two parsers say what they expect; check once against your install.
