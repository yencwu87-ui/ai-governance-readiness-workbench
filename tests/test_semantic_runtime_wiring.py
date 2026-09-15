from pathlib import Path
import sys
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from assessor import _validate
from governance.control_contract import get_control_contract, validate_contracts, validate_per_framework
from governance.semantic_registry import load_semantic_registry, control_semantics
from governance.source_review import best_excerpts


def test_all_runtime_contracts_match_semantic_registry():
    assert validate_contracts() == []
    assert validate_per_framework() == []
    sem=load_semantic_registry()
    expected={(c['framework'],c['control_id']): [e['id'] for e in c.get('elements',[])] for c in sem['controls']}
    assert len(expected) == 195
    contract_dir=ROOT/'governance/knowledge/contracts'
    got={}
    for p in contract_dir.glob('*.yaml'):
        data=yaml.safe_load(p.read_text()) or {}
        for c in data.get('controls') or []:
            got[(c['framework'],c['control_id'])]=[e['id'] for e in c.get('elements',[])]
    assert got.keys() == expected.keys()
    assert got == expected


def test_d13_cannot_promote_test_steps_into_visible_gaps():
    c=get_control_contract('D1.3','MGF Agentic')
    out={
        'excerpt':'',
        'gaps':[
            "e1: The organization must ensure that cap the agent's blast radius before build.",
            'e2: The enforced configuration as at a date and compare it, field by field, to the approved boundary.',
            'e3: Define the population of granted access or mandate holders, and reconcile it to the approved grants.',
            'e4: Sample boundary events in the period: blocks, referrals and overrides.',
            'e5: Where no boundary event occurred, test the enforcement.',
            'e6: Inspect the most recent recertification for completeness.'
        ],
        'rationale':'synthetic', 'sufficiency':'none', 'proposedMaturity':1,
        'remediation':[], 'elementVerdicts':[
            {'element_id':e['id'],'status':'not_evidenced','excerpt':''} for e in c['elements']
        ]
    }
    res=_validate(out,'synthetic evidence',[],elements=[{'id':e['id'],'text':e['text']} for e in c['elements']],contract=c)
    assert all(g.startswith(('e1:','e2:','e3:','e4:')) for g in res['gaps'])
    assert all('Evidence does not demonstrate' in g for g in res['gaps'])
    assert any('Inspect the most recent recertification' in g for g in res.get('supplemental_assessor_notes',[]))


def test_uploaded_mas_source_is_review_context_only():
    class C:
        id='M1.1'; title='Board & senior management accountability for AI risk'; req='Board governance approval and accountability for AI risk'
    hits=best_excerpts('2.5 The Board is responsible for approving the overall governance approach for AI risk management.\n\nUnrelated paragraph.', C(), limit=2)
    assert hits
    assert 'Board' in hits[0]['excerpt']
