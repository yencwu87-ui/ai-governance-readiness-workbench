from governance.outcomes import outcome_definitions, mappings_for, evaluate_outcome


def test_outcome_catalog_has_global_ids():
    ids = [x['outcome_id'] for x in outcome_definitions()]
    assert 'OVS-CHANGE-01' in ids
    assert 'OVS-OVERSIGHT-01' in ids


def test_crosswalk_uses_real_mas_and_mgf_namespaces():
    m = mappings_for('OVS-CHANGE-01')
    assert any(x['framework'] == 'MAS' and x['control_id'] == 'M3.12' for x in m)
    assert any(x['framework'] == 'MGF' and x['control_id'] == 'D2.2' for x in m)


def test_outcome_posture_is_deterministic():
    decisions = {
        'MAS::M3.12': {'sufficiency': 'full'},
        'MGF::D2.2': {'sufficiency': 'partial'},
    }
    def key_for(framework, control_id):
        return f'{framework}::{control_id}'
    out = evaluate_outcome('OVS-CHANGE-01', decisions_by_control_key=decisions, control_key_for=key_for)
    assert out['posture'] == 'remediate'
