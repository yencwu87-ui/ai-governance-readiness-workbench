from governance.semantic_registry import control_semantics, coverage_summary


def test_replicated_framework_counts():
    s = coverage_summary()
    assert s['controls_total'] == 195
    assert s['elements_total'] == 562
    assert s['framework_elements']['MAS'] == 101
    assert s['framework_elements']['MGF Agentic'] == 126
    assert s['framework_elements']['SAFR'] == 84
    assert s['framework_elements']['NIST AI RMF'] == 212
    assert s['framework_elements']['ISO 42001'] == 39


def test_safr_controls_are_purposefully_decomposed():
    c = control_semantics('S1.1', 'SAFR')
    assert c is not None
    assert len(c['elements']) == 4
    assert all(e['verification'] == 'HUMAN_JUDGEMENT' for e in c['elements'])


def test_nist_elements_are_source_grounded():
    c = control_semantics('GOVERN 1.2', 'NIST AI RMF')
    assert c is not None
    assert len(c['elements']) >= 3
    assert all(e['source_grounding'] == 'INSTRUMENT_MATCH_CANDIDATE' for e in c['elements'])
    assert all(e['verification'] == 'HUMAN_JUDGEMENT' for e in c['elements'])
