from pathlib import Path
import hashlib, json, yaml

ROOT=Path(__file__).resolve().parents[1]

def test_v05_has_30_mas_requirements_and_test_controls():
    d=yaml.safe_load((ROOT/'requirements/mas.yaml').read_text())
    assert len(d['controls'])==30
    assert len(d['test_controls'])==30
    for cid,e in d['controls'].items():
        assert e.get('requirement')
        assert len(e.get('elements') or []) >= 3
        assert set((e.get('boundary') or {})) >= {'none','partial','full'}

def test_active_eval_hash_matches_golden_set():
    p=ROOT/'eval/golden_set.jsonl'
    m=json.loads((ROOT/'eval/active_set.json').read_text())
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    assert m['sha256']==sha
    assert m['sha256_12']==sha[:12]
    assert m['case_count']==30
    assert m['real_full_cases']>=3

def test_active_eval_is_not_claimed_scored_without_matching_result():
    p=ROOT/'eval/golden_set.jsonl'
    sha=hashlib.sha256(p.read_bytes()).hexdigest()[:12]
    results=json.loads((ROOT/'governance/eval_results.json').read_text())
    matching=[r for r in results if r.get('eval_set_sha256_12')==sha]
    assert matching == []
