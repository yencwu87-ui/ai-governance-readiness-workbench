#!/usr/bin/env python3
"""Report the current v0.4 control-plane readiness without changing any artefact."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from governance.register_checks import validate_ticket_register
from governance.release_gate import evaluate_release_gate
from governance.link_check import run as link_run
from governance.knowledge import validate_control_testing
from governance.control_contract import validate_contracts, validate_per_framework


def main() -> int:
    register = validate_ticket_register(ROOT / "governance" / "tickets.csv", root=ROOT)
    links = link_run()
    results = json.loads((ROOT / "governance" / "eval_results.json").read_text())
    import hashlib as _hashlib
    set_path = ROOT / "eval" / "golden_set.jsonl"
    current_sha = _hashlib.sha256(set_path.read_bytes()).hexdigest()[:12]
    matching = [r for r in results if r.get("eval_set_sha256_12") == current_sha]
    gate = evaluate_release_gate(matching[-1]) if matching else {"status":"INCONCLUSIVE","failed":["current evaluation corpus has not been scored" ]}
    testing_errors = validate_control_testing(ROOT / "governance" / "knowledge" / "control_testing.yaml")
    contract_errors = validate_per_framework()

    print("Governance Engine v0.5 status")
    print(f"  ticket register : {'PASS' if not register['errors'] else 'BLOCKED'} ({len(register['errors'])} error(s), {len(register.get('warnings', []))} historical warning(s))")
    print(f"  link integrity  : {'PASS' if not links['errors'] else 'BLOCKED'} ({len(links['errors'])} error(s))")
    print(f"  eval release    : {gate['status']} ({', '.join(gate['failed']) or 'no failures'})")
    active_manifest = json.loads((ROOT / "eval" / "active_set.json").read_text())
    print(f"  eval corpus     : {active_manifest['case_count']} cases, sha {active_manifest['sha256_12']}, real-full {active_manifest['real_full_cases']}")
    print(f"  Lane B coverage : {links['counts']['lane_b_covered']}/{links['counts']['with_tests']}")
    print(f"  critical human-only/uncovered: {len(links['critical_uncovered'])}")
    print(f"  testing knowledge: {'PASS' if not testing_errors else 'BLOCKED'} ({len(testing_errors)} error(s))")
    print(f"  control contracts: {'PASS' if not contract_errors else 'BLOCKED'} ({len(contract_errors)} error(s))")
    return 0 if register['errors'] == [] and links['errors'] == [] and gate['status'] == 'PASS' else 1


if __name__ == "__main__":
    raise SystemExit(main())
