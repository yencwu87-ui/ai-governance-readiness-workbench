#!/usr/bin/env python3
"""Record explicit human disposition for a canonical element."""
from __future__ import annotations
import argparse
from pathlib import Path
import yaml

ALLOWED={'pending_human','include','exclude','merge','split','candidate_pending_source','parallel_context'}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--decisions',required=True)
    ap.add_argument('--element',required=True)
    ap.add_argument('--status',required=True,choices=sorted(ALLOWED))
    ap.add_argument('--reviewer',required=True)
    ap.add_argument('--rationale',required=True)
    ap.add_argument('--decided-at',required=True)
    a=ap.parse_args()
    p=Path(a.decisions)
    d=yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    d.setdefault('elements',{})[a.element]={'status':a.status,'rationale':a.rationale,'reviewer':a.reviewer,'decided_at':a.decided_at}
    p.write_text(yaml.safe_dump(d,sort_keys=False,allow_unicode=False),encoding='utf-8')
    print(f'{a.element}: {a.status}')
if __name__=='__main__': raise SystemExit(main())
