"""Streamlit dataframes must not hand pyarrow a column of mixed type.

`{"Maturity": c["maturity"] or "—"}` produced ints and a string in one column. pyarrow logged a
full traceback on every render and then silently applied "automatic fixes for column types",
which is the worst of both: noisy, and the displayed types are then whatever the fixer chose.

The fix is to render the column as text rather than to coerce it numerically — int-plus-missing
becomes float64 in pandas and maturity 3 would display as "3.0", and a numeric column would have
to represent "not assessed" as NaN, collapsing absent into a value.
"""
import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pd = pytest.importorskip("pandas")
pa = pytest.importorskip("pyarrow")


def _dataframe_columns_mixing_value_and_placeholder(path: Path):
    """Columns built as `<expr> or "<string>"`, where <expr> may not be a string."""
    src = path.read_text(encoding="utf-8")
    out = []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "dataframe"):
            continue
        seg = ast.get_source_segment(src, node) or ""
        for m in re.finditer(r'"([A-Za-z ][A-Za-z ]*)":\s*([a-zA-Z_][\w\[\]"\'\.]*)\s+or\s+"', seg):
            out.append((node.lineno, m.group(1), m.group(2)))
    return out


def test_the_maturity_column_is_rendered_as_text():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"Maturity": str(c["maturity"]) if c["maturity"] else "—"' in src
    assert '"Maturity": c["maturity"] or "—"' not in src


def test_a_mixed_maturity_column_would_break_arrow():
    """Pins why the fix is needed rather than trusting it stays fixed by habit."""
    with pytest.raises(Exception):
        pa.Table.from_pandas(pd.DataFrame([{"Maturity": 3}, {"Maturity": "—"}]))


def test_the_rendered_column_converts_cleanly():
    pa.Table.from_pandas(pd.DataFrame([{"Maturity": "3"}, {"Maturity": "—"}]))


def test_no_numeric_column_is_left_mixing_with_a_string_placeholder():
    """`Disposition`, `Reviewer` and `Design rating` are all-string and are fine.

    This catches a numeric field acquiring a placeholder later — the failure only shows at
    render time, where it is a log line rather than an exception, so nothing else would catch it.
    """
    NUMERIC_HINTS = ("maturity", "score", "count", "rating_value", "n_", "accuracy", "days")
    offenders = [(ln, col, expr)
                 for ln, col, expr in _dataframe_columns_mixing_value_and_placeholder(ROOT / "app.py")
                 if any(h in col.lower() or h in expr.lower() for h in NUMERIC_HINTS)]
    assert not offenders, f"numeric dataframe column with a string placeholder: {offenders}"
