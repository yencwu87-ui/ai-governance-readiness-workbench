#!/usr/bin/env python3
from __future__ import annotations
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inference.policy import TaskSignals, build_plan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--role', default='assess')
    ap.add_argument('--control', default='')
    ap.add_argument('--evidence-chars', type=int, default=6000)
    ap.add_argument('--elements', type=int, default=0)
    ap.add_argument('--disagreement', action='store_true')
    ap.add_argument('--high-risk', action='store_true')
    ap.add_argument('--prior-failures', type=int, default=0)
    a = ap.parse_args()
    plan = build_plan(TaskSignals(role=a.role, control_id=a.control, evidence_chars=a.evidence_chars,
                                  element_count=a.elements, reviewer_disagreement=a.disagreement,
                                  high_risk=a.high_risk, prior_failures=a.prior_failures))
    print(f'tier={plan.tier}')
    print(f'model={plan.model}')
    print(f'num_ctx={plan.num_ctx}')
    print(f'num_predict={plan.num_predict}')
    print(f'max_attempts={plan.max_attempts}')
    print('reasons=' + ','.join(plan.reasons))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
