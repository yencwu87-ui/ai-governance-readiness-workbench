"""Quick smoke test of the assessor against the local model. Run: python test_assessor.py"""
import json
from pathlib import Path

from assessor import assess, model_name
from playbook import load_controls

xlsx = next(Path("data").glob("*.xlsx"), None)
assert xlsx, "Put the playbook workbook in data/ first"
controls = load_controls(xlsx)
ctl = next(c for c in controls["SAFR"] if c.id.startswith("S1.1"))

POLICY = ("Our AI Acceptable Use Policy v2.1 (approved by the AI Risk Committee, March 2026) states that all AI agents "
          "must be registered in the enterprise AI inventory before deployment to production.")
RECORD = ('Extract from AI Inventory (SNOW CMDB, 28 Aug 2026): AGT-0142 "Trade-recon assistant", owner J. Tan, '
          "registered 12 Jun 2026, status Active, IAM service principal sp-agt-0142.")
CASES = [("policy only — expect partial", POLICY),
         ("policy + inventory record — expect full", POLICY + "\n\n" + RECORD),
         ("unrelated text — expect none", "Lunch menu: chicken rice, laksa, kopi. Cashless payment only.")]

print(f"Assessor: {model_name()}  |  Control: {ctl.id} {ctl.title}\n")
for label, ev in CASES:
    print("==", label)
    out = assess(ctl, ev)
    print(f"   sufficiency={out['sufficiency']}  maturity={out['proposedMaturity']}")
    print(f"   excerpt: {out['excerpt']!r}")
    print(f"   gaps: {out['gaps']}")
    print(f"   flags: {out['flags']}")
    print(f"   ask: {out.get('reviewerPrompt','')}\n")
