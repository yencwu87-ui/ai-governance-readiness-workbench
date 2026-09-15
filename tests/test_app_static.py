"""Static UI invariants; deliberately does not import Streamlit."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def test_contract_report_is_defined_before_every_call():
    tree = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))
    defs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_contract_report"]
    assert len(defs) == 1, "app.py must have exactly one _contract_report definition"
    definition_line = defs[0].lineno
    calls = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_contract_report"]
    assert calls, "app.py must actually call _contract_report"
    assert min(calls) > definition_line, (
        f"_contract_report is called at lines {sorted(calls)} before its definition at {definition_line}"
    )


def test_compare_dashboard_reads_canonical_agreement_count():
    text = APP.read_text(encoding="utf-8")
    assert 's.get("n_agree", s.get("agreements", 0))' in text
