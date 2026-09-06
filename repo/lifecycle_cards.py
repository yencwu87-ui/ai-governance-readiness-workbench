"""Lifecycle cards — the assessor's working surface. One use case, 11 plays, one card per step.

render(plays, index, lane_b) is called from app.py inside the Lifecycle tab.
  plays  : output of plays.load_plays(...)            (Play objects, see plays.py)
  index  : the scanner.Index from pipeline.index_folder(), or its chunk list, or a
           {doc_id: text} dict — documents are rebuilt per source path
  lane_b : output of pipeline.latest_lane_b()          (control_id -> latest result)

Nothing here writes except decisions.record(), and only on a reviewer's click.
"""
from __future__ import annotations

import re

import streamlit as st

import decisions as D
import usecases as U
from judge import StepContext, judge_step, call_ollama
from retriever import HybridIndex, chunk_documents
from validator import validate, make_gate_check

BADGE = {"not_started": "⚪", "in_progress": "🟡", "gate_passed": "🟢", "gate_failed": "🔴", "locked": "🔒"}
SUFF = ["full", "partial", "none"]


def _g(o, k, d=None):
    return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)


@st.cache_resource(show_spinner="Indexing evidence (BM25 + embeddings)…")
def _index(docs_key: str, docs: dict[str, str], use_embeddings: bool) -> HybridIndex:
    return HybridIndex(chunk_documents(docs), use_embeddings=use_embeddings)


def _docs_from(index) -> dict[str, str]:
    """scanner.Index | list[chunk] | dict -> {path: text}. Chunks are re-joined per path so the
    hybrid retriever chunks them consistently."""
    if index is None:
        return {}
    if isinstance(index, dict):
        return index
    chunks = getattr(index, "chunks", index)
    docs: dict[str, list[str]] = {}
    for ch in chunks or []:
        docs.setdefault(str(getattr(ch, "path", getattr(ch, "label", "doc"))), []).append(getattr(ch, "text", ""))
    return {k: "\n\n".join(v) for k, v in docs.items()}


def _header_field(header: str, name: str) -> str:
    """Pull 'Trigger', 'Frequency', 'Owner', 'Exit gate' out of the play header text."""
    m = re.search(rf"{name}\s*[—–:-]+\s*(.+?)(?=\s*\|\s*(?:Trigger|Frequency|Owner|Exit gate)|$)",
                  header or "", flags=re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _tests_by_step(lane_b: dict[str, dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for r in (lane_b or {}).values():
        for ref in r.get("play_refs", []):
            by.setdefault(ref, []).append(r)
    return by


def render(plays: list, index, lane_b: dict[str, dict], reviewer: str = "") -> None:
    docs = _docs_from(index)
    by_step = _tests_by_step(lane_b)
    st.subheader("Lifecycle — per use case")
    cases = U.load()
    left, right = st.columns([3, 2])
    with left:
        if not cases:
            st.info("No use cases yet. Add one on the right.")
            uc = None
        else:
            uc = st.selectbox("Use case", cases, format_func=lambda c: f"{c.id} · {c.name} ({c.materiality})")
    with right:
        with st.expander("Add use case"):
            nid = st.text_input("id", placeholder="UC-004")
            nname = st.text_input("name")
            nown = st.text_input("owner")
            nmat = st.selectbox("materiality", U.MATERIALITY, index=1)
            if st.button("Add") and nid and nname:
                cases.append(U.UseCase(nid.strip(), nname.strip(), nown.strip(), nmat))
                U.save(cases); st.rerun()
    reviewer = reviewer or st.text_input("Reviewer (named)", key="lc_reviewer")
    use_emb = st.toggle("Semantic retrieval (local embeddings)", value=True)
    if uc is None:
        return

    idx = _index("|".join(sorted(docs)), docs, use_emb)
    st.caption(f"Retrieval: {'BM25 + embeddings ' + idx.embed_status if idx.chunks else idx.embed_status} · {len(idx.chunks)} chunks · {len(docs)} documents")

    status = D.play_status(plays, uc.id)
    lat = D.latest(uc.id)

    # strip of 11 plays
    cols = st.columns(len(plays))
    for c, p in zip(cols, plays):
        pid = _g(p, "id")
        c.markdown(f"<div style='text-align:center'>{BADGE[status[pid]]}<br><small>{pid}</small></div>",
                   unsafe_allow_html=True)

    open_ids = [_g(p, "id") for p in plays if status[_g(p, "id")] != "locked"]
    first_open = next((i for i, pid in enumerate(open_ids) if status[pid] != "gate_passed"), 0)
    sel = st.selectbox("Play", open_ids, index=first_open)
    play = next(p for p in plays if _g(p, "id") == sel)
    hdr = _g(play, "header", "")
    trigger, owner, gate = _header_field(hdr, "Trigger"), _header_field(hdr, "Owner"), _header_field(hdr, "Exit gate")
    st.markdown(f"**{sel} — {_g(play,'title','')}**  \n"
                f"Trigger: {trigger} · Owner: {owner}  \n"
                f"Exit gate: *{gate}*")

    controls_str = _controls_str(play)
    for s in _g(play, "steps", []) or []:
        sid = _g(s, "id")
        expected = _g(s, "evidence", "") or ""
        dec = lat.get(sid)
        head = f"{sid} · {_g(s,'owner','')} — {(_g(s,'action','') or '')[:90]}"
        if dec:
            head += f"   ✔ {dec['decision']} ({(dec['final'] or {}).get('sufficiency','?')})"
        with st.expander(head, expanded=dec is None):
            st.markdown(f"**Action** {_g(s,'action','')}  \n**Expected output** {expected}")
            lb = sorted(by_step.get(sid, []), key=lambda r: r["control_id"])
            if lb:
                st.markdown("**Operating test (Lane B)** " + ", ".join(
                    f"{t['control_id']}: {t['machine_verdict']}" for t in lb))

            q = f"{_g(s,'action','')} {expected}"
            hits = idx.search(q, k=6)
            if hits:
                st.markdown("**Evidence retrieved**")
                for h in hits:
                    tag = "+".join(h.found_by) + (f" · terms: {', '.join(h.bm25_terms[:6])}" if h.bm25_terms else "")
                    st.markdown(f"- `{h.chunk.label}` <small>{tag}</small>", unsafe_allow_html=True)
                    st.caption(h.chunk.text[:280].replace("\n", " ") + ("…" if len(h.chunk.text) > 280 else ""))
            else:
                st.warning("No evidence retrieved for this step.")

            key = f"prop_{uc.id}_{sid}"
            if st.button("Ask judge", key=f"btn_{key}"):
                ctx = StepContext(sel, _g(play, "title", ""), gate, controls_str,
                                  sid, _g(s, "owner", ""), _g(s, "action", ""), expected, uc.name, uc.materiality)
                with st.spinner("Judging…"):
                    prop = judge_step(ctx, hits)
                    gchk = make_gate_check(gate, _steps_summary(play, lat), hits, call_ollama)
                    v = validate(prop, hits, expected, sid, lat, gate_check=gchk)
                st.session_state[key] = (prop, v)

            prop, v = st.session_state.get(key, (None, None))
            if prop:
                c1, c2 = st.columns([2, 3])
                with c1:
                    st.markdown(f"**Judge proposes:** `{prop['sufficiency']}` · confidence {prop['confidence']:.2f}")
                    if v.status == "needs_review":
                        st.error("Validator: needs review" + (f" — downgraded to `{v.downgraded_to}`" if v.downgraded_to else ""))
                        for fnd in v.failures:
                            st.markdown(f"- {fnd.check}: {fnd.detail}")
                    else:
                        st.success("Validator: all checks passed")
                    with st.expander("Checks"):
                        for fnd in v.findings:
                            st.markdown(f"{'✅' if fnd.ok else '❌'} {fnd.check} {fnd.detail}")
                with c2:
                    st.markdown("**Reasoning** " + prop.get("reasoning", ""))
                    for ce in prop.get("cited_excerpts", []):
                        st.markdown(f"> `{ce.get('chunk_id','')}` {ce.get('text','')}")
                    if prop.get("gaps"):
                        st.markdown("**Gaps**\n" + "\n".join(f"- {g}" for g in prop["gaps"]))
                    if prop.get("suggested_evidence"):
                        st.markdown("**Would close the gap**\n" + "\n".join(f"- {g}" for g in prop["suggested_evidence"]))

            # decision row — the only write
            st.markdown("---")
            default = (v.downgraded_to or prop["sufficiency"]) if prop else "partial"
            fs = st.selectbox("Recorded sufficiency", SUFF, index=SUFF.index(default), key=f"fs_{key}")
            reason = st.text_input("Reason (required on amend/reject)", key=f"rs_{key}")
            b1, b2, b3 = st.columns(3)
            final = {"sufficiency": fs, "gaps": (prop or {}).get("gaps", [])}
            for col, label in ((b1, "accept"), (b2, "amend"), (b3, "reject")):
                if col.button(label.capitalize(), key=f"{label}_{key}", disabled=not reviewer.strip()):
                    try:
                        if label == "accept" and prop and fs != prop["sufficiency"]:
                            st.warning("Sufficiency differs from the proposal — use Amend."); continue
                        D.record(uc.id, sid, label, reviewer, reason, prop, final)
                        st.session_state.pop(key, None); st.rerun()
                    except ValueError as e:
                        st.error(str(e))

    with st.expander("Judge calibration (all use cases)"):
        cal = D.calibration()
        st.write(cal["total"])
        if cal["per_play"]:
            st.dataframe(cal["per_play"])


def _controls_str(play) -> str:
    c = _g(play, "controls", {}) or {}
    if isinstance(c, dict):
        return " | ".join(f"{lib} {', '.join(map(str, ids))}" for lib, ids in c.items())
    return str(c)


def _steps_summary(play, lat: dict[str, dict]) -> str:
    parts = []
    for s in _g(play, "steps", []) or []:
        sid = _g(s, "id"); d = lat.get(sid)
        parts.append(f"{sid}: {(d['final'] or {}).get('sufficiency','undecided') if d else 'undecided'}")
    return "; ".join(parts)
