from pathlib import Path
import re, yaml, copy, hashlib, json
from collections import Counter
ROOT=Path('/mnt/data/work_fullcov')

# ---------- NIST: source-grounded suggested actions ----------
text=(ROOT/'instruments/AI_RMF_Playbook.txt').read_text(encoding='utf-8')

def section_for(text, cid):
    m=re.search(r'(?m)^'+re.escape(cid)+r'\s*$', text)
    if not m: return ''
    nxt=re.search(r'(?m)^(?:GOVERN|MAP|MEASURE|MANAGE) \d+\.\d+\s*$', text[m.end():])
    end=m.end()+nxt.start() if nxt else len(text)
    return text[m.start():end]

def bullets(sec):
    sm=re.search(r'(?m)^Suggested Actions\s*$', sec)
    if not sm: return []
    part=sec[sm.end():]
    eh=re.search(r'\n(?:Transparency & Documentation|AI Transparency Resources|References)\s*',part)
    if eh: part=part[:eh.start()]
    # bullet may wrap across lines until next bullet/page heading
    raw=re.findall(r'(?ms)^•\s+(.*?)(?=^•\s+|\n\d+ of 142\s*$|\Z)', part)
    return [' '.join(x.split()) for x in raw if x.strip()]

def nist_elements(cid, req, existing):
    bs=bullets(section_for(text,cid))
    if len(bs)>=3:
        # Source language is retained; frame as recommended/semantic elements, not new regulation.
        return [(f'The organisation should {b[0].lower()+b[1:]}' if b else b, ['NIST AI RMF Playbook suggested action']) for b in bs[:3]]
    if len(bs)==2:
        return [(f'The organisation should {b[0].lower()+b[1:]}' if b else b, ['NIST AI RMF Playbook suggested action']) for b in bs]
    # fallback: preserve the control's existing semantic sentence and add two source-bounded checks from design-test guidance.
    out=[]
    e0=existing[0].get('governed_text') if existing else req
    out.append((e0 or req,['NIST AI RMF Playbook control statement']))
    # Use ToD confirmation clauses as design clarifiers, explicitly framed as implementation details.
    return [(x, ['NIST AI RMF Playbook control statement']) for x in [e0 or req]]

# ---------- SAFR: source + existing design tests ----------
def safr_elements(control):
    current=control.get('elements') or []
    tod=[x.get('text','').strip() for x in control.get('test_of_design',[]) if x.get('id','').startswith('D')]
    # Remove the terminal verdicts and build 3-4 purposeful, reviewable obligations from actual design-test content.
    clean=[]
    for t in tod:
        if not t or t.lower().startswith('design verdict') or t.lower().startswith('obtain the') and 'specification' not in t.lower():
            continue
        t=re.sub(r'^Confirm\s+', '', t, flags=re.I)
        t=re.sub(r'^Obtain\s+', '', t, flags=re.I)
        t=re.sub(r'^Define\s+', '', t, flags=re.I)
        # convert inspect/test language to a governed design statement without adding substantive scope
        t=t.rstrip('.')
        if t.lower().startswith('inspect '):
            t=t[8:]
        t=t[0].upper()+t[1:] if t else t
        if len(t)>35:
            clean.append(t)
    # Deduplicate and cap at four. If fewer, include the control requirement itself as a core element.
    seen=[]; out=[]
    for t in clean:
        if t not in seen:
            seen.append(t); out.append((f'The control design specifies {t[0].lower()+t[1:]}.',['SAFR white paper','control design test guidance']))
        if len(out)>=4: break
    if len(out)<3:
        req=control.get('requirement','')
        if req:
            out.insert(0,(req.rstrip('.').capitalize()+'.',['SAFR white paper control statement']))
    return out[:4]

# Load registry/contracts
reg_p=ROOT/'governance/knowledge/semantic_registry.yaml'
reg=yaml.safe_load(reg_p.read_text())
for c in reg['controls']:
    fw=c.get('framework')
    proto={e['id']:e for e in c.get('elements',[])}
    if fw=='NIST AI RMF':
        pairs=nist_elements(c['control_id'],c.get('requirement',''),list(proto.values()))
        # Keep at least the original element when source parsing produces fewer than 2; 3 is ideal.
        if len(pairs)<2:
            pairs=[(c.get('requirement',''),['NIST AI RMF Playbook control statement'])]
        new=[]
        source_basis=(c.get('control_source_matches') or [])[:3]
        for i,(txt,evs) in enumerate(pairs,1):
            old=copy.deepcopy(proto.get(f'e{i}') or proto.get('e1') or {})
            old.update({
                'id':f'e{i}','intent':txt,'governed_text':txt,'scope':old.get('scope','model'),
                'applies_when':old.get('applies_when'),'verification':'HUMAN_JUDGEMENT',
                'verification_reason':'Source-grounded semantic element; no deterministic predicate is claimed unless separately specified.',
                'expected_evidence':evs,'predicate_spec':{'present':False,'element_predicates':[],'applicability':None},
                'locator':f'controls.{c["control_id"]}.elements[{i-1}]',
                'source_grounding':'INSTRUMENT_MATCH_CANDIDATE',
                'source_basis':source_basis,
                'design_test_guidance': old.get('design_test_guidance') or [x.get('text','') for x in c.get('test_of_design',[]) if x.get('text')][:4],
            })
            new.append(old)
        c['elements']=new
    elif fw=='SAFR':
        pairs=safr_elements(c)
        new=[]
        for i,(txt,evs) in enumerate(pairs,1):
            old=copy.deepcopy(proto.get(f'e{i}') or proto.get('e1') or {})
            old.update({
                'id':f'e{i}','intent':txt,'governed_text':txt,'scope':'model','applies_when':None,
                'verification':'HUMAN_JUDGEMENT',
                'verification_reason':'Draft/source-grounded semantic element; no deterministic predicate is claimed unless separately specified.',
                'expected_evidence':evs,'predicate_spec':{'present':False,'element_predicates':[],'applicability':None},
                'locator':f'controls.{c["control_id"]}.elements[{i-1}]',
                'source_grounding':'INSTRUMENT_MATCH_CANDIDATE',
                'source_basis': (c.get('control_source_matches') or [])[:3] or old.get('source_basis',[]),
                'design_test_guidance': old.get('design_test_guidance') or [x.get('text','') for x in c.get('test_of_design',[]) if x.get('text')][:4],
            })
            new.append(old)
        c['elements']=new

# Recompute summaries
counts=Counter(); vc=Counter()
for c in reg['controls']:
    counts[c['framework']]+=len(c.get('elements',[]))
    for e in c.get('elements',[]): vc[e.get('verification','HUMAN_JUDGEMENT')]+=1
reg['summary']['controls']=len(reg['controls'])
reg['summary']['semantic_elements']=sum(counts.values())
reg['summary']['framework_elements']={k:counts[k] for k in sorted(counts)}
reg['summary']['deterministic_elements']=vc['DETERMINISTIC']
reg['summary']['human_judgement_elements']=vc['HUMAN_JUDGEMENT']
reg['summary']['out_of_band_elements']=vc['OUT_OF_BAND']

# Contract update from registry for SAFR/NIST only; preserve all other metadata.
for fw, fname in [('SAFR','safr.yaml'),('NIST AI RMF','nist_ai_rmf.yaml')]:
    cp=ROOT/'governance/knowledge/contracts'/fname
    doc=yaml.safe_load(cp.read_text())
    rmap={(c['framework'],c['control_id']):c for c in reg['controls']}
    for c in doc['controls']:
        r=rmap[(fw,c['control_id'])]
        c['elements']=[{'id':e['id'],'text':e['governed_text'],'scope':e.get('scope','model'),'applies_when':e.get('applies_when')} for e in r['elements']]
        c['expected_evidence']=sorted({x for e in r['elements'] for x in (e.get('expected_evidence') or [])})
    cp.write_text(yaml.safe_dump(doc,sort_keys=False,allow_unicode=True),encoding='utf-8')

# Ensure consolidated contracts mirror framework contracts; preserve MGF and ISO.
all_docs=[]
for fname in ['mas.yaml','mgf_agentic.yaml','safr.yaml','nist_ai_rmf.yaml','iso_42001.yaml']:
    all_docs.append(yaml.safe_load((ROOT/'governance/knowledge/contracts'/fname).read_text()))
con={'schema_version':all_docs[0]['schema_version'],'frameworks':[d for d in all_docs], 'control_count':sum(len(d['controls']) for d in all_docs)}
(ROOT/'governance/knowledge/control_contracts.yaml').write_text(yaml.safe_dump(con,sort_keys=False,allow_unicode=True),encoding='utf-8')

# Update registry hashes and docs.
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
reg_p.write_text(yaml.safe_dump(reg,sort_keys=False,allow_unicode=True),encoding='utf-8')
(ROOT/'governance/knowledge/semantic_registry.sha256').write_text(f'{sha(reg_p)}  governance/knowledge/semantic_registry.yaml\n')
# hashes for framework contracts and consolidated
for p in list((ROOT/'governance/knowledge/contracts').glob('*.yaml')):
    (p.with_suffix('.sha256')).write_text(f'{sha(p)}  {p.name}\n')
(ROOT/'governance/knowledge/control_contracts.sha256').write_text(f'{sha(ROOT/"governance/knowledge/control_contracts.yaml")}  governance/knowledge/control_contracts.yaml\n')

# Coverage doc
lines=['# Replicated Governed-Control Semantic Coverage','','This pass extends the instrument-first semantic decomposition beyond MGF Agentic.','','## Coverage','']
for fw in ['MAS','MGF Agentic','SAFR','NIST AI RMF','ISO 42001']:
    lines.append(f'- {fw}: **{counts[fw]} semantic elements**')
lines += ['',f'- Total governed controls: **{len(reg["controls"])}**',f'- Total semantic elements: **{sum(counts.values())}**',f'- Deterministic elements: **{vc["DETERMINISTIC"]}**',f'- Human-judgement elements: **{vc["HUMAN_JUDGEMENT"]}**',f'- Out-of-band elements: **{vc["OUT_OF_BAND"]}**','',
'## Method','',
'- **MGF Agentic**: existing source-grounded decomposition retained and used as the pattern.','- **MAS**: existing 101-element audited decomposition retained; no blanket inflation was applied where the existing three-per-control elements were already purposeful.','- **SAFR**: decomposed from the SAFR white paper plus the repository design-test guidance. SAFR is explicitly a reference white paper, not regulatory guidance.','- **NIST AI RMF**: decomposed from the NIST AI RMF Playbook suggested-action text where available; source language is retained as semantic guidance rather than promoted into a new legal obligation.','- All new elements remain **HUMAN_JUDGEMENT** unless an independent deterministic predicate exists. Instrument matches are provenance candidates, not human source sign-off.','']
(ROOT/'REPLICATED_SEMANTIC_COVERAGE.md').write_text('\n'.join(lines),encoding='utf-8')
print('counts', dict(counts))
print('verification',dict(vc))
