#!/usr/bin/env python3
"""Regenerate governance/knowledge/control_testing.yaml from the playbook workbook.

Uses artifact_tool for workbook reads. Blank Test of Design/Test of Operating Effectiveness
cells produce explicit draft_derived testing guidance; no derived wording is labelled authoritative.
"""
from __future__ import annotations
from pathlib import Path
import re
import yaml
from artifact_tool import Blob, SpreadsheetFile

ROOT=Path(__file__).resolve().parent.parent
BOOK=ROOT/'data'/'AI_Governance_Playbook_MGF_SAFR_v0.5.1_contracts.xlsx'
OUT=ROOT/'governance'/'knowledge'/'control_testing.yaml'
SHEETS={
 'ISO42001':('Control Library - ISO 42001','A3:O80'),
 'NIST_AI_RMF':('Control Library - NIST AI RMF','A3:O80'),
 'MAS':('Control Library - MAS','A3:R80'),
 'MGF_Agentic':('Control Library - MGF Agentic','A3:U80'),
 'SAFR':('Control Library - SAFR','A3:V80'),
}

def text(x): return '' if x is None else str(x).strip()
def split_items(x): return [p.strip(' -') for p in re.split(r'[;\n•]+', text(x)) if p.strip(' -')]
def plays(x): return re.findall(r'\b(?:PLAY|Play)\s+\d+\b', text(x))

def norm(lib,r):
 if lib=='MAS': return text(r.get('MAS ref')), text(r.get('MAS expectation area')), text(r.get('MAS expectation area'))
 if lib=='MGF_Agentic':
  return text(r.get('MGF Control ID')).replace(' ★',''), text(r.get('Control / Recommended Measure')), text(r.get('Control / Recommended Measure'))
 if lib=='SAFR':
  return text(r.get('SAFR Control ID')).replace(' ★',''), text(r.get('Control / recommended measure')), text(r.get('Control / recommended measure'))
 if lib=='ISO42001':
  title=text(r.get('Control Title')); return text(r.get('Control ID')), title, text(r.get('Requirement (summary)')) or title
 cid=text(r.get('Subcategory')); return cid, text(r.get('Subcategory outcome')), text(r.get('Subcategory outcome'))

def main():
 wb=SpreadsheetFile.import_xlsx(Blob.load(str(BOOK)))
 play_rows=wb.worksheets.get_item('Playbooks & Runbooks').get_range('A3:F68').values
 playmap={}; cur=None
 for row in play_rows:
  first=text(row[0]) if row else ''
  if first.startswith('PLAY '):
   m=re.match(r'PLAY\s+(\d+)\s+—\s*(.*)',first)
   if m: cur=f'Play {m.group(1)}'; playmap[cur]={'title':m.group(2),'steps':[]}
  elif first.startswith('Step') and cur:
   playmap[cur]['steps'].append({'step':first.strip(),'owner':text(row[1]),'action':text(row[2]),'evidence':text(row[4])})
 controls=[]
 for lib,(sheet,rng) in SHEETS.items():
  rows=wb.worksheets.get_item(sheet).get_range(rng).values; hdr=rows[0]
  for row in rows[1:]:
   if not row or all(x is None or x=='' for x in row): continue
   r={hdr[i]:row[i] if i<len(row) else None for i in range(len(hdr))}
   cid,title,req=norm(lib,r)
   if not cid or not title: continue
   linked=split_items(r.get('Linked play')); step_rows=[]
   for p in plays(r.get('Linked play')):
    for st in playmap.get(p,{}).get('steps',[]): step_rows.append({'play':p,**st})
   evidence=split_items(r.get('Evidence / artifact')); owner=text(r.get('Owner (role)'))
   td=text(r.get('Test of Design')); toe=text(r.get('Test of Operating Effectiveness'))
   design=[f'Confirm the control has a named accountable owner: {owner}.' if owner else 'Confirm a named accountable owner is assigned.',
           'Confirm the requirement/objective is documented and scoped to the relevant system, process, or programme.']
   if evidence: design.append('Confirm the declared design artefacts exist and are approved/current where applicable: '+ '; '.join(evidence)+'.')
   if linked: design.append('Confirm the linked playbook/runbook defines a repeatable procedure and explicit exit gate for this control.')
   if td: design=[td]
   operating=[]
   for st in step_rows[:10]:
    line=f"Verify operation of {st['play']} {st['step']}: {st['action']}" + (f" Evidence expected: {st['evidence']}." if st['evidence'] else '')
    operating.append(line)
   if evidence: operating.append('Sample the declared evidence/artifacts and verify they demonstrate execution of the control, not only policy intent.')
   if req: operating.append(f'Verify observed operation addresses the control requirement: {req}.')
   operating += ['Check for exceptions, failures, overdue actions, or contradictory records and verify they were dispositioned under the applicable process.',
                 'Where cadence or event triggers apply, verify the sample falls within the required cadence/trigger window.']
   if toe: operating=[toe]
   status='exact' if td or toe else 'draft_derived'
   controls.append({'control_id':cid,'framework':lib,'title':title,'requirement_basis':req,'objective':text(r.get('Objective — what it bounds')),
                    'owner':owner,'evidence_artifacts':evidence,'linked_play':linked,
                    'crosswalks':{'MAS':text(r.get('MAS AIRG theme')),'ISO_42001':text(r.get('ISO 42001') or r.get('ISO/IEC 42001 Annex A')),
                                  'NIST_AI_RMF':text(r.get('NIST AI RMF')),'MGF_SAFR':text(r.get('Linked MAS | SAFR') or r.get('Linked MAS | MGF')),
                                  'CSA_PA':text(r.get('Linked CSA PA'))},
                    'testing':{'design':design,'operating':operating,'play_steps':step_rows,
                               'source_status':status,'source_notes':'Preserves workbook-provided test wording.' if status=='exact' else 'Drafted from workbook control row, declared evidence, requirement/objective and linked playbook steps; workbook test fields were blank.'},
                    'provenance':{'source_file':'data/AI_Governance_Playbook_MGF_SAFR_v0.5.1_contracts.xlsx','source_sheet':sheet,'source_control_id':cid,'source_status':status},
                    'authority_tier':'authoritative' if status=='exact' else 'example'})
 OUT.write_text(yaml.safe_dump({'schema_version':'0.4.control-testing.1','purpose':'Normalized Control Testing Knowledge Base derived from the governed AI Governance Playbook workbook. Blank workbook testing cells produce draft_derived guidance and are not authoritative until approved.','source_workbook':str(BOOK.relative_to(ROOT)),'control_count':len(controls),'controls':controls},sort_keys=False,allow_unicode=True,width=120),encoding='utf-8')
 print(f'Wrote {len(controls)} controls to {OUT}')
if __name__=='__main__': main()
