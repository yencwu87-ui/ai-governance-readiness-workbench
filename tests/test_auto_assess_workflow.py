from pathlib import Path


APP = Path(__file__).parents[1] / "app.py"


def test_save_my_read_triggers_independent_assessment():
    text = APP.read_text()
    save_block = text[text.index('if st.button("Save my reading"'):text.index('if not has_ev:', text.index('if st.button("Save my reading"'))]
    assert 'propose(c, ev, pdf)' in save_block
    assert 'S["ai"][c.key] = propose(c, ev, pdf)' in save_block
    assert 'is_error(S["ai"].get(c.key))' in save_block
    assert 'never passed to propose()' in save_block


def test_manual_assess_button_removed_from_assess_tab():
    text = APP.read_text()
    assert 'g2.button("Assess with AI"' not in text
    assert 'Assess with AI", disabled=True' not in text


def test_ai_result_stays_blind_until_my_read_saved():
    text = APP.read_text()
    assert 'The proposal is withheld until your reading is recorded' in text or 'proposal is hidden until your reading is saved' in text or 'never shown' in text
    assert 'Your own reading is recorded before anything a model produces is shown' in text or 'Save your independent reading first' in text


def test_stage_includes_ai_assessment_state():
    text = APP.read_text()
    assert '("AI assessment",' in text
    assert '("Compare",' in text
