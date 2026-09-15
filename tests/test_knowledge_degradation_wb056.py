"""WB-056 — a retrieval that could not run must never look like one that found nothing.

Before this, `search_web` caught every exception and returned `[]`, and the resolver was called
inside a bare `except Exception` that degraded to a generic message. A missing `ddgs`, a blocked
network and a genuinely quiet search were indistinguishable, and an assessment shaped by no
external knowledge at all carried no indication of it. Two swallows in series is how a dead
feature looks healthy.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ollama_search as OS  # noqa: E402
from governance import knowledge_resolver as KR  # noqa: E402


class _Ctl:
    id, lib, req, title = "M3.6", "Control Library - MAS", "validation requirement", "Validation"
    owner, maps, key = "CRO", "", "MAS::M3.6"


def test_a_missing_dependency_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setitem(sys.modules, "ddgs", None)
    rows, err = OS.search_web_checked("anything")
    assert rows == []
    assert err and "ddgs" in err


def test_a_failing_search_is_reported(monkeypatch):
    class _Boom:
        def __enter__(self): raise RuntimeError("rate limited")
        def __exit__(self, *a): return False
    monkeypatch.setitem(sys.modules, "ddgs", type("m", (), {"DDGS": _Boom}))
    rows, err = OS.search_web_checked("anything")
    assert rows == [] and "rate limited" in err


def test_an_empty_result_is_not_an_error(monkeypatch):
    """No results is a result. It must stay distinguishable from no search."""
    class _Empty:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, *a, **k): return []
    monkeypatch.setitem(sys.modules, "ddgs", type("m", (), {"DDGS": _Empty}))
    rows, err = OS.search_web_checked("anything")
    assert rows == [] and err is None


def test_the_resolver_marks_a_degraded_retrieval(monkeypatch):
    monkeypatch.setattr(KR, "_web", lambda q, n=5: ([], "the web search failed (RuntimeError: nope)"))
    monkeypatch.setenv("WB_WEB_KNOWLEDGE", "always")
    b = KR.resolve(_Ctl(), "evidence", task="current guidance")
    assert b["web_degraded"] is True
    assert b["web_used"] is False
    assert "COULD NOT BE RETRIEVED" in b["web_context"]
    assert KR.resolver_flags(b)


def test_a_successful_empty_search_is_not_degraded(monkeypatch):
    monkeypatch.setattr(KR, "_web", lambda q, n=5: ([], None))
    monkeypatch.setenv("WB_WEB_KNOWLEDGE", "always")
    b = KR.resolve(_Ctl(), "evidence", task="current guidance")
    assert b["web_degraded"] is False
    assert KR.resolver_flags(b) == []
    assert "searched and returned nothing" in b["web_context"]


def test_a_search_that_was_never_attempted_is_not_degraded(monkeypatch):
    monkeypatch.setenv("WB_WEB_KNOWLEDGE", "off")
    b = KR.resolve(_Ctl(), "evidence", task="anything")
    assert b["web_attempted"] is False and b["web_degraded"] is False
    assert KR.resolver_flags(b) == []


def test_the_degradation_reaches_the_proposal_flags(monkeypatch):
    """The field the UI renders. A degradation recorded only in a side field is one nobody sees."""
    import assessor as A
    monkeypatch.setattr(A, "PROVIDER", "ollama")
    monkeypatch.setattr(A, "_ollama", lambda s, u: '{"excerpt":"x","gaps":[],"rationale":"r",'
                                                   '"sufficiency":"none","proposedMaturity":1,'
                                                   '"remediation":[],"reviewerPrompt":"q"}')
    monkeypatch.setattr(A, "model_name", lambda *a, **k: "stub")
    monkeypatch.setattr(A, "_contract_elements", lambda c: [])
    monkeypatch.setattr(A, "scan_injection", lambda t: [])
    monkeypatch.setattr(KR, "_web", lambda q, n=5: ([], "the ddgs package is not installed"))
    monkeypatch.setenv("WB_WEB_KNOWLEDGE", "always")
    out = A.assess(_Ctl(), "the validation report was approved")
    assert out["external_knowledge_degraded"] is True
    assert any("could not be retrieved" in f.lower() for f in out.get("flags", []))
