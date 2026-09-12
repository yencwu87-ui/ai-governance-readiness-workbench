import datetime as dt
import json
import os
from pathlib import Path

import streamlit as st

from assessor import PROVIDER, model_name
from scanner import MIN_RATIO, MIN_SCORE, TOP_K, SelfScanError, self_scan_reason, signals_for
from pipeline import (build_evidence, control_history, export_playbook, gap_analysis, index_folder, is_error, list_bundles,
                      load_bundle, match_controls, open_items, propose, record_decision, run_audit, sign_result, unsign_result,
                      latest_lane_b, lifecycle_view)
from plays import load_plays
from reasons import reason_error
from challenge import challenge as run_challenge, challenge_disagreement as run_challenge2
from compare import compare as compare_reads, headline as compare_headline, elements_for
from challenge_dossier import create_dossier, respond as respond_to_challenge, append as append_dossier
from caa.review import DISPOSITIONS
from playbook import LIBRARIES, load_controls
from demo_evidence import generate_pack as generate_demo_evidence
import folder_picker as fp
import tour

DATA = Path("data")
DATA.mkdir(exist_ok=True)
STATE_FILE = DATA / "assessments.json"
DEFAULT_PLAYBOOK = next(DATA.glob("*.xlsx"), None)

st.set_page_config(page_title="AI governance readiness workbench", layout="wide")


# ---------- persistence ----------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"org": "", "reviewer": "", "evidence": {}, "ai": {}, "decisions": {},
            "blind": {}, "challenge": {}, "challenge2": {}}


def save_state():
    STATE_FILE.write_text(json.dumps(st.session_state.s, indent=1, default=str))


if "s" not in st.session_state:
    st.session_state.s = load_state()
S = st.session_state.s

# Theme is a persisted preference, applied before any component draws.
THEME = "dark" if S.get("dark") else "light"
tour.apply_theme(THEME)
COL = tour.theme_colors(THEME)
pill = lambda s: f'<span class="pill" style="background:{COL.get(s, COL["pending"])}">{s}</span>'


def stages(*items) -> str:
    """A four-stage strip for the Assess tab: where you are, and what is still ahead.

    The assessment order is deliberate — the reviewer's own reading is recorded before any
    model output is shown — but a gate the user cannot see reads as a missing feature rather
    than a sequence. Hiding the challenge and assess buttons until a reading exists made the
    tab look like it had two controls when it has four. Showing all four stages, with the
    unreachable ones greyed, makes the order legible without making it optional.

    items: (label, state) where state is 'done', 'now' or 'wait'.
    """
    c = {"done": COL["full"], "now": COL["partial"], "wait": COL["pending"]}
    parts = [f'<span class="pill" style="background:{c[st_]}">{i}. {label}</span>'
             for i, (label, st_) in enumerate(items, 1)]
    sep = ' <span style="opacity:.4">&rsaquo;</span> '
    return '<div style="margin:.15rem 0 .7rem 0">' + sep.join(parts) + '</div>'

# ---------- sticky header (WB-024) ----------
# The title, the one-line framing and the tab bar stay put while the page scrolls. On a long
# control list or a long proposal the reader would otherwise lose both the tabs and the line
# that says a rating is not a compliance determination.
#
# Streamlit has no supported API for this, so it targets internal DOM attributes and may need
# revisiting after a Streamlit upgrade. If the layout looks wrong after one, delete this block:
# nothing else depends on it.
_STICKY_BG = "#12161C" if THEME == "dark" else "#FFFFFF"
_STICKY_LINE = "#2A313A" if THEME == "dark" else "#E4E8EE"
_STICKY_FG = "#E8ECF1" if THEME == "dark" else "#12233B"
_STICKY_SUB = "#9AA6B4" if THEME == "dark" else "#5B6B7F"
st.markdown(f"""<style>
  .wb-head {{
    position: sticky; top: 0; z-index: 1000;
    background: {_STICKY_BG};
    padding: .35rem 0 .55rem 0;
    border-bottom: 1px solid {_STICKY_LINE};
  }}
  .wb-head .wb-t {{ font-size: 1.55rem; font-weight: 800; color: {_STICKY_FG}; line-height: 1.2; }}
  .wb-head .wb-s {{ font-size: .82rem; color: {_STICKY_SUB}; margin-top: .15rem; }}
  /* the tab bar sits directly under the header and sticks below it */
  div[data-testid="stTabs"] > div[data-baseweb="tab-list"] {{
    position: sticky; top: 4.1rem; z-index: 999;
    background: {_STICKY_BG};
    border-bottom: 1px solid {_STICKY_LINE};
  }}
</style>""", unsafe_allow_html=True)

# ---------- sidebar ----------
with st.sidebar:
    st.title("Workbench")
    up = st.file_uploader("Playbook workbook (.xlsx)", type="xlsx")
    src = up if up else DEFAULT_PLAYBOOK
    if src is None:
        st.info("Upload the AI Governance Playbook workbook, or place it in the data/ folder. The Audit and History tabs work without it.")
    S["org"] = st.text_input("Organisation", S.get("org", ""))
    S["reviewer"] = st.text_input("Reviewer name", S.get("reviewer", ""))
    st.caption("Scope")
    scope = {lib: st.checkbox(lib, value=lib in ("MAS", "MGF Agentic", "SAFR"), key=f"scope_{lib}") for lib in LIBRARIES}
    if PROVIDER == "ollama":
        try:
            import requests
            tags = [m["name"] for m in requests.get("http://localhost:11434/api/tags", timeout=2).json().get("models", [])]
            st.caption(f"Assessor: {model_name()}" + ("" if model_name().split("/", 1)[1] in tags else " — model not pulled: run `ollama pull " + model_name().split("/", 1)[1] + "`"))
        except Exception:
            st.warning("Ollama not reachable at localhost:11434 — start the Ollama app.")
    else:
        try:
            if "ANTHROPIC_API_KEY" in st.secrets:
                os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
        except Exception:
            pass
        st.caption(f"Assessor: {model_name()}")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.warning("ANTHROPIC_API_KEY not set — assessments will fail.")
    st.divider()
    dark_now = st.toggle("Dark mode", value=bool(S.get("dark")), key="dark_toggle")
    if dark_now != bool(S.get("dark")):
        S["dark"] = dark_now
        save_state()
        st.rerun()
    S["guide"] = st.toggle("Show guide", value=S.get("guide", True), key="guide_toggle")
    save_state()

    with st.expander("Reset"):
        st.caption(
            "Clears work held in this workbench. Lane B evidence bundles are not touched — "
            "they are the hashed audit trail and are removed outside the app, if at all."
        )
        scope_reset = st.radio(
            "What to clear",
            ["Assessments and decisions", "Everything except display preferences"],
            key="reset_scope",
        )
        ok = st.checkbox("I understand this cannot be undone from the app", key="reset_confirm")
        if st.button("Reset now", type="primary", disabled=not ok, key="reset_go"):
            # A decision carries the name of the person who made it, so it is copied
            # aside before it is dropped rather than simply deleted.
            if STATE_FILE.exists():
                (DATA / "backups").mkdir(exist_ok=True)
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                (DATA / "backups" / f"assessments-{stamp}.json").write_text(STATE_FILE.read_text())
            fresh = {"org": "", "reviewer": "", "scan_folder": "",
                     "evidence": {}, "ai": {}, "ai_status": {}, "decisions": {},
                     "blind": {}, "challenge": {}, "challenge2": {},
                     "dark": S.get("dark"), "guide": S.get("guide", True)}
            if scope_reset.startswith("Assessments"):
                for k in ("org", "reviewer", "scan_folder"):
                    fresh[k] = S.get(k, "")
            st.session_state.s = fresh
            for k in ("index", "signals", "gap_rows", "sel", "lifecycle_view"):
                st.session_state.pop(k, None)
            save_state()
            st.rerun()


@st.cache_data(show_spinner=False)
def _load(path: str):
    return load_controls(path)


controls = ({} if src is None else _load(str(src)) if isinstance(src, Path) else load_controls(src))


@st.cache_data(show_spinner=False)
def _load_plays(path: str):
    return load_plays(path)


plays = ([] if src is None else _load_plays(str(src)) if isinstance(src, Path) else load_plays(src))
in_scope = [c for lib, rows in controls.items() if scope.get(lib) for c in rows]
by_key = {c.key: c for c in in_scope}

st.markdown(
    '<div class="wb-head">'
    '<div class="wb-t">AI governance readiness workbench</div>'
    '<div class="wb-s">Evidence in, sufficiency rating proposed by AI, decision recorded by a named '
    'reviewer. Ratings are not a determination of regulatory compliance.</div>'
    '</div>', unsafe_allow_html=True)


def _tour_context() -> dict:
    """State the guide reads. Every value is observed, never inferred, and the guide
    never calls the assessor — a rule that reads state cannot be wrong about whether
    a folder has been indexed."""
    idx_ = st.session_state.get("index")
    try:
        bundles_ = list_bundles()
    except Exception:  # noqa: BLE001 — the guide must never take the app down
        bundles_ = []
    fails = incon = 0
    if bundles_:
        try:
            head = bundles_[0]
            latest = load_bundle(head["path"]) if isinstance(head, dict) and "path" in head else head
            for r in (latest or {}).get("results", []):
                fails += r.get("machine_verdict") == "FAIL"
                incon += r.get("machine_verdict") == "NOT_TESTABLE"
        except Exception:  # noqa: BLE001
            pass
    return {
        "controls": bool(in_scope),
        "reviewer": S.get("reviewer", ""),
        "indexed_docs": len(getattr(idx_, "chunks", []) or []),
        "ai_proposals": len(S.get("ai", {})),
        "decisions": len(S.get("decisions", {})),
        "bundles": len(bundles_),
        "open_failures": fails,
        "open_inconclusive": incon,
        "lifecycle_viewed": bool(st.session_state.get("lifecycle_view")),
    }


if S.get("guide", True):
    tour.render(_tour_context(), show_all=True)

tab_s, tab_c, tab_a, tab_r, tab_b, tab_h, tab_l = st.tabs(["Scan", "Controls", "Assess", "Report", "Audit", "History", "Lifecycle"])
VCOL = {"PASS": "#2F7D5B", "FAIL": "#A23B3B", "NOT_TESTABLE": "#6B7A8A"}
vpill = lambda v: f'<span class="pill" style="background:{VCOL[v]}">{v}</span>'


# ---------- Scan ----------
with tab_s:
    if not controls:
        st.info("Load a playbook workbook to use this tab.")
    else:
        # ================================================================
        # WB-037 — Evidence workspace, restructured around the choice a first-time user
        # actually faces rather than around the widgets the pipeline needs.
        #
        # What was wrong with the previous layout:
        #   - the demo was two widgets pretending to be one. A selectbox reading "Off" looks
        #     like a toggle, so choosing "Mixed" and pressing Index did nothing, because the
        #     selectbox was only an argument to the button beside it.
        #   - the match threshold had the visual weight of a primary action while governing a
        #     step (matching) that has no button and is never seen to happen.
        #   - numbering started at the fifth element on the page and step 2 did not exist until
        #     step 1 succeeded, so the shape of the journey was invisible.
        #   - the primary button was disabled with no reason shown.
        #   - the caption said the scan was optional while the page presented itself as the
        #     mandatory landing tab.
        #
        # Nothing about the pipeline changes here. index_folder, match_controls, build_evidence
        # and propose are called exactly as before, and min_ratio is still recorded on every
        # evidence bundle so a proposal stays reproducible.
        # ================================================================
        st.subheader("Evidence workspace")

        route = st.radio(
            "How do you want to start?",
            ["I have an evidence folder", "Try it with synthetic evidence", "Assess one control directly"],
            horizontal=True, key="scan_route",
            help="A folder scan is optional. It is a way of getting candidate evidence in front "
                 "of many controls at once, not a required first step.",
        )

        folder = ""
        if route == "Assess one control directly":
            st.info("Go to the **Assess** tab, pick a control, and paste or upload its evidence there. "
                    "Nothing on this tab is needed for that.")

        elif route == "Try it with synthetic evidence":
            st.caption("Generates a synthetic document for every one of the 195 control contracts, "
                       "into a temporary folder outside this repository.")
            scenario_label = st.radio(
                "Which pack", ["Mixed — full, partial and none", "All complete"],
                horizontal=True, key="demo_scenario",
                label_visibility="collapsed",
            )
            if st.button("Generate and load synthetic evidence", type="primary", disabled=not controls):
                scenario = "full" if scenario_label == "All complete" else "mixed"
                demo_dir = generate_demo_evidence(scenario=scenario)
                st.session_state.demo_evidence_dir = str(demo_dir)
                st.session_state.scan_folder = str(demo_dir)
                S["scan_folder"] = str(demo_dir)
                save_state()
                st.rerun()
            folder = st.session_state.get("demo_evidence_dir", "")
            if folder:
                st.success(f"Synthetic pack loaded: `{folder}`")
            # The honest caveat belongs on the screen, not only in the release notes: this pack is
            # generated FROM the control contracts, so it reuses the requirement wording almost
            # verbatim. Retrieval and assessment both look better against it than against real
            # documents, and the mixed pack is roughly 60% authored as `full`.
            st.warning("This pack is generated from the control contracts themselves, so it reuses "
                       "the requirement wording. Retrieval and assessment will look better here than "
                       "on real documents. Use it to learn the workflow, never as a measurement.")

        else:
            # WB-038: three ways to name a folder, because none works everywhere. The in-app
            # browser always works. The native dialog only works when the browser and this
            # process are on the same machine — opened by a remote server it blocks on a
            # dialog nobody can see — so fp.local_runtime() gates it. Pasting stays, because
            # it is still the fastest route for anyone who already has the path.
            st.session_state.pop("demo_evidence_dir", None)
            S.setdefault("recent_folders", [])

            def _use_folder(path: str):
                S["scan_folder"] = path
                S["recent_folders"] = fp.remember(S.get("recent_folders", []), path)
                st.session_state.browse_at = path
                save_state()

            folder = st.text_input("Evidence folder", S.get("scan_folder", ""),
                                   placeholder="/Users/you/Documents/ai-governance-evidence")
            if folder != S.get("scan_folder", ""):
                S["scan_folder"] = folder

            b1, b2 = st.columns([1, 1])
            if fp.native_available(folder or None):
                if b1.button("Browse…", key="btn_native_pick"):
                    chosen, err = fp.pick_folder_native(folder or str(fp.home()))
                    if err:
                        st.warning(err)
                    elif chosen:
                        _use_folder(chosen)
                        st.rerun()
                    # chosen and err both None means cancelled - not an error, say nothing
            browsing = b2.toggle("Browse from here", key="browse_open",
                                 help="Walk the filesystem inside the app. Works whether the "
                                      "workbench runs on this machine or on a server.")

            if browsing:
                at = st.session_state.get("browse_at") or folder or str(fp.home())
                if fp.safe_path(at) is None:
                    at = str(fp.home())
                crumbs = fp.breadcrumbs(at)
                cols = st.columns(len(crumbs) + 1)
                up = fp.parent_of(at)
                if cols[0].button("↑", key="browse_up", disabled=up is None,
                                  help="Up one level"):
                    st.session_state.browse_at = up
                    st.rerun()
                for i, (label, target) in enumerate(crumbs, start=1):
                    if cols[i].button(label or "/", key=f"crumb_{i}"):
                        st.session_state.browse_at = target
                        st.rerun()

                subs = fp.list_subdirs(at, show_hidden=st.session_state.get("browse_hidden", False))
                st.caption(f"`{at}` — {len(subs)} subfolder(s)")
                if subs:
                    pick = st.selectbox("Open a subfolder", ["—"] + subs, key="browse_pick")
                    if pick != "—":
                        st.session_state.browse_at = str(Path(at) / pick)
                        st.session_state.browse_pick = "—"
                        st.rerun()
                else:
                    st.caption("No subfolders here, or this folder cannot be read. "
                               "It can still be selected.")
                st.checkbox("Show hidden folders", key="browse_hidden")
                if st.button(f"Use this folder", type="primary", key="browse_use"):
                    _use_folder(at)
                    st.rerun()

            recent = [p for p in S.get("recent_folders", []) if p != folder]
            if recent:
                r = st.selectbox("Recent folders", ["—"] + recent, key="recent_pick")
                if r != "—":
                    _use_folder(r)
                    st.rerun()

            if not folder:
                st.caption("Browse above, or paste the full path. In Finder: right-click the "
                           "folder, hold Option, then Copy as Pathname.")
            elif fp.safe_path(folder) is None:
                st.caption("That path does not point at a readable directory yet.")

        self_scan = self_scan_reason(folder) if folder else None
        if self_scan:
            st.error(self_scan)

        # ---- the three steps, always visible, each carrying its own reason when unavailable ----
        st.markdown("---")
        idx = st.session_state.get("index")
        sigs = st.session_state.get("signals", [])
        s1, s2, s3 = st.columns(3)

        with s1:
            st.markdown("**1 · Index**")
            st.caption("Read every file in the folder and split it into searchable passages.")
            blocked = (not folder) or bool(self_scan)
            do_index = st.button("Index evidence", type="primary", disabled=blocked, key="btn_index")
            if blocked:
                st.caption("Needs an evidence folder above." if not folder
                           else "Blocked — see the message above.")

        with s2:
            st.markdown("**2 · Match and assess**")
            st.caption("Find each control's best passages, then ask the assessor for a proposal "
                       "on every control that matched.")
            if not idx:
                st.caption("Available once evidence is indexed.")

        with s3:
            st.markdown("**3 · Review**")
            st.caption("Proposals are stored **hidden**. On the Assess tab each one stays "
                       "invisible until you have recorded your own reading of the evidence.")

        with st.expander("Advanced — retrieval settings"):
            st.caption("Defaults are fine for a first run. These change which passages a control is "
                       "assessed on, so the value in force is recorded with every assessment made "
                       "under it and a stored proposal stays reproducible.")
            min_ratio = st.slider("Match threshold", 0.0, 1.0, MIN_RATIO, 0.05, key="min_ratio",
                                  help="How close to a control's best-matching passage another passage "
                                       "must score to be included as evidence.")
            st.caption(f"Passages scoring below **{min_ratio:.0%}** of each control's own best match are "
                       "excluded. Relative to the best match, not an absolute score, so one value means "
                       "the same thing across libraries with differently-worded controls. "
                       "Lower finds more and noisier. Higher is stricter and can leave a control with "
                       "no evidence at all — which is not the same finding as a control that has none.")

        if do_index:
            if not os.path.isdir(folder):
                st.error("Folder not found. Paste the full path (in Finder: right-click the folder, "
                         "hold Option, Copy as Pathname).")
            else:
                bar = st.progress(0.0, "Reading files…")
                try:
                    st.session_state.index, st.session_state.signals = index_folder(
                        folder, lambda n, t, name: bar.progress((n + 1) / max(t, 1), f"Reading {name}"))
                except SelfScanError as e:
                    bar.empty()
                    st.error(str(e))
                    st.stop()
                bar.empty()
                chunks = st.session_state.index.chunks
                files = len({c.path for c in chunks})
                st.success(f"Indexed {files} documents into {len(chunks)} passages. "
                           f"Found {len(st.session_state.signals)} environment signals.")
                idx = st.session_state.index
                sigs = st.session_state.signals

        if sigs:
            with st.expander(f"Environment signals ({len(sigs)})"):
                st.caption("Configuration and infrastructure files that point at a control without "
                           "being evidence for it. They are shown to the assessor as context.")
                st.dataframe([{"File": s_.path, "Kind": s_.kind, "What to check": s_.hint,
                               "Relevant controls": ", ".join(s_.controls)} for s_ in sigs],
                             width="stretch", hide_index=True)

        if idx:
            matches = match_controls(idx, in_scope, min_ratio=min_ratio)
            found = [c for c in in_scope if c.key in matches]
            st.markdown("---")
            m1, m2 = st.columns([2, 3])
            m1.metric("Controls with candidate evidence", f"{len(found)} of {len(in_scope)}")
            m2.caption(f"At a match threshold of {min_ratio:.0%}. "
                       f"**{len(in_scope) - len(found)}** in-scope controls matched no document. "
                       "Move the threshold and this number changes — a control with no matching "
                       "document is not the same finding as one whose evidence the threshold excluded.")
            with st.expander("Preview matches"):
                st.dataframe([{"Control": f"{c.id} {c.title}", "Library": c.lib,
                               "Best match": matches[c.key][0][0].label,
                               "Score": round(matches[c.key][0][1], 1),
                               "Passages kept": len(matches[c.key]),
                               "Signals": len(signals_for(c, sigs))} for c in found],
                             width="stretch", hide_index=True)
            only_new = st.checkbox("Skip controls that already have a recorded decision", True)
            todo = [c for c in found if not (only_new and c.key in S["decisions"])]
            if st.button(f"2 · Assess {len(todo)} matched controls", type="primary",
                         disabled=not todo, key="btn_assess"):
                bar = st.progress(0.0)
                fails = 0
                for n, c in enumerate(todo):
                    bar.progress(n / len(todo), f"Assessing {c.id} ({n + 1}/{len(todo)})")
                    S["evidence"][c.key] = build_evidence(c, matches[c.key], sigs)
                    # WB-023: the threshold changes which passages a control was assessed on, so it
                    # belongs with the evidence. Without it a stored proposal cannot be reproduced.
                    S["evidence"][c.key]["retrieval"] = {"min_ratio": min_ratio, "min_score": MIN_SCORE, "k": TOP_K}
                    S["ai"][c.key] = propose(c, S["evidence"][c.key])
                    fails += S["ai"][c.key].get("model") == "error"
                    S["decisions"].pop(c.key, None)
                    save_state()
                bar.empty()
                st.success(f"Assessed {len(todo)} controls ({fails} errors). **Nothing is recorded yet.** "
                           "Go to the Assess tab — each proposal stays hidden until you have recorded "
                           "your own reading of the evidence.")

        # gap analysis
        if S["ai"] or S["decisions"]:
            st.subheader("Gap analysis")
            rows_ = gap_analysis(in_scope, S["ai"], S["decisions"])
            st.caption(f"{len(rows_)} controls below full. Proposed ratings are the assessor's; only reviewed ones are recorded.")
            st.dataframe([{k: v for k, v in r.items() if k != "Priority"} for r in rows_], width="stretch", hide_index=True, height=400)
            st.session_state.gap_rows = rows_

# ---------- Controls ----------
with tab_c:
    if not controls:
        st.info("Load a playbook workbook to use this tab.")
    else:
        q = st.text_input("Search controls", "")
        rows = [c for c in in_scope if not q or q.lower() in f"{c.id} {c.title} {c.req}".lower()]
        st.write(f"{len(rows)} of {len(in_scope)} controls in scope")
        for c in rows:
            d = S["decisions"].get(c.key)
            state = d["sufficiency"] if d else ("pending" if c.key in S["ai"] or c.key in S.get("blind", {}) else None)
            has_ev = bool(S["evidence"].get(c.key, {}).get("text") or S["evidence"].get(c.key, {}).get("file_name"))
            cols = st.columns([1, 6, 2])
            cols[0].markdown(pill(state if state != "pending" else "to review") if state else "", unsafe_allow_html=True)
            cols[1].markdown(f"**{c.id}** {c.title}  \n<small>{c.lib} · {c.owner}</small>", unsafe_allow_html=True)
            if cols[2].button("Open", key=f"open_{c.key}"):
                st.session_state.sel = c.key
                st.rerun()
            if not state and has_ev:
                cols[0].caption("evidence added")

# ---------- Assess ----------
with tab_a:
    if not controls:
        st.info("Load a playbook workbook to use this tab.")
    else:
        sel = st.selectbox("Control", options=[c.key for c in in_scope], index=[c.key for c in in_scope].index(st.session_state.get("sel")) if st.session_state.get("sel") in by_key else 0,
                           format_func=lambda k: f"{by_key[k].id} {by_key[k].title[:70]}  ({by_key[k].lib})")
        st.session_state.sel = sel
        c = by_key[sel]
        st.subheader(f"{c.id} {c.title}")
        st.caption(f"{c.lib} · owner: {c.owner}")
        st.markdown(f'<div class="req">{c.req}</div>', unsafe_allow_html=True)
        if c.maps:
            st.caption("Cross-mapped: " + c.maps)

        _ev0 = S["evidence"].get(c.key, {})
        _has0 = bool(_ev0.get("text") or _ev0.get("file_path"))
        _bl0 = S.get("blind", {}).get(c.key)
        _ch0 = S.get("challenge", {}).get(c.key)
        _d0 = S["decisions"].get(c.key)
        _ai0 = S["ai"].get(c.key)
        _ai_status0 = S.get("ai_status", {}).get(c.key) if isinstance(S.get("ai_status"), dict) else None
        st.markdown(stages(
            ("Evidence", "done" if _has0 else "now"),
            ("Your reading", "done" if _bl0 else ("now" if _has0 else "wait")),
            ("AI assessment", "done" if (_ai0 and not is_error(_ai0)) else ("now" if _bl0 else "wait")),
            ("Compare", "done" if (_bl0 and _ai0 and not is_error(_ai0)) else ("now" if _bl0 and _ai0 else "wait")),
            ("Challenge / decision", "done" if (_ch0 or _d0) else ("now" if _bl0 and _ai0 else "wait")),
        ), unsafe_allow_html=True)
        if S.get("guide", True):
            st.caption("Save your independent reading first. Saving it automatically triggers the AI assessment; "
                       "the proposal remains hidden until your reading is recorded. The challenger is optional "
                       "and can only ask questions — it cannot rate and cannot agree.")

        ev = S["evidence"].setdefault(c.key, {})
        ev["text"] = st.text_area("Evidence", ev.get("text", ""), height=160,
                                  placeholder="Paste policy extracts, procedure text, log snippets, inventory records, or describe the artefact.")
        f = st.file_uploader("Attach file (PDF, txt, md, csv, log)", type=["pdf", "txt", "md", "csv", "log", "json"], key=f"file_{c.key}")
        if f is not None:
            if f.type == "application/pdf":
                (DATA / "evidence").mkdir(exist_ok=True)
                p = DATA / "evidence" / f"{c.key.replace('::', '_').replace('/', '-')}_{f.name}"
                p.write_bytes(f.getvalue())
                ev["file_name"], ev["file_path"] = f.name, str(p)
            else:
                ev["text"] = (ev["text"] + "\n\n" if ev["text"] else "") + f"[{f.name}]\n" + f.getvalue().decode(errors="ignore")[:20000]
        if ev.get("file_name"):
            st.caption(f"Attached: {ev['file_name']}")
        if ev.get("auto"):
            st.caption("Evidence located by folder scan from: " + "; ".join(Path(p_).name for p_ in ev.get("sources", [])))

        S.setdefault("blind", {})
        S.setdefault("challenge", {})
        S.setdefault("challenge2", {})
        blind = S["blind"].get(c.key)
        has_ev = bool(ev.get("text") or ev.get("file_path"))

        reuse = st.selectbox("Reuse this evidence on another control", [""] + [k for k in by_key if k != c.key],
                             format_func=lambda k: "—" if not k else f"{by_key[k].id} {by_key[k].title[:50]}")
        if st.button("Copy evidence", disabled=not reuse):
            S["evidence"][reuse] = dict(ev)
            st.toast("Evidence copied. Cross-mapped controls still need their own assessment.")
        save_state()

        # ================================================================
        # Independent review workflow
        #
        # The model may compute a proposal before the reviewer submits their reading
        # (for example from the Scan tab), but the proposal is never shown until the
        # reviewer has saved an independent reading. On save, an on-demand assessment
        # is triggered automatically if one does not already exist. This keeps the blind
        # display gate while removing the redundant "Assess with AI" button.
        # ================================================================

        # ---------------- Phase 1 — the reviewer's own reading ----------------
        if not blind:
            st.markdown("### Your reading")
            st.caption("Recorded before anything from a model is shown. Decide each element of the "
                       "requirement from the evidence alone, for this control alone.")
            _levels = ["none", "partial", "full"]
            k1, k2 = st.columns(2)
            # Opens unset. The argument already written below for the error case — that a
            # widget must not manufacture an opinion that looks like its default — holds
            # for every case, not only the one where the call failed.
            b_suff = k1.selectbox("Sufficiency", ["—"] + _levels, index=0, key=f"bs_{c.key}")
            _cap = {"—": 5, "none": 1, "partial": 3, "full": 5}[b_suff]
            b_mat = k2.selectbox("Maturity", ["—"] + list(range(1, _cap + 1)), index=0, key=f"bm_{c.key}",
                                 help="1 ad hoc, 2 documented, 3 implemented, 4 measured, 5 optimised. "
                                      "Sufficiency caps maturity, as it does in eval/label.py.")
            # WB-031 — per-element verdicts, so the later comparison has something to compare.
            # Every element opens unset and an unset element is never counted as agreement by
            # compare(). That is deliberate: pre-selecting a verdict is the same defect as the
            # old "Accept proposal" default, which produced 47 accepts to 4 amends because
            # agreement was one click and disagreement was work.
            _elements = elements_for(c)
            _verdict_labels = {"—": "unset", "met": "met", "not evidenced": "not_evidenced", "n/a": "not_applicable"}
            _el_state = {}
            if _elements:
                st.markdown("**Element by element**")
                st.caption(f"{len(_elements)} elements from the governed contract for this control. "
                           "Leave an element unset if this evidence does not let you decide it — "
                           "unset is recorded as unset and is never read as agreement.")
                for _e in _elements:
                    _c1, _c2 = st.columns([0.62, 0.38])
                    _c1.markdown(f'<div style="padding-top:.45rem"><code>{_e["id"]}</code> {_e["text"]}</div>',
                                 unsafe_allow_html=True)
                    _pick = _c2.radio(_e["id"], list(_verdict_labels), index=0, horizontal=True,
                                      key=f"bev_{c.key}_{_e['id']}", label_visibility="collapsed")
                    _el_state[_e["id"]] = _verdict_labels[_pick]
            else:
                st.caption("This control has no contract elements, so the element comparison is "
                           "unavailable for it and only the ratings will be compared.")

            b_reason = st.text_area("Which rule or missing element decided it?", key=f"br_{c.key}",
                                    placeholder="Name the element the evidence satisfies, or the one it does not show.")
            b_amb = st.checkbox("Ambiguous — cannot be decided from this evidence", key=f"ba_{c.key}")

            if st.button("Save my reading", type="primary", disabled=not has_ev):
                err = reason_error(b_reason, rating=b_suff)
                if not S.get("reviewer", "").strip():
                    st.error("Set a reviewer name in the sidebar. A reading needs an attributable person.")
                elif b_suff == "—" or b_mat == "—":
                    st.error("Choose a sufficiency and a maturity.")
                elif err:
                    st.error(err)
                else:
                    S["blind"][c.key] = {
                        "sufficiency": b_suff, "maturity": int(b_mat), "reason": b_reason.strip(),
                        "ambiguous": b_amb, "labelled_by": S["reviewer"].strip(),
                        "labelled_on": dt.datetime.now().isoformat(timespec="seconds"),
                        "element_verdicts": [{"element_id": k_, "status": v_} for k_, v_ in _el_state.items()],
                    }
                    # Saving My Read automatically starts the independent AI assessment if needed.
                    # The model receives the control/evidence contract only; the reviewer's read is
                    # never passed to propose(), so the blind record remains genuine.
                    if not S["ai"].get(c.key) or is_error(S["ai"].get(c.key)):
                        S.setdefault("ai_status", {})[c.key] = "running"
                        save_state()
                        with st.spinner("AI is independently assessing the evidence against the governed elements…"):
                            try:
                                pdf = Path(ev["file_path"]).read_bytes() if ev.get("file_path") else None
                                S["ai"][c.key] = propose(c, ev, pdf)
                                S["ai_status"][c.key] = "error" if is_error(S["ai"][c.key]) else "ready"
                                S["decisions"].pop(c.key, None)
                            except Exception as e:
                                S["ai"][c.key] = {"model": "error", "error": str(e)}
                                S["ai_status"][c.key] = "error"
                    else:
                        S.setdefault("ai_status", {})[c.key] = "ready" if not is_error(S["ai"][c.key]) else "error"
                    save_state()
                    st.rerun()
            if not has_ev:
                st.caption("Add evidence above before recording a reading.")

            st.markdown("")
            st.info("Save your reading to trigger an independent AI assessment automatically. "
                    "The AI reads the evidence and governed control contract; it does not receive your reading.")
            if S["ai"].get(c.key):
                st.caption("AI assessment is prepared but remains hidden until your reading is saved.")

        # ---------------- Phases 2 and 3 ----------------
        else:
            st.markdown("### Your reading — recorded")
            st.markdown(f'{pill(blind["sufficiency"])} &nbsp; maturity {blind["maturity"]}/5 &nbsp; '
                        f'<small>{blind["labelled_by"]}, {blind["labelled_on"][:16].replace("T", " ")}'
                        f'{" · marked ambiguous" if blind.get("ambiguous") else ""}</small>',
                        unsafe_allow_html=True)
            st.caption(blind["reason"])
            if st.button("Reopen my reading", help="Discards this reading and any challenge on it. "
                                                   "Nothing has been written to the playbook yet."):
                S["blind"].pop(c.key, None)
                S["challenge"].pop(c.key, None)
                S.get("challenge2", {}).pop(c.key, None)
                S.get("compare", {}).pop(c.key, None)
                save_state(); st.rerun()

            # -------- Phase 2 — challenge --------
            ch = S["challenge"].get(c.key)
            if not ch and st.button("Challenge my reading"):
                with st.spinner("Challenging…"):
                    try:
                        # challenge() takes the evidence text and raises on transport or parse
                        # failure. A challenger that did not run must never be indistinguishable
                        # from one that ran and found nothing to ask.
                        out = run_challenge(c, ev.get("text", ""), blind)
                        ch_record = {
                            "challenger_model": out.get("model"),
                            "reasoning_schema": out.get("reasoning_schema"),
                            "overall_reasoning": out.get("overall_reasoning", ""),
                            "challenges": out.get("challenges") or [],
                            "sharpest": out.get("sharpest", ""),
                            "unaddressed": out.get("unaddressed") or [],
                            "knowledge": out.get("knowledge") or [],
                            "shown_on": dt.datetime.now().isoformat(timespec="seconds"),
                            "shown_to": S["reviewer"].strip(),
                            "changed": False,
                        }
                        dossier = create_dossier(
                            control_id=c.key, control_title=c.title, reviewer=S["reviewer"],
                            blind=blind, challenges=ch_record["challenges"],
                            challenger_model=ch_record["challenger_model"],
                            knowledge=ch_record["knowledge"], reasoning_schema=ch_record["reasoning_schema"],
                            assessment_id=(S.get("assessment_identity") or {}).get("assessment_id"),
                        )
                        append_dossier(dossier)
                        ch_record["dossier"] = dossier
                        S["challenge"][c.key] = ch_record
                        save_state(); st.rerun()
                    except Exception as e:
                        st.error(f"The challenger failed ({type(e).__name__}) — nothing was recorded "
                                 f"and your reading stands unchallenged. {e}")

            if ch:
                st.markdown(f'### Challenge &nbsp;<small>{ch.get("challenger_model","?")} — questions only, '
                            f'it cannot rate and cannot agree</small>', unsafe_allow_html=True)
                if ch.get("overall_reasoning"):
                    st.markdown("**Why this is being challenged**")
                    st.write(ch["overall_reasoning"])
                if ch.get("sharpest"):
                    st.markdown(f'**Answer first:** {ch["sharpest"]}')
                outcome = ch.get("challenge_outcome")
                if outcome:
                    st.caption(f"Challenge outcome: {outcome}")
                if ch.get("knowledge"):
                    st.caption("Governance knowledge consulted: " + ", ".join(m.get("memory_id", "?") for m in ch["knowledge"]))
                dossier = ch.get("dossier") or {}
                responses_by_no = {x.get("challenge_no"): x.get("response") for x in dossier.get("challenges", [])}
                for i_, q_ in enumerate(ch.get("challenges", []), 1):
                    st.markdown(f"**Challenge {i_} — {str(q_.get('severity','medium')).upper()}**")
                    st.markdown(f"**Observation:** {q_.get('observation','')}")
                    st.markdown("**Evidence basis**")
                    for e_ in q_.get("evidence_basis", []): st.markdown(f"- {e_}")
                    st.markdown("**Requirement basis**")
                    for r_ in q_.get("requirement_basis", []): st.markdown(f"- {r_}")
                    if q_.get("knowledge_basis"):
                        st.markdown("**Knowledge / precedent**")
                        for k_ in q_["knowledge_basis"]: st.markdown(f"- {k_.get('memory_id')} — {k_.get('role','advisory')}")
                    st.markdown(f"**Inference:** {q_.get('inference','')}")
                    st.markdown(f"**Challenge:** {q_.get('challenge','')}")
                    ct_ = q_.get("claim_test") or {}
                    if ct_:
                        st.markdown("**Claim / rebuttal test**")
                        st.write(f"**Reviewer claim:** {ct_.get('claim','')}")
                        st.write(f"**Fact actually establishes:** {ct_.get('fact_meaning','')}")
                        st.write(f"**Rebuttal:** {ct_.get('rebuttal','')}")
                        st.write(f"**Rebuttal strength:** `{q_.get('challenge_strength', ct_.get('rebuttal_strength','weak'))}`")
                    fp_ = q_.get("factual_pointer") or {}
                    if fp_:
                        st.markdown("**Factual pointer**")
                        st.code(f"{fp_.get('source','?')} · {fp_.get('locator','?')}\n\"{fp_.get('quote','')}\"")
                        st.caption(fp_.get("what_it_supports", ""))
                    rp_ = q_.get("requirement_pointer") or {}
                    if rp_:
                        st.markdown("**Requirement pointer**")
                        st.code(f"requirements/mas.yaml · {rp_.get('locator','?')}\n{rp_.get('element_id','?')}: {rp_.get('text','?')}")
                    if q_.get("risk_to_address"):
                        st.markdown(f"**Control risk to address:** {q_.get('risk_to_address')}")
                    if q_.get("resolution_pointer"):
                        st.markdown(f"**What resolves the risk:** {q_.get('resolution_pointer')}")
                    st.markdown(f"**Recommended action:** `{q_.get('recommended_action','answer')}` · confidence: `{q_.get('confidence','medium')}`")
                    existing = responses_by_no.get(i_)
                    if existing:
                        st.success(f"Response: **{existing.get('disposition','?')}** — {existing.get('note','')}")
                    else:
                        st.markdown("**Reviewer response**")
                        rcols = st.columns(3)
                        disp_label = rcols[0].selectbox("Disposition", ["accept", "reject", "evidence_provided", "escalate"], key=f"cd_disp_{c.key}_{i_}",
                            format_func=lambda x: {"accept":"Accept challenge", "reject":"Reject challenge", "evidence_provided":"Provide evidence", "escalate":"Escalate"}[x])
                        resp_note = st.text_area("Response / reasoning", key=f"cd_note_{c.key}_{i_}",
                            placeholder="Explain why the challenge is accepted/rejected, or what evidence was provided.")
                        resp_ev = st.text_area("Evidence supplied (optional)", key=f"cd_ev_{c.key}_{i_}",
                            placeholder="Paste the specific evidence that answers the challenge.")
                        if st.button("Record challenge response", key=f"cd_save_{c.key}_{i_}"):
                            try:
                                updated = respond_to_challenge(dossier, i_, response=disp_label, reviewer=S["reviewer"],
                                    note=resp_note, evidence=[resp_ev] if resp_ev.strip() else [])
                                append_dossier(updated)
                                ch["dossier"] = updated
                                save_state(); st.rerun()
                            except ValueError as e:
                                st.error(str(e))
                for u_ in ch.get("unaddressed", []):
                    st.warning(f"Requirement element your reason never mentions: {u_}")
                dstatus = (ch.get("dossier") or {}).get("status", "open")
                st.caption(f"Challenge dossier: {(ch.get('dossier') or {}).get('dossier_id','—')} · status: {dstatus}")
                st.info("A challenger attacks sound labels too. Respond to each challenge. The response "
                        "is retained in the append-only dossier; it does not itself change the rating.")

            # -------- Phase 3 — the assessor (automatic after My Read) --------
            _ai_status = S.setdefault("ai_status", {}).get(c.key)
            if _ai_status == "running":
                st.info("AI assessment is running independently against the evidence and governed elements…")
            elif _ai_status == "error" or (S.get("ai", {}).get(c.key) and is_error(S["ai"][c.key])):
                err_a = S.get("ai", {}).get(c.key, {}).get("error", "")
                st.error("The automatic AI assessment failed — no AI rating was produced. " + err_a)
                st.caption("Your saved reading remains intact. Resolve the model/runtime issue and reopen/save the reading to retry.")
            elif S.get("ai", {}).get(c.key):
                st.success("AI assessment is ready. It was computed independently from your reading and is now available for comparison.")
                st.caption("The AI assessed the evidence against the governed control elements; it did not receive or use your reading.")

            save_state()

            a = S["ai"].get(c.key)
            if a:
                st.markdown("### AI proposal")
                if is_error(a):
                    # WB-021: the call never returned. There is no rating to show, and one must not be
                    # invented here either — the reviewer form below stays available because a person
                    # can still read the evidence and decide.
                    st.warning("The assessor call failed for this control, so no rating was proposed. "
                               "This is not a finding and nothing has been recorded. "
                               "Re-run the assessment, or record your own decision below.")
                    if a.get("error"):
                        st.caption(a["error"])
                else:
                    st.markdown(f'{pill(a["sufficiency"])} &nbsp; maturity {a["proposedMaturity"]}/5 &nbsp; <small>{a.get("model","")}</small>', unsafe_allow_html=True)
                    st.write(a.get("rationale", ""))
                    if a.get("excerpt"):
                        st.markdown(f"> *{a['excerpt']}*")
                    for g in a.get("gaps", []):
                        st.markdown(f"- {g}")
                    if a.get("remediation"):
                        st.markdown("**Suggested actions**")
                        for r_ in a["remediation"]:
                            st.markdown(f"- {r_}")
                    for fl in a.get("flags", []):
                        st.warning(f"Validation: {fl}")
                    if a.get("reviewerPrompt"):
                        st.info(f"Before accepting, ask: {a['reviewerPrompt']}")
                    if a.get("sufficiency") != blind["sufficiency"]:
                        st.caption(f"The proposal differs from your reading ({blind['sufficiency']}). "
                                   "A difference is not a correction — check it against the requirement "
                                   "and the evidence before it moves you.")

            # ================================================================
            # WB-031 Phase 4 — compare. Deterministic, no model call.
            #
            # The rating comparison that used to live in the caption above is a comparison of
            # two words. This compares the two reads where the reasoning is: element by element,
            # against the same canonical contract both sides were given. An element neither side
            # decided is excluded from the compared population rather than counted as agreement,
            # and a failed assessor call is NOT_COMPARABLE rather than a silent pass.
            # ================================================================
            diff = None
            S.setdefault("compare", {})
            if a:
                diff = compare_reads(blind, a, c)
                S["compare"][c.key] = diff
                st.markdown("### Compare")
                st.caption(compare_headline(diff))
                if diff.get("comparable") and diff.get("rows"):
                    _sym = {"met": "met", "not_evidenced": "not evidenced",
                            "not_applicable": "n/a", "unset": "—"}
                    _rows = ["| Element | You | Assessor | |", "|---|---|---|---|"]
                    for r_ in diff["rows"]:
                        mark = ("✓" if r_["agree"] else "✗") if r_["compared"] else "·"
                        _rows.append(f"| `{r_['element_id']}` {r_['text'][:88]} | {_sym[r_['reviewer']]} "
                                     f"| {_sym[r_['ai']]} | {mark} |")
                    st.markdown("\n".join(_rows))
                    _s = diff["summary"]
                    if _s["reviewer_unset"] or _s["assessor_unset"]:
                        st.caption(f"Not compared: {_s['reviewer_unset']} element(s) you left unset, "
                                   f"{_s['assessor_unset']} the assessor returned no verdict on. "
                                   "These are excluded from the agreement count, not counted as agreement.")
                    if _s["agreement_rate"] is None and _s["n_compared"]:
                        st.caption(f"Only {_s['n_compared']} element(s) were decided on both sides, below the "
                                   f"floor of {_s['min_compared']} — no agreement rate is reported for this control.")
                    for r_ in diff["rows"]:
                        if r_["compared"] and not r_["agree"] and r_.get("ai_excerpt"):
                            st.caption(f"{r_['element_id']} — the assessor rests its verdict on: \"{r_['ai_excerpt'][:200]}\"")

                # -------- Phase 4b — second challenge pass, scoped to the disagreement --------
                ch2 = S["challenge2"].get(c.key)
                if diff.get("disagreements") and not ch2:
                    st.caption("The challenger can now attack the disagreement rather than your reading. "
                               "It may find against the assessor as readily as against you, and it still "
                               "cannot rate and cannot agree.")
                    if st.button(f"Challenge the disagreement ({len(diff['disagreements'])} element(s))",
                                 key=f"ch2_{c.key}"):
                        with st.spinner("Challenging the disagreement…"):
                            try:
                                out2 = run_challenge2(c, ev.get("text", ""), blind, a, diff)
                                S["challenge2"][c.key] = {
                                    "challenger_model": out2.get("model"),
                                    "reasoning_schema": out2.get("reasoning_schema"),
                                    "overall_reasoning": out2.get("overall_reasoning", ""),
                                    "challenges": out2.get("challenges") or [],
                                    "sharpest": out2.get("sharpest", ""),
                                    "scope_elements": out2.get("scope_elements") or [],
                                    "out_of_scope_dropped": out2.get("out_of_scope_dropped", 0),
                                    "supports_tally": out2.get("supports_tally") or {},
                                    "challenge_outcome": out2.get("challenge_outcome"),
                                    "diff_sha": out2.get("diff_sha"),
                                    "at": dt.datetime.now().isoformat(timespec="seconds"),
                                }
                                save_state(); st.rerun()
                            except Exception as e:
                                # Same rule as pass 1: a challenger that did not run must never be
                                # indistinguishable from one that ran and found nothing.
                                st.error(f"The disagreement challenge failed ({type(e).__name__}) — nothing was "
                                         f"recorded and the disagreement stands unexamined. {e}")

                ch2 = S["challenge2"].get(c.key)
                if ch2:
                    st.markdown(f'#### Disagreement challenge &nbsp;<small>{ch2.get("challenger_model","?")} — '
                                f'scope {", ".join(ch2.get("scope_elements") or [])}</small>', unsafe_allow_html=True)
                    if ch2.get("diff_sha") and diff.get("diff_sha") and ch2["diff_sha"] != diff["diff_sha"]:
                        st.warning("This challenge was run against an earlier version of the comparison. "
                                   "One of the two reads has changed since — re-run it before relying on it.")
                    if ch2.get("out_of_scope_dropped"):
                        st.caption(f'{ch2["out_of_scope_dropped"]} challenge(s) were discarded for naming an '
                                   "element outside the disagreement.")
                    _t = ch2.get("supports_tally") or {}
                    if _t:
                        st.caption(f'Evidence read as supporting — you: {_t.get("reviewer", 0)} · '
                                   f'the assessor: {_t.get("assessor", 0)} · neither: {_t.get("neither", 0)}')
                    if ch2.get("overall_reasoning"):
                        st.markdown(ch2["overall_reasoning"])
                    for i2, q2 in enumerate(ch2.get("challenges", []), 1):
                        _side = {"reviewer": "finds for your reading",
                                 "assessor": "finds for the assessor",
                                 "neither": "settles neither side"}.get(q2.get("supports", "neither"))
                        with st.expander(f'{i2}. {q2.get("requirement_pointer", {}).get("element_id", "?")} — '
                                         f'{_side} · {q2.get("challenge_strength", "weak")}'):
                            st.markdown(f'**Challenge:** {q2.get("challenge", "")}')
                            _fp = q2.get("factual_pointer") or {}
                            if _fp.get("quote"):
                                st.markdown(f'> *{_fp["quote"]}*  \n<small>{_fp.get("locator", "")}</small>',
                                            unsafe_allow_html=True)
                            if q2.get("risk_to_address"):
                                st.write(f'**Risk if it stands:** {q2["risk_to_address"]}')
                            if q2.get("resolution_pointer"):
                                st.write(f'**What would settle it:** {q2["resolution_pointer"]}')
                            if q2.get("requirement_pointer_repaired"):
                                st.caption("Requirement pointer was canonicalized from the governed control element; "
                                           "the model's wording was retained only for provenance.")
                    if st.button("Discard this disagreement challenge", key=f"ch2x_{c.key}"):
                        S["challenge2"].pop(c.key, None); save_state(); st.rerun()

            st.markdown("### Reviewer decision — only this is recorded")
            d = S["decisions"].get(c.key)
            if d:
                over = " **(overrides AI)**" if (a or {}).get("sufficiency") and d["sufficiency"] != a["sufficiency"] else ""
                moved_txt = ""
                if d.get("supersedes"):
                    sp = d["supersedes"]
                    moved_txt = (f" — moved from your reading of {sp['sufficiency']}/{sp['maturity']}"
                                 + (" after challenge" if d.get("revised_after_challenge") else "")
                                 + (" after the proposal" if d.get("revised_after_assessor") else ""))
                st.markdown(f'{pill(d["sufficiency"])} maturity {d["maturity"]}/5 — recorded by {d["reviewer"]}, '
                            f'{d["at"][:16].replace("T", " ")}{over}{moved_txt}', unsafe_allow_html=True)
                if d.get("note"):
                    st.caption("Reason: " + d["note"])
                if st.button("Reopen decision"):
                    S["decisions"].pop(c.key); save_state(); st.rerun()
            else:
                _levels = ["none", "partial", "full"]
                # Defaults are the reviewer's own reading. Never the proposal's.
                k1, k2 = st.columns(2)
                suff = k1.selectbox("Sufficiency", _levels, index=_levels.index(blind["sufficiency"]))
                mat = k2.selectbox("Maturity", [1, 2, 3, 4, 5], index=blind["maturity"] - 1)
                note = st.text_area("Which rule or missing element decided it?", value=blind["reason"],
                                    help="Required. If you have moved from your own reading, say what moved you.")
                moved = suff != blind["sufficiency"] or mat != blind["maturity"]
                if moved:
                    st.warning("Your reading is kept and recorded as superseded. This is a revision, "
                               "not a correction — both stand in the record.")
                if st.button("Record decision", type="primary"):
                    if not S.get("reviewer", "").strip():
                        st.error("Set a reviewer name in the sidebar.")
                    else:
                        try:
                            rec = record_decision(a or {}, suff, mat, note, S["reviewer"])
                        except ValueError as e:
                            st.error(str(e))
                        else:
                            err = reason_error(note, rating=suff, revised=moved, previous=blind["reason"])
                            if err:
                                st.error(err)
                            else:
                                rec["blind"] = dict(blind)
                                rec["assessor_shown"] = bool(a)
                                rec["challenged"] = bool(ch)
                                # WB-031: the comparison is stored as a fact of the assessment, not
                                # recomputed later. Element agreement is the calibration signal this
                                # lane has never carried — rating agreement over three values cannot
                                # distinguish an assessor that is right for the wrong reasons.
                                _dif = (S.get("compare") or {}).get(c.key)
                                if _dif:
                                    rec["element_diff"] = {
                                        "comparable": _dif.get("comparable"),
                                        "reason": _dif.get("reason"),
                                        "summary": _dif.get("summary"),
                                        "rating": _dif.get("rating"),
                                        "disagreements": _dif.get("disagreements"),
                                        "diff_sha": _dif.get("diff_sha"),
                                        "rows": [{k_: r_[k_] for k_ in ("element_id", "reviewer", "ai", "agree", "direction")}
                                                 for r_ in (_dif.get("rows") or [])],
                                    }
                                _ch2 = (S.get("challenge2") or {}).get(c.key)
                                rec["challenged_disagreement"] = bool(_ch2)
                                if _ch2:
                                    rec["disagreement_challenge"] = {
                                        "challenger_model": _ch2.get("challenger_model"),
                                        "scope_elements": _ch2.get("scope_elements"),
                                        "supports_tally": _ch2.get("supports_tally"),
                                        "challenge_outcome": _ch2.get("challenge_outcome"),
                                        "diff_sha": _ch2.get("diff_sha"),
                                    }
                                if moved:
                                    rec["supersedes"] = {k_: blind[k_] for k_ in ("sufficiency", "maturity", "reason")}
                                    rec["revised_after_assessor"] = bool(a)
                                    rec["revised_after_challenge"] = bool(ch)
                                    rec["revised_after_compare"] = bool(_dif and _dif.get("comparable"))
                                    rec["revised_after_disagreement_challenge"] = bool(_ch2)
                                    if ch:
                                        S["challenge"][c.key]["changed"] = True
                                    if _ch2:
                                        S["challenge2"][c.key]["changed"] = True
                                S["decisions"][c.key] = rec
                                save_state(); st.rerun()

# ---------- Report ----------
with tab_r:
    if not controls:
        st.info("Load a playbook workbook to use this tab.")
    else:
        st.subheader("Readiness summary")
        st.caption(f"{S['org'] or 'Organisation not set'} · {S['reviewer'] or 'reviewer not set'} · {dt.date.today()}")
        stats = []
        for lib, rows in controls.items():
            if not scope.get(lib):
                continue
            ds = [S["decisions"][c.key] for c in rows if c.key in S["decisions"]]
            cnt = lambda s: sum(1 for d in ds if d["sufficiency"] == s)
            mats = [d["maturity"] for d in ds]
            stats.append({"Library": lib, "Controls": len(rows), "Assessed": len(ds), "Full": cnt("full"), "Partial": cnt("partial"), "None": cnt("none"),
                          "Avg maturity": round(sum(mats) / len(mats), 1) if mats else None})
        st.dataframe(stats, width="stretch", hide_index=True)

        gaps = [c for c in in_scope if S["decisions"].get(c.key, {}).get("sufficiency") != "full"]
        gaps.sort(key=lambda c: {"none": 0, "partial": 1}.get(S["decisions"].get(c.key, {}).get("sufficiency"), 2))
        st.subheader(f"Gap register ({len(gaps)})")
        st.dataframe([{"Control": f"{c.id} {c.title}", "Library": c.lib, "Rating": S["decisions"].get(c.key, {}).get("sufficiency", "not assessed"),
                       "Owner": c.owner, "Gaps noted": "; ".join(S["ai"].get(c.key, {}).get("gaps", []))} for c in gaps],
                     width="stretch", hide_index=True, height=360)

        # markdown report
        md = [f"# AI Governance Readiness Assessment\n", f"**Organisation:** {S['org']}  ", f"**Reviewer:** {S['reviewer']}  ", f"**Date:** {dt.date.today()}  ",
              f"**Scope:** {', '.join(l for l in scope if scope[l])}\n",
              "The named reviewer records their own reading of the evidence before any model output is shown. An AI assistant then proposes a sufficiency rating, and a challenger may attack the reading with questions but cannot rate and cannot agree. Where the reviewer moved from their own reading, both readings stand in the record. Ratings describe how far supplied evidence supports each control. They are not a determination of regulatory compliance.\n",
              "## Summary\n", "| Library | Controls | Assessed | Full | Partial | None | Avg maturity |", "|---|---|---|---|---|---|---|"]
        md += [f"| {s['Library']} | {s['Controls']} | {s['Assessed']} | {s['Full']} | {s['Partial']} | {s['None']} | {s['Avg maturity'] or '–'} |" for s in stats]
        md += ["\n## Gap register\n", "| Control | Library | Rating | Owner | Gaps noted |", "|---|---|---|---|---|"]
        md += [f"| {c.id} {c.title} | {c.lib} | {S['decisions'].get(c.key, {}).get('sufficiency', 'not assessed')} | {c.owner} | {'; '.join(S['ai'].get(c.key, {}).get('gaps', []))} |" for c in gaps]
        if st.session_state.get("gap_rows"):
            md += ["\n## Gap analysis and suggested actions\n", "| Control | Library | Finding | Gaps | Suggested action | Owner |", "|---|---|---|---|---|---|"]
            md += [f"| {r['Control']} | {r['Library']} | {r['Finding']} | {r['Gaps']} | {r['Suggested action']} | {r['Owner']} |" for r in st.session_state.gap_rows]
        md += ["\n## Accepted assessments\n"]
        for c in in_scope:
            d = S["decisions"].get(c.key)
            if not d:
                continue
            a = S["ai"].get(c.key, {})
            md += [f"### {c.id} — {c.title} ({c.lib})",
                   f"- Rating: {d['sufficiency']}, maturity {d['maturity']}/5 — recorded by {d['reviewer']} on {d['at'][:10]}" + (f" (AI proposed {d['aiSufficiency']})" if d.get('aiSufficiency') != d['sufficiency'] else ""),
                   f"- Reviewer's reading before any model output: {d['blind']['sufficiency']}, maturity {d['blind']['maturity']}/5 — {d['blind']['reason']}" if d.get("blind") else "- Reviewer's reading before any model output: not recorded (assessed before this was required)",
                   (f"- Moved from that reading after " + ("the challenger" if d.get("revised_after_challenge") else "") + (" and " if d.get("revised_after_challenge") and d.get("revised_after_assessor") else "") + ("the proposal" if d.get("revised_after_assessor") else "")) if d.get("supersedes") else "- Held the reading",
                   f"- Rationale: {a.get('rationale', '')}"] + ([f'- Evidence excerpt: "{a["excerpt"]}"'] if a.get("excerpt") else []) + ([f"- Validation flags: {'; '.join(a['flags'])}"] if a.get("flags") else []) + ([f"- Reviewer note: {d['note']}"] if d.get("note") else []) + [""]
        if st.session_state.get("lifecycle_view"):
            md += ["\n## Lifecycle plays — design vs operation\n",
                   "| Play | Steps tested | Op PASS | Op FAIL | Op N/T | Design full | Design partial | Design none | Unassessed | Flag |",
                   "|---|---|---|---|---|---|---|---|---|---|"]
            for v_ in st.session_state.lifecycle_view:
                s_ = v_["summary"]
                md.append(f"| {v_['id']} {v_['title']} | {s_['steps_tested']}/{s_['steps']} | {s_['op_pass']} | {s_['op_fail']} | {s_['op_nt']} | "
                          f"{s_['design_full']} | {s_['design_partial']} | {s_['design_none']} | {s_['design_unassessed']} | "
                          f"{'design full / op FAIL' if s_['design_full_op_fail'] else ''} |")
            md.append("\nOperation verdicts are deterministic Lane B checks; design ratings are reviewer-recorded Lane A assessments. A step without an operating test is a coverage gap, not a pass.")
        report = "\n".join(md)

        c1, c2 = st.columns(2)
        c1.download_button("Download report (.md)", report, file_name=f"AI_readiness_{(S['org'] or 'org').replace(' ', '_')}.md", type="primary")
        if c2.button("Write results back to playbook"):
            out = DATA / f"playbook_assessed_{dt.date.today()}.xlsx"
            n = export_playbook(src, str(out), controls, S["decisions"], S["ai"], S["evidence"])
            st.success(f"{n} control rows updated → {out}")
            st.download_button("Download updated playbook", out.read_bytes(), file_name=out.name)


# ====================================================================
# ---------- Audit (Lane B: deterministic control testing) ----------
# ====================================================================
with tab_b:
    st.subheader("Continuous control testing")
    st.caption("Deterministic checks over artefacts (git history, dependency pins, deploy manifests, governance exports, environment signals). "
               "No model is involved. Each run writes a hashed evidence bundle; only a named reviewer can sign a result.")
    afolder = st.text_input("Target folder (repo or evidence root)", S.get("scan_folder", ""), key="audit_folder")
    S["scan_folder"] = afolder
    c1, c2, c3 = st.columns([1, 1, 2])
    trig = c2.selectbox("Trigger", ["manual", "on_commit", "on_deploy", "scheduled"], help="Selects controls by frequency. `manual` runs everything.")
    if c1.button("Run audit", type="primary", disabled=not afolder):
        if not os.path.isdir(afolder):
            st.error("Folder not found.")
        else:
            with st.spinner("Discovering artefacts and running checks…"):
                try:
                    b, bpath = run_audit(afolder, trig)
                    st.session_state.sel_bundle = str(bpath)
                    st.success(f"Bundle {b['bundle_id'][:8]} written: {len(b['results'])} controls run.")
                except Exception as e:
                    st.error(f"Audit failed: {e}")
    save_state()

    bundles = list_bundles()
    if not bundles:
        st.info("No bundles yet. Run an audit, or `python -m caa.runner --target <folder>` from a terminal / CI.")
    else:
        st.markdown("#### Bundles")
        st.dataframe([{"Run at": b_["run_at"][:19].replace("T", " "), "Trigger": b_["trigger"], "Controls": b_["controls"],
                       "PASS": b_["PASS"], "FAIL": b_["FAIL"], "NOT_TESTABLE": b_["NOT_TESTABLE"], "Unsigned": b_["unsigned"],
                       "Integrity": "✓" if b_["integrity"] else "✗ TAMPERED", "Bundle": b_["bundle_id"][:8]} for b_ in bundles],
                     width="stretch", hide_index=True, height=200)
        paths = [b_["path"] for b_ in bundles]
        default = st.session_state.get("sel_bundle") if st.session_state.get("sel_bundle") in paths else paths[0]
        selp = st.selectbox("Open bundle", paths, index=paths.index(default),
                            format_func=lambda p_: next(f"{b_['run_at'][:19].replace('T',' ')} · {b_['trigger']} · {b_['bundle_id'][:8]}" for b_ in bundles if b_["path"] == p_))
        st.session_state.sel_bundle = selp
        bd = load_bundle(selp)
        ok = next(b_["integrity"] for b_ in bundles if b_["path"] == selp)
        if not ok:
            st.error("Integrity check failed: machine results in this bundle were modified after the run. Signing is disabled.")
        st.caption(f"Runner {bd['runner_version']} · control pack {bd['control_pack']['sha256'][:12]} ({bd['control_pack']['control_count']} controls) · "
                   f"target `{bd.get('inventory_id','')[:8]}` · bundle sha {bd['bundle_sha256'][:12]}")

        order = {"FAIL": 0, "NOT_TESTABLE": 1, "PASS": 2}
        results = sorted(bd["results"], key=lambda r_: (order[r_["machine_verdict"]], r_["control_id"]))
        show_pass = st.checkbox("Show PASS results", False)
        for r_ in results:
            if r_["machine_verdict"] == "PASS" and not show_pass:
                continue
            hv = r_.get("human_verdict")
            head = f"{r_['control_id']} — {r_['assertion'][:90]}"
            with st.expander(head, expanded=(r_["machine_verdict"] != "PASS" and not hv)):
                st.markdown(f"{vpill(r_['machine_verdict'])} &nbsp; <small>{r_['severity']} · {r_['domain']} · {', '.join(r_.get('framework_refs', []))}</small>", unsafe_allow_html=True)
                st.write(r_["detail"])
                if r_.get("findings"):
                    flat = [{k: (v if not isinstance(v, (dict, list)) else json.dumps(v)[:120]) for k, v in f_.items()} for f_ in r_["findings"][:50]]
                    st.dataframe(flat, width="stretch", hide_index=True)
                if r_.get("evidence"):
                    st.caption("Evidence examined: " + "; ".join(f"{e_['source']} ({e_['sha256'][:10]})" for e_ in r_["evidence"]))
                st.markdown(f'<div class="req"><b>Human gate</b> — {r_["human_gate"]}</div>', unsafe_allow_html=True)

                if hv:
                    st.markdown(f"**{hv['disposition']}** — signed by {hv['reviewer']}, {hv['signed_at'][:16].replace('T', ' ')}" +
                                (f" · exception {hv['exception_ref']}" if hv.get("exception_ref") else ""))
                    if hv.get("rationale"):
                        st.caption(hv["rationale"])
                    if st.button("Reopen", key=f"unsign_{r_['control_id']}"):
                        unsign_result(selp, r_["control_id"]); st.rerun()
                elif ok:
                    k1, k2, k3 = st.columns([1.2, 1, 2])
                    disp = k1.selectbox("Disposition", DISPOSITIONS, key=f"disp_{r_['control_id']}")
                    exc = k2.text_input("Exception ref", key=f"exc_{r_['control_id']}", placeholder="EXC-…")
                    rat = k3.text_input("Rationale", key=f"rat_{r_['control_id']}")
                    if st.button("Sign", key=f"sign_{r_['control_id']}", type="primary", disabled=not S.get("reviewer")):
                        try:
                            sign_result(selp, r_["control_id"], S["reviewer"], disp, rat, exc or None)
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
                    if not S.get("reviewer"):
                        st.caption("Set your reviewer name in the sidebar to sign.")

# ====================================================================
# ---------- History (Lane B: one control across runs) ----------
# ====================================================================
with tab_h:
    st.subheader("Control history")
    bundles = list_bundles()
    if not bundles:
        st.info("No bundles yet.")
    else:
        ids = sorted({r_["control_id"] for b_ in bundles for r_ in load_bundle(b_["path"])["results"]})
        cid = st.selectbox("Control", ids)
        hist = control_history(cid)
        if hist:
            st.markdown(f"**{cid}** — latest: {vpill(hist[0]['machine_verdict'])}", unsafe_allow_html=True)
            st.dataframe([{"Run at": h["run_at"][:19].replace("T", " "), "Trigger": h["trigger"], "Machine": h["machine_verdict"],
                           "Detail": h["detail"], "Disposition": h["disposition"] or "—", "Reviewer": h["reviewer"] or "—"} for h in hist],
                         width="stretch", hide_index=True)
            streak = 0
            for h in hist:
                if h["machine_verdict"] == "FAIL":
                    streak += 1
                else:
                    break
            if streak >= 3:
                st.warning(f"{cid} has failed on the last {streak} runs. If an exception is in place it should appear in the exception register (MCM-10).")
        items = open_items()
        st.markdown(f"#### Open items in latest bundle ({len(items)})")
        st.caption("FAIL or NOT_TESTABLE results with no reviewer signature.")
        st.dataframe([{"Control": i_["control_id"], "Verdict": i_["machine_verdict"], "Severity": i_["severity"], "Detail": i_["detail"]} for i_ in items],
                     width="stretch", hide_index=True)


# ====================================================================
# ---------- Lifecycle (join: plays link design and operation) ----------
# ====================================================================
with tab_l:
    st.subheader("Lifecycle plays — design vs operation")
    st.caption("Each play from the playbook's Playbooks & Runbooks sheet. Design = Lane A rating of the controls the play satisfies "
               "(reviewer-recorded, or AI-proposed and flagged). Operation = latest Lane B verdict of the tests hung off each step's evidence output. "
               "A step with no test is a gap in continuous coverage, not a pass.")
    if not plays:
        st.info("Load the playbook workbook to see the lifecycle plays.")
    else:
        lb = latest_lane_b()
        view = lifecycle_view(plays, in_scope, S["decisions"], S["ai"], lb)
        RCOL = {"full": COL["full"], "partial": COL["partial"], "none": COL["none"], None: COL["pending"]}

        # overview
        st.dataframe([{"Play": f"{v['id']} {v['title']}", "Steps": v["summary"]["steps"], "Steps tested": v["summary"]["steps_tested"],
                       "Op PASS": v["summary"]["op_pass"], "Op FAIL": v["summary"]["op_fail"], "Op N/T": v["summary"]["op_nt"],
                       "Controls in scope": v["summary"]["controls"], "Design full": v["summary"]["design_full"],
                       "Design partial": v["summary"]["design_partial"], "Design none": v["summary"]["design_none"],
                       "Unassessed": v["summary"]["design_unassessed"],
                       "Flag": "design full / op FAIL" if v["summary"]["design_full_op_fail"] else ""} for v in view],
                     width="stretch", hide_index=True, height=430)
        st.session_state.lifecycle_view = view

        sel_play = st.selectbox("Open play", [v["id"] for v in view], format_func=lambda i: next(f"{v['id']} {v['title']}" for v in view if v["id"] == i))
        v = next(x for x in view if x["id"] == sel_play)
        st.markdown(f"#### {v['id']} — {v['title']}")
        st.caption(v["header"])
        if v["summary"]["design_full_op_fail"]:
            st.error("Design rated full on at least one control, but an operating test is failing. Investigate before relying on the design rating.")

        st.markdown("**Steps and operating tests**")
        for s in v["steps"]:
            c1, c2 = st.columns([3, 2])
            c1.markdown(f"**{s['id']}** {s['action']}  \n<small>{s['owner']}"
                        + (f" · {s['cadence']}" if s["cadence"] else "") + f" · evidence: *{s['evidence']}*</small>", unsafe_allow_html=True)
            if not s["tests"]:
                c2.markdown('<span class="pill" style="background:#6B7A8A">no operating test</span>', unsafe_allow_html=True)
            for r_ in s["tests"]:
                hv = r_.get("human_verdict") or {}
                c2.markdown(f"{vpill(r_['machine_verdict'])} **{r_['control_id']}** <small>{r_['detail'][:60]}"
                            + (f" · {hv['disposition']} by {hv['reviewer']}" if hv else "") + f" · {r_['run_at'][:10]}</small>", unsafe_allow_html=True)

        st.markdown("**Controls this play satisfies (design)**")
        if v["controls"]:
            st.dataframe([{"Control": f"{c['id']} {c['title'][:70]}", "Library": c["lib"],
                           "Design rating": (c["rating"] or "not assessed") + ("" if c["recorded"] or not c["rating"] else " (proposed)"),
                           "Maturity": c["maturity"] or "—"} for c in v["controls"]], width="stretch", hide_index=True)
        else:
            st.caption("None of this play's controls are in the selected scope.")


# ---- Step 8: per-use-case lifecycle cards (judge proposes, reviewer decides) ----
with tab_l:
    if plays:
        st.markdown("---")
        import lifecycle_cards
        lifecycle_cards.render(plays, st.session_state.get("index"), latest_lane_b())
