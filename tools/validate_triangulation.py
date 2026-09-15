#!/usr/bin/env python3
"""WB-100 transparency/audit gate for requirement triangulation."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from governance.triangulation import SourceRegistry, control_sufficiency, digest

def load(p):
    return yaml.safe_load(Path(p).read_text(encoding='utf-8')) or {}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--control', required=True)
    ap.add_argument('--elements', required=True, help='legacy/canonical element source')
    ap.add_argument('--overlay', required=False, help='WB-100 governed assurance overlay; preferred when present')
    ap.add_argument('--findings', required=True)
    ap.add_argument('--sources', required=True)
    ap.add_argument('--web-log', required=True)
    ap.add_argument('--decisions', required=True)
    ap.add_argument('--as-of', required=True)
    ap.add_argument('--out', required=True)
    a=ap.parse_args()
    el=load(a.overlay or a.elements); fi=load(a.findings); wr=load(a.web_log); hd=load(a.decisions); reg=SourceRegistry.from_yaml(a.sources)
    elems=el.get('elements') or el.get('controls',{}).get(a.control,{}).get('elements') or []
    report=control_sufficiency(elems, fi.get('findings',[]), reg, as_of=a.as_of, control_id=a.control, web_research=wr, human_decisions=hd)
    report['transparency']={
      'web_research': wr.get('online_check',{}),
      'human_decisions': hd.get('elements',{}),
      'source_registry_digest': digest(reg.snapshot()),
      'decision_rule': hd.get('decision_policy',{}),
    }
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(report['control'],indent=2))
    return 0 if report['control']['status']=='reviewable' else 2
if __name__=='__main__': raise SystemExit(main())
