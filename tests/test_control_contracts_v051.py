from governance.control_contract import validate_per_framework, get_control_contract

def test_all_framework_contract_files_validate():
    assert validate_per_framework() == []

def test_mas_requirement_authority_is_mas_yaml():
    c = get_control_contract('M3.12','MAS')
    assert c
    assert c['requirement_source'] == 'requirements/mas.yaml'
    assert c['requirement_authority'] == 'authoritative_internal_interpretation'
    assert c['elements'] and c['test_of_design'] and c['test_of_operating_effectiveness']

def test_safr_contract_has_challenge_inputs():
    c = get_control_contract('S1.1','SAFR')
    assert c
    assert c['near_miss_failure_modes']
    assert c['resolutions']
    assert c['test_of_design'] and c['test_of_operating_effectiveness']
