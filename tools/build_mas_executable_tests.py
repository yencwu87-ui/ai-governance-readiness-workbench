"""Sync the executable MAS catalog into the Control Testing Brain."""
from pathlib import Path
import yaml
from caa.mas_tests import export_catalog

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "governance" / "knowledge" / "mas_executable_tests.yaml"

def main():
    data = {
        "schema_version": "0.4.mas-executable-tests.1",
        "purpose": "Executable evidence-floor checks derived from the approved v0.4 MAS Test of Design and Test of Operating Effectiveness procedures.",
        "authority": "Testing procedure remains subject to human approval; this file contains executable interpretations, not regulatory text.",
        "controls": export_catalog(),
    }
    OUT.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False))
    print(f"wrote {OUT} ({len(data['controls'])} controls)")

if __name__ == "__main__":
    main()
