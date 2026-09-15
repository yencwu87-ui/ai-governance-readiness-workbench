"""GE-109 — the event/control-plane boundary.

One rule, expressed four ways: **the UI may not write to the governance ledger.** It asks
`core.cycle` to, and `core.cycle` decides whether the write is allowed.

Why this needs a test rather than a convention. `core/cycle.py` was extracted precisely to stop
the UI owning the cycle, and its own docstring says a UI is not a control. The extraction
happened; the migration did not, and for months `app.py` called four cycle functions and wrote
`proposed`, `compared`, `challenged`, `note` and `observed` itself. The visible cost was that a
guard written inside a cycle function did not exist for anyone using the app — WB-103's
bundle-hash check sat inside `assess()` and protected nothing until WB-105 made it public.

A boundary that is only a convention is a boundary that has already been crossed.
"""
import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

APP = ROOT / "app.py"
CYCLE = ROOT / "core" / "cycle.py"

#: The kinds that constitute the governance record. `note` and `observed` are included: a note
#: is attributable and an observation is evidence, so both are ledger writes even though neither
#: carries a rating.
GOVERNANCE_KINDS = {"cycle_started", "evidence_bound", "gap_scanned", "proposed", "read",
                    "compared", "challenged", "decided", "superseded", "note", "observed"}


# ------------------------------------------------------------------ KINDS completeness

def _appended_kinds(path: Path) -> set[str]:
    """Every literal kind passed to `events.append(...)` in a module.

    Matched on the full attribute path, not the method name: `rows.append("LOCAL")` is a list,
    not a ledger write, and an earlier version of this check flagged six of them.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr != "append":
            continue
        if getattr(fn.value, "id", "") != "events":
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
        else:
            found.add("<non-literal kind>")
    return found


def test_every_kind_the_cycle_appends_is_registered():
    """The bug that motivated this file.

    `cycle.gap_scan()` appended `gap_scanned`, which was not in `KINDS`, so `events.append`
    raised on every call from the day it shipped. Nothing caught it because the WB-103 tests
    exercised `completeness.scan` directly and never went through the cycle.
    """
    import events
    missing = _appended_kinds(CYCLE) - set(events.KINDS)
    assert not missing, f"cycle appends kinds absent from events.KINDS: {sorted(missing)}"


def test_kinds_has_no_entries_nothing_writes():
    """The reverse direction is a warning, not a failure — a kind may be written elsewhere."""
    import events
    assert "gap_scanned" in events.KINDS
    assert len(set(events.KINDS)) == len(events.KINDS), "duplicate entry in KINDS"


# ------------------------------------------------------------------ the boundary itself

def test_the_ui_has_no_governance_write_path_outside_the_cycle():
    """No `events.append(...)` anywhere in app.py. Not one, not a special case.

    A single exempted call site is how the last boundary eroded: the write was cheaper than the
    function, so the next one was written directly too.
    """
    offenders = _appended_kinds(APP)
    assert not offenders, (
        "app.py writes to the ledger directly: "
        f"{sorted(offenders)} — route these through core.cycle")


def test_app_py_calls_events_append_zero_times_textually():
    """Belt and braces: the AST check misses a dynamically built call, a grep does not."""
    src = APP.read_text(encoding="utf-8")
    hits = [ln.strip() for ln in src.splitlines()
            if re.search(r"events\s*\.\s*append\s*\(", ln)]
    assert not hits, f"direct ledger writes remain in app.py: {hits}"


def test_the_ui_may_still_read_the_ledger():
    """Reads are not the boundary. `events.state`, `events.decided`, `events.cycle` are fine.

    Stated as a test so nobody 'fixes' the boundary by banning the module outright — the UI has
    to project governed state to render anything honest.
    """
    src = APP.read_text(encoding="utf-8")
    assert "events.state(" in src, "the UI should still project state from the ledger"


# ------------------------------------------------------------------ cycle covers the need

@pytest.mark.parametrize("fn", ["start", "bind_evidence", "rebind_evidence", "gap_scan",
                                "assess", "record_proposal", "record_read", "compare_reads",
                                "record_compare", "challenge", "challenge_read",
                                "record_challenge", "record_note", "record_observation",
                                "decide", "check_bundle_unchanged"])
def test_cycle_exposes_every_write_the_ui_needs(fn):
    """If the UI has a legitimate write with no cycle function, the boundary cannot hold."""
    import core.cycle as cyc
    assert hasattr(cyc, fn), f"core.cycle is missing {fn}"
    assert fn in cyc.__all__, f"{fn} is not public API"


# ------------------------------------------------------------------ the guards actually guard

def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_EVENTS", str(tmp_path / "events.jsonl"))
    for mod in ("events", "core.cycle"):
        sys.modules.pop(mod, None)
    import events, core.cycle as cyc
    return events, cyc


def test_record_proposal_refuses_a_failed_assessor_call(tmp_path, monkeypatch):
    """The guard the UI was skipping. A failed call is not a rating of `none`."""
    _events, cyc = _fresh(tmp_path, monkeypatch)
    with pytest.raises(Exception) as exc:
        cyc.record_proposal("no-such-cycle", {"status": "error", "model": "error"})
    assert "no such cycle" in str(exc.value) or "failed" in str(exc.value)


def test_record_note_requires_a_named_actor(tmp_path, monkeypatch):
    _events, cyc = _fresh(tmp_path, monkeypatch)
    with pytest.raises(Exception):
        cyc.record_note("c", {"x": 1}, actor="   ")


def test_record_compare_refuses_a_diff_that_does_not_say_if_it_is_comparable(tmp_path, monkeypatch):
    _events, cyc = _fresh(tmp_path, monkeypatch)
    with pytest.raises(Exception):
        cyc.record_compare("c", {"summary": {}})


def test_record_challenge_refuses_an_empty_record(tmp_path, monkeypatch):
    _events, cyc = _fresh(tmp_path, monkeypatch)
    with pytest.raises(Exception):
        cyc.record_challenge("c", {})


# ------------------------------------------------------------------ the cache is only a cache

def test_the_state_file_cannot_carry_a_decision_forward():
    """`assessments.json` is stripped of ledger-owned keys on load.

    Before GE-109 the file said "cache only" in a comment while
    `_sync_authoritative_decisions` overwrote `decisions` only `if projected` — so a cache with
    decisions and a ledger without them left the cache standing as the record.
    """
    src = APP.read_text(encoding="utf-8")
    assert "_LEDGER_OWNED" in src
    assert 'S["decisions"] = _event_decisions()' in src, (
        "decisions must be rebuilt from the ledger unconditionally")
    assert "if projected:" not in src, "the conditional rebuild is back"


def test_decisions_are_dropped_from_a_loaded_cache(tmp_path, monkeypatch):
    """Behavioural, not textual: load a state file carrying a decision and check it is gone."""
    src = APP.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "load_state")
    owned = next(n for n in tree.body
                 if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "_LEDGER_OWNED")
    ns: dict = {}
    exec(compile(ast.Module([owned], []), "<t>", "exec"), ns)
    state_file = tmp_path / "assessments.json"
    state_file.write_text('{"org":"Acme","decisions":{"k":{"sufficiency":"full"}}}')
    ns.update({"STATE_FILE": state_file, "json": __import__("json")})
    exec(compile(ast.Module([fn], []), "<t>", "exec"), ns)
    loaded = ns["load_state"]()
    assert loaded["org"] == "Acme", "ordinary UI state must survive"
    assert loaded["decisions"] == {}, "a decision in the cache must not survive load"
