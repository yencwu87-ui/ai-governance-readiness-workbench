"""Create an MAS requirement draft without modifying the live requirements/mas.yaml.

Example:
  python tools/draft_regulatory_change.py --source-title 'MAS AIRG update' \
    --source-reference 'internal://reg-change/2026-09' --out requirements/drafts/mas-2026-09-draft.yaml

The tool copies the current requirements as the base draft. Proposed control edits can then
be applied manually or by a controlled transformation step; the live requirements file is untouched.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import yaml
from governance.regulatory_change import load_requirements, build_draft, save_draft, impact_report

ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-title', required=True)
    ap.add_argument('--source-reference', required=True)
    ap.add_argument('--effective-from')
    ap.add_argument('--ticket')
    ap.add_argument('--out')
    ap.add_argument('--proposed-controls', help='YAML file containing a controls mapping; defaults to current controls')
    args = ap.parse_args()
    current = load_requirements()
    controls = (yaml.safe_load(Path(args.proposed_controls).read_text()) or {}).get('controls', current.get('controls', {})) if args.proposed_controls else current.get('controls', {})
    draft = build_draft(controls, source_title=args.source_title, source_reference=args.source_reference,
                        effective_from=args.effective_from, change_ticket=args.ticket)
    out = save_draft(draft, args.out)
    print(out)
    testing_path = ROOT / 'governance' / 'knowledge' / 'mas_executable_tests.yaml'
    testing = yaml.safe_load(testing_path.read_text()) if testing_path.exists() else {}
    print(yaml.safe_dump({'impact': impact_report(draft, testing)}, sort_keys=False))

if __name__ == '__main__':
    main()
