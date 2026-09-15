"""Canonical control-contract loader for Assess with AI, Challenge My Read and testing.

Workbook authoring is normalized into per-framework YAML contracts. For MAS, the requirement
semantics are overlaid from requirements/mas.yaml and remain authoritative. Testing/challenge
metadata from the workbook is governed draft content until formally approved.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_DIR = ROOT / "governance" / "knowledge" / "contracts"
DEFAULT_PATH = ROOT / "governance" / "knowledge" / "control_contracts.yaml"
ALIASES = {
    'MAS': 'mas.yaml', 'ISO42001': 'iso_42001.yaml', 'ISO 42001': 'iso_42001.yaml',
    'NIST AI RMF': 'nist_ai_rmf.yaml', 'NIST_AI_RMF': 'nist_ai_rmf.yaml',
    'MGF Agentic': 'mgf_agentic.yaml', 'MGF_Agentic': 'mgf_agentic.yaml', 'SAFR': 'safr.yaml'
}

def _path_for(framework: str) -> Path:
    return CONTRACT_DIR / ALIASES.get(framework, '')

@lru_cache(maxsize=10)
def load_contracts(path: str | Path = DEFAULT_PATH) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    if not isinstance(data.get('controls'), list):
        raise ValueError('control contracts must contain a controls list')
    return data

def get_control_contract(control_id: str, framework: str = '') -> dict | None:
    p = _path_for(framework) if framework in ALIASES else DEFAULT_PATH
    for c in load_contracts(p)['controls']:
        cid = str(c.get('control_id') or '').replace('★','').strip()
        if cid == str(control_id).replace('★','').strip():
            return c
    return None

def requirement_context(control_id: str, framework: str = '') -> dict:
    c = get_control_contract(control_id, framework)
    if not c:
        return {'source': None, 'control_id': control_id, 'requirement': '', 'elements': [], 'boundary': {}, 'authority': 'unknown'}
    return {'source': c.get('requirement_source'), 'control_id': control_id, 'requirement': c.get('requirement',''),
            'elements': c.get('elements') or [], 'boundary': c.get('boundary') or {}, 'authority': c.get('requirement_authority')}

def testing_context(control_id: str, framework: str = '') -> dict:
    return get_control_contract(control_id, framework) or {}

def validate_contracts(path: str | Path = DEFAULT_PATH) -> list[str]:
    errors=[]; seen=set(); data=load_contracts(path)
    for c in data['controls']:
        fw=str(c.get('framework','')); cid=str(c.get('control_id','')).replace('★','').strip(); key=(fw,cid)
        if key in seen: errors.append(f'duplicate control contract: {fw}/{cid}')
        seen.add(key)
        for f in ('title','requirement','elements','boundary','test_of_design','test_of_operating_effectiveness','near_miss_failure_modes','resolutions'):
            if not c.get(f): errors.append(f'missing {f}: {fw}/{cid}')
        if fw == 'MAS' and c.get('requirement_source') != 'requirements/mas.yaml':
            errors.append(f'MAS requirement authority mismatch: {fw}/{cid}')
    return errors

def validate_per_framework() -> list[str]:
    errors=[]
    for fw,fn in ALIASES.items():
        if fw not in {'MAS','ISO42001','NIST_AI_RMF','MGF_Agentic'} and fn:  # aliases duplicate names
            continue
    for fn in sorted(set(ALIASES.values())):
        p=CONTRACT_DIR/fn
        if not p.exists(): errors.append(f'missing framework contract: {p}')
        else: errors.extend(validate_contracts(p))
    return errors
