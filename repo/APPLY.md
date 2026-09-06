# Step 8 — lifecycle cards, step judge, validator, hybrid retrieval

Unzip at the git root (the folder containing repo/):

    cd ~/Downloads/Projects/ai-governance-readiness-workbench
    cp -R ~/Downloads/step8/. .
    cd repo
    ollama pull nomic-embed-text        # embeddings; judge uses your existing llama3.1:8b
    python -m pytest tests/test_step8.py
    streamlit run app.py

New files (all under repo/): usecases.py, decisions.py, retriever.py, judge.py, validator.py,
lifecycle_cards.py, governance/usecases.csv, tests/test_step8.py, README_step8_section.md.

## Wire the tab (app.py)

Replace the body of the existing Lifecycle tab with:

    import lifecycle_cards
    lifecycle_cards.render(plays, index, latest_lane_b())

where `plays` is the list from plays.load_plays(...) and `index` is the scanner.Index that
pipeline.index_folder() returned for the scanned folder (the cards rebuild documents from its
chunks). The cards are aligned with plays.py as uploaded: Play.id/.title/.header/.controls/
.steps and Step.id/.owner/.action/.evidence; trigger, owner and exit gate are parsed out of
Play.header. Lane B tests are matched to steps through play_refs, as lifecycle_view does.

## README and housekeeping

- Append README_step8_section.md to governance/README.md (or the root README), then delete it.
- Add `repo/.cache/` and `repo/governance/step_decisions.jsonl` to .gitignore, or commit the
  decision log deliberately as evidence — your call, but decide once.
- Update the sheet title in cell A1 of Playbooks & Runbooks to "11 Lifecycle Plays".
- Optional: run the stress kit against judge.judge_step (guardrail 9).

Commit as WB-008: lifecycle cards per use case; step judge + validator; hybrid retrieval.
