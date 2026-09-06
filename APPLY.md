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

## Revision 2 (after first run)
- retriever: chunks cut at paragraph/sentence/word boundaries, never mid-word; at most 2 hits
  per document and near-duplicate chunks (overlap neighbours) suppressed; short `file#n` labels.
- cards: caption says "no documents indexed" until a Scan has run; render() accepts a
  `reviewer` argument so the sidebar name can be reused —
      lifecycle_cards.render(plays, st.session_state.get("index"), latest_lane_b(), reviewer)
  where `reviewer` is whatever app.py already calls the sidebar reviewer name.
- Delete repo/.cache/embeddings.jsonl once: chunk boundaries changed, so old vectors are stale.

## Revision 3 (items 4 and 5)
- judge.py: prompt tells the model an artefact may serve the expected output under another
  name (suitability assessment = intake form); `is_data_step()` and `lane_b_proposal()`.
- validator.py: `source == "lane_b"` proposals skip V1/V3/V4/V6, keep V2/V5.
- lifecycle_cards.py: steps with Lane B tests (or data-type outputs) are evidenced by the
  operating test; retrieval off by default with a per-step toggle.
- decisions.calibration(): excludes Lane-B-fed proposals.
- stress/judge_target.py + stress/judge_cases.jsonl: run `python -m stress.judge_target`
  from repo/ (Ollama up). Wire into the hotspot runner via `JudgeTarget.run_case`.
- tests: 12.
Commit as WB-009: Lane-B-fed lifecycle steps; judge stress target.
