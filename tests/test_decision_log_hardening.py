import json
from pathlib import Path
import pytest

from decisions import record, load, load_errors, calibration
from reasons import reason_error


def test_canonical_hashes_full_and_unicode(tmp_path):
    p = tmp_path / 'd.jsonl'
    proposal = {'z': 'é', 'a': 1}
    rec = record('UC1', 'S1', 'accept', 'R', 'Evidence shows the required element is met.',
                 proposal, {'sufficiency': 'full'}, p)
    assert len(rec['proposal_hash']) == 64
    assert rec['proposal_hash16'] == rec['proposal_hash'][:16]
    assert len(rec['final_hash']) == 64
    assert rec['blind_hash'] is None


def test_record_validates_ids_and_final(tmp_path):
    p = tmp_path / 'd.jsonl'
    with pytest.raises(ValueError): record('', 'S1', 'accept', 'R', 'Evidence shows the required element is met.', {}, {}, p)
    with pytest.raises(ValueError): record('UC1', ' ', 'accept', 'R', 'Evidence shows the required element is met.', {}, {}, p)
    with pytest.raises(ValueError): record('UC1', 'S1', 'accept', 'R', 'Evidence shows the required element is met.', {}, None, p)


def test_load_tolerates_corrupt_line(tmp_path):
    p = tmp_path / 'd.jsonl'
    p.write_text('{"use_case":"UC1"}\nnot-json\n{"use_case":"UC2"}\n', encoding='utf-8')
    assert [r['use_case'] for r in load(p)] == ['UC1', 'UC2']
    assert load_errors(p)[0]['line'] == 2


def test_calibration_equal_delta_is_same_not_under(tmp_path):
    p = tmp_path / 'd.jsonl'
    proposal = {'sufficiency': 'partial'}
    final = {'sufficiency': 'partial'}
    record('UC1', 'P1.S1', 'amend', 'R', 'Evidence shows the required element remains partial.', proposal, final, p)
    out = calibration(p)['per_play']['P1']
    assert out['same'] == 1
    assert out['over'] == 0
    assert out['under'] == 0


def test_reason_normalization_and_deferral_safeguard():
    assert reason_error('ok!') is not None
    assert reason_error('n/a,') is not None
    assert reason_error('REJECT;') is not None
    assert reason_error('Good point') is not None
    assert reason_error('Challenger is right because evidence lacks Q2 logs') is None
    assert reason_error('evidence missing Q2 logs', revised=True, previous='Evidence missing Q2 logs.') is not None
    assert reason_error('<CONTROL_NAME>') is not None
