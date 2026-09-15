"""WB-062/070 — requirement provenance at the point of use, and elements drafted by selection.

The defect these answer: for 165 of 195 controls the governed "elements" are the control title
with a prefix. Four attempts to draft real ones from the instrument each lost everything, in a
different way, until the model stopped being asked to transcribe.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.control_contract import requirement_context  # noqa: E402


def de():
    spec = importlib.util.spec_from_file_location("de", ROOT / "tools" / "draft_elements.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Ctl:
    def __init__(self, cid="S4.2", lib="Control Library - SAFR", title="Gateway interception of actions"):
        self.id, self.lib, self.title = cid, lib, title
        self.req = "Provide an API-level chokepoint that intercepts outbound agent actions"
        self.owner, self.maps, self.key = "o", "", f"{lib}::{cid}"


INSTRUMENT = (
    "Section 4. Deployment controls. "
    "The institution should establish criteria for determining whether an agentic system is "
    "suitable for a given deployment context. "
    "The institution shall obtain approval from a designated authority before the system is "
    "deployed into a context assessed as high impact. "
    "This pattern is recommended for new deployments and is offered as an option. "
    "Records of such approvals should be retained for five years."
)


# ---------------- WB-062: provenance reaches the point of use ----------------

def test_requirement_context_carries_authority_and_draft_status():
    d = requirement_context("D1.1", "Control Library - MGF Agentic")
    assert d["authority"] == "draft" and d["is_draft"] is True and "test_provenance" in d


def test_an_authored_requirement_is_not_marked_draft():
    m = requirement_context("M3.6", "Control Library - MAS")
    assert m["is_draft"] is False and m["source"] == "requirements/mas.yaml"


def test_the_assessor_prompt_states_draft_authority():
    import assessor as A
    b = A._provenance_banner(_Ctl("D1.1", "Control Library - MGF Agentic"))
    assert "DRAFT" in b and "restate the control title" in b


def test_the_assessor_prompt_states_authored_authority():
    import assessor as A
    b = A._provenance_banner(_Ctl("M3.6", "Control Library - MAS"))
    assert "DRAFT" not in b and "requirements/mas.yaml" in b


def test_the_app_warns_when_elements_are_draft():
    app = (ROOT / "app.py").read_text()
    assert 'a.get("requirement_is_draft")' in app and "restate the control title" in app


# ---------------- candidates must be quotable ----------------

def test_every_candidate_is_verbatim_in_the_instrument():
    m = de()
    for s in m.candidates(INSTRUMENT, _Ctl()):
        assert m.anchored_in(s, INSTRUMENT)


def test_no_candidate_begins_mid_sentence():
    """Run 3 lost everything because fixed-width chunking handed over passages starting
    "hms or features aligns with". A model cannot copy from a fragment."""
    m = de()
    body = ("Preamble words that will be cut across the chunk boundary somewhere in here. " * 40 +
            "The institution shall obtain approval before deployment into a high impact context. " +
            "Trailing text that also gets cut somewhere in the middle of a word. " * 40)
    for s in m.candidates(body, _Ctl()):
        assert s[0].isupper() or s[0].isdigit() or s[0] == "(", s[:60]


def test_candidates_keep_document_order():
    m = de()
    got = m.candidates(INSTRUMENT, _Ctl())
    assert got.index([s for s in got if "establish criteria" in s][0]) < \
           got.index([s for s in got if "Records of such approvals" in s][0])


# ---------------- selection cannot paraphrase ----------------

def _stub(monkeypatch, select_payload, state_payload):
    import assessor as A
    monkeypatch.setattr(A, "PROVIDER", "ollama")
    calls = []

    def fake(system, user):
        calls.append(user)
        if "You select sentences" in system:
            return select_payload
        return state_payload(user) if callable(state_payload) else state_payload
    monkeypatch.setattr(A, "_ollama", fake)
    return calls


def test_the_anchor_is_the_instrument_sentence_not_the_model_text(monkeypatch):
    """Run 4 lost everything because the model wrote the control's own objective into the quote
    slot. An index cannot be paraphrased, so the anchor is now verbatim by construction."""
    m = de()
    cands = m.candidates(INSTRUMENT, _Ctl())
    target = [i for i, s in enumerate(cands, 1) if "shall obtain approval" in s][0]
    _stub(monkeypatch, '{"picked":[%d],"note":""}' % target,
          '{"elements":[{"text":"Approval precedes high-impact deployment","kind":"operation"}]}')
    row = m.draft_one(_Ctl(), INSTRUMENT, True, "file:test.txt")
    e = row["elements"][0]
    assert e["anchor"] == cands[target - 1]
    assert m.anchored_in(e["anchor"], INSTRUMENT)
    assert e["confidence"] == "known"


def test_an_out_of_range_index_is_ignored_and_counted(monkeypatch):
    m = de()
    _stub(monkeypatch, '{"picked":[1,9999],"note":""}',
          '{"elements":[{"text":"Something is documented","kind":"design"}]}')
    row = m.draft_one(_Ctl(), INSTRUMENT, True, "file:test.txt")
    assert row["invalid_indices"] == 1
    assert len(row["selected"]) == 1


def test_selecting_nothing_is_a_reported_result_not_a_crash(monkeypatch):
    """SAFR offers gateway integration as a deployment option, not an obligation. An empty
    selection is the correct answer there and has to survive as one."""
    m = de()
    _stub(monkeypatch, '{"picked":[],"note":"the section describes an option"}', '{"elements":[]}')
    row = m.draft_one(_Ctl(), INSTRUMENT, True, "file:test.txt")
    assert row["elements"] == []
    assert "derived from descriptive text" in row["dropped"][0]["reason"]
    assert "option" in m.render(row)


def test_a_selected_sentence_with_no_stated_obligation_is_reported(monkeypatch):
    m = de()
    seen = {"n": 0}

    def per_sentence(user):
        seen["n"] += 1
        return ('{"elements":[{"text":"Only one stated","kind":"design"}]}' if seen["n"] == 1
                else '{"elements":[]}')
    _stub(monkeypatch, '{"picked":[1,2],"note":""}', per_sentence)
    row = m.draft_one(_Ctl(), INSTRUMENT, True, "file:test.txt")
    assert row["selected_not_stated"] == [2]
    assert "produced no element" in m.render(row)


def test_one_sentence_may_yield_two_elements(monkeypatch):
    m = de()
    _stub(monkeypatch, '{"picked":[1],"note":""}',
          '{"elements":[{"text":"Criteria are established for deployment context","kind":"design"},'
          '{"text":"Criteria are applied for determining","kind":"operation"}]}')
    row = m.draft_one(_Ctl(), INSTRUMENT, True, "file:test.txt")
    assert [e["id"] for e in row["elements"]] == ["e1", "e2"]
    assert row["elements"][0]["anchor"] == row["elements"][1]["anchor"]


def test_an_all_design_decomposition_is_called_out(monkeypatch):
    m = de()
    _stub(monkeypatch, '{"picked":[1],"note":""}',
          '{"elements":[{"text":"Criteria are documented","kind":"design"}]}')
    assert "Every element is design-side" in m.render(m.draft_one(_Ctl(), INSTRUMENT, True, "f"))


def test_unverified_instrument_never_yields_known_confidence(monkeypatch):
    m = de()
    _stub(monkeypatch, '{"picked":[1],"note":""}',
          '{"elements":[{"text":"Something is documented","kind":"design"}]}')
    row = m.draft_one(_Ctl(), INSTRUMENT, False, "web-search (advisory, unverified)")
    assert row["elements"][0]["confidence"] == "unchecked"


# ---------------- the M3.6 failure: one anchor on every element ----------------

def test_each_element_carries_the_anchor_of_its_own_sentence(monkeypatch):
    """The first real M3.6 run produced 37 elements all carrying the same anchor. Batched, the
    second call enumerated the instrument and ignored the numbering. One sentence per call means
    the anchor is never named by the model and so cannot detach from its obligation."""
    m = de()
    cands = m.candidates(INSTRUMENT, _Ctl())
    picked = [1, 2]

    def per_sentence(user):
        body = user.split("SENTENCE:\n", 1)[1].split("\n\n")[0]
        return '{"elements":[{"text":"obligation from: %s","kind":"design"}]}' % body[:40]
    _stub(monkeypatch, '{"picked":[1,2],"note":""}', per_sentence)
    row = m.draft_one(_Ctl(), INSTRUMENT, True, "file:test.txt")
    anchors = [e["anchor"] for e in row["elements"]]
    assert len(set(anchors)) == 2
    for e in row["elements"]:
        assert e["anchor"][:40] in e["text"]        # each element states ITS own sentence


def test_over_selection_is_capped_and_reported(monkeypatch):
    """42 of 47 selected is acceptance, not selection, and a decomposition built from that many
    sentences is the instrument re-typed rather than a control's requirement."""
    m = de()
    long_instrument = " ".join(
        f"The institution should perform duty number {n} before deploying any agent."
        for n in range(1, 21))
    cands = m.candidates(long_instrument, _Ctl())
    assert len(cands) > m.MAX_SELECTED
    _stub(monkeypatch, json_dumps_picked(list(range(1, len(cands) + 1))),
          '{"elements":[{"text":"x","kind":"design"}]}')
    row = m.draft_one(_Ctl(), long_instrument, True, "file:test.txt")
    assert row["over_selected"] is True
    assert row["selected_count_raw"] == len(cands)
    assert len(row["selected"]) == m.MAX_SELECTED
    assert "Selection guard:" in m.render(row)


def json_dumps_picked(nums):
    import json as _j
    return _j.dumps({"picked": nums, "note": ""})


def test_function_words_are_rejected():
    m = de()
    assert m.element_is_obligation("of")[0] is False
    assert m.element_is_obligation("and")[0] is False
    assert m.element_is_obligation("The FI should conduct validation")[0] is True


def test_element_anchor_mismatch_is_rejected():
    m = de()
    ok, reason, _ = m.element_anchor_match("The FI should be well-governed", "Validation should cover testing results")
    assert ok is False
    assert reason == "element_tokens_not_supported_by_own_anchor"


def test_subject_swap_is_rejected_even_when_words_overlap():
    m = de()
    ok, reason = m.element_subject_match(
        "The FI should be well-governed",
        "The AI system should be well-governed before deployment.",
    )
    assert ok is False
    assert reason == "obligated_subject_not_supported_by_anchor"


def test_running_header_is_removed_before_sentencing():
    m = de()
    raw = "Proposed Guidelines on AI Risk Management | 25\nformal independent validation before deployment.\n"
    got = m.sentences(raw)
    assert got == []  # lowercase continuation remains a fragment and cannot become an anchor
