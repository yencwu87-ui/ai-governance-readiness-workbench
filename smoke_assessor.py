"""Manual smoke check of the assessor against whichever model is configured.

    python smoke_assessor.py

Not a pytest test — it makes live model calls and is eyeballed, not asserted.
It was previously named test_assessor.py with its calls at module level, so
pytest collected it, imported it, and a single unreachable endpoint aborted
collection for the whole suite before any deterministic test ran.

For scored assessor quality use eval/score.py against the golden set. This
script only answers "is the configured model reachable and roughly sane".
"""
import argparse
from pathlib import Path

from assessor import assess, model_name
from playbook import load_controls

POLICY = ("Our AI Acceptable Use Policy v2.1 (approved by the AI Risk Committee, March 2026) states that all AI agents "
          "must be registered in the enterprise AI inventory before deployment to production.")
RECORD = ('Extract from AI Inventory (SNOW CMDB, 28 Aug 2026): AGT-0142 "Trade-recon assistant", owner J. Tan, '
          "registered 12 Jun 2026, status Active, IAM service principal sp-agt-0142.")
CASES = [("policy only — expect partial", POLICY),
         ("policy + inventory record — expect full", POLICY + "\n\n" + RECORD),
         ("unrelated text — expect none", "Lunch menu: chicken rice, laksa, kopi. Cashless payment only.")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--playbook", default=None,
                    help="workbook path (default: first .xlsx in data/)")
    ap.add_argument("--control", default="S1.1",
                    help="control id prefix to exercise (default: S1.1)")
    ap.add_argument("--lib", default="SAFR", help="library the control is in")
    a = ap.parse_args()

    xlsx = Path(a.playbook) if a.playbook else next(Path("data").glob("*.xlsx"), None)
    if not xlsx:
        raise SystemExit("Put the playbook workbook in data/ first, or pass --playbook")

    controls = load_controls(xlsx)
    if a.lib not in controls:
        raise SystemExit(f"No library {a.lib!r}. Available: {sorted(controls)}")
    ctl = next((c for c in controls[a.lib] if c.id.startswith(a.control)), None)
    if ctl is None:
        raise SystemExit(f"No control starting {a.control!r} in {a.lib}")

    print(f"Assessor: {model_name()}  |  Control: {ctl.id} {ctl.title}\n")
    for label, ev in CASES:
        print("==", label)
        try:
            out = assess(ctl, ev)
        except Exception as e:
            print(f"   FAILED: {type(e).__name__}: {e}\n")
            continue
        print(f"   sufficiency={out['sufficiency']}  maturity={out['proposedMaturity']}")
        print(f"   excerpt: {out['excerpt']!r}")
        print(f"   gaps: {out['gaps']}")
        print(f"   flags: {out['flags']}")
        print(f"   ask: {out.get('reviewerPrompt','')}\n")

    print("Eyeball only. These three cases are not a scored evaluation —\n"
          "use eval/score.py against the golden set for that.")


if __name__ == "__main__":
    main()
