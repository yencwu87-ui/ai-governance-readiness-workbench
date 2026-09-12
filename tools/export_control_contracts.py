#!/usr/bin/env python3
"""Export the challenge-ready playbook workbook into canonical per-framework YAML contracts.

The workbook is the human authoring surface. This command produces the normalized runtime
contracts consumed by Assess with AI, Challenge My Read, and executable testing.
For MAS, requirement semantics are overlaid from requirements/mas.yaml and remain authoritative.
"""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path
import yaml
from artifact_tool import Blob, SpreadsheetFile
ROOT=Path(__file__).resolve().parent.parent
BOOK=ROOT/'data'/'AI_Governance_Playbook_MGF_SAFR_v0.5.1_contracts.xlsx'
OUTDIR=ROOT/'governance'/'knowledge'/'contracts'
MAS=ROOT/'requirements'/'mas.yaml'
SHEETS={'MAS':('Control Library - MAS',2,3,7,10,14,16,17,21,22,23,24,25,26),
'ISO 42001':('Control Library - ISO 42001',2,3,5,8,12,13,14,17,18,19,20,21,22),
'NIST AI RMF':('Control Library - NIST AI RMF',4,5,6,9,13,14,15,18,19,20,21,22,23),
'MGF Agentic':('Control Library - MGF Agentic',2,3,8,11,17,19,20,24,25,26,27,28,29),
'SAFR':('Control Library - SAFR',2,3,8,11,17,20,21,25,26,27,28,29,30)}

def cell(row,i): return '' if i is None or row[i-1] is None else str(row[i-1]).strip()
def lines(x): return [p.strip() for p in re.split(r'\n+',x or '') if p.strip()]
def steps(x):
 out=[]
 for i,line in enumerate(lines(x),1):
  m=re.match(r'([DO]\d+)[.:]?\s*(.*)',line); out.append({'id':m.group(1) if m else f's{i}','text':m.group(2).strip() if m else line})
 return out
def elems(x):
 out=[]
 for i,line in enumerate(lines(x),1):
  m=re.match(r'(e\d+)\.\s*(.*?)(?:\s+\[([^\]]+)\])?$',line,re.I)
  out.append({'id':m.group(1) if m else f'e{i}','text':(m.group(2) if m else line).strip(),'scope':(m.group(3) if m and m.group(3) else 'model')})
 return out
def boundary(x):
 d={}
 for line in lines(x):
  m=re.match(r'(none|partial|full)\s*[-:]\s*(.*)',line,re.I)
  if m:d[m.group(1).lower()]=m.group(2).strip()
 return d
def resolutions(x):
 out=[]
 for line in lines(x):
  m=re.match(r'([^\s]+)\s*→\s*(.*)',line); out.append({'failure_mode':m.group(1) if m else None,'text':m.group(2).strip() if m else line})
 return out

def main():
 wb=SpreadsheetFile.import_xlsx(Blob.load(str(BOOK))); mas=yaml.safe_load(MAS.read_text())
 allc=[]
 for fw,(sheet,idc,titlec,ownc,evc,playc,tdc,toec,elemc,popc,failc,resc,bc,provc) in SHEETS.items():
  vals=wb.worksheets.get_item(sheet).get_range('A4:AD100').values
  for row in vals:
   cid=cell(row,idc); title=cell(row,titlec)
   if not cid or not title: continue
   if fw=='MAS' and cid in mas.get('controls',{}):
    me=mas['controls'][cid]; req=me['requirement']; elements=[{'id':str(e.get('id')),'text':' '.join(str(e['text']).split()),'scope':str(e.get('scope','model')),'applies_when':e.get('applies_when'),'locator':f'controls.{cid}.elements[{i}]'} for i,e in enumerate(me.get('elements',[]))]
    b=me.get('boundary') or {}; src='requirements/mas.yaml'; auth='authoritative_internal_interpretation'
   else:
    req=cell(row,4) or title; elements=elems(cell(row,elemc)); b=boundary(cell(row,bc)); src='playbook_workbook'; auth='draft'
   allc.append({'framework':fw,'control_id':cid.replace('★','').strip(),'title':title,'requirement':req,'requirement_source':src,'requirement_authority':auth,'elements':elements,'boundary':b,'owner':cell(row,ownc),'expected_evidence':lines(cell(row,evc)),'linked_play':lines(cell(row,playc)),'test_of_design':steps(cell(row,tdc)),'test_of_operating_effectiveness':steps(cell(row,toec)),'near_miss_failure_modes':lines(cell(row,failc)),'resolutions':resolutions(cell(row,resc)),'population_and_evidence_floor':cell(row,popc),'test_provenance':cell(row,provc)})
 OUTDIR.mkdir(parents=True,exist_ok=True)
 data={'schema_version':'0.5.1.control-contract.3','source_workbook':BOOK.name,'control_count':len(allc),'controls':allc}
 (ROOT/'governance/knowledge/control_contracts.yaml').write_text(yaml.safe_dump(data,sort_keys=False,allow_unicode=True,width=140))
 for fw,fn in [('MAS','mas.yaml'),('ISO 42001','iso_42001.yaml'),('NIST AI RMF','nist_ai_rmf.yaml'),('MGF Agentic','mgf_agentic.yaml'),('SAFR','safr.yaml')]:
  subset=[c for c in allc if c['framework']==fw]
  out={'schema_version':'0.5.1.control-contract.3','framework':fw,'source_workbook':BOOK.name,'control_count':len(subset),'controls':subset}
  (OUTDIR/fn).write_text(yaml.safe_dump(out,sort_keys=False,allow_unicode=True,width=140))
 sha=hashlib.sha256((ROOT/'governance/knowledge/control_contracts.yaml').read_bytes()).hexdigest()
 (ROOT/'governance/knowledge/control_contracts.sha256').write_text(sha+'  control_contracts.yaml\n')
 print(f'exported {len(allc)} controls')
if __name__=='__main__': main()
