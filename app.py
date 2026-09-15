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
import events
from core import cycle as governance_cycle
from core.cycle import CycleError
from governance import completeness
from governance.outcomes import outcome_definitions, evaluate_outcome, evaluate_all, crosswalk_validation
from plays import load_plays
from reasons import reason_error
from challenge import challenge as run_challenge, challenge_disagreement as run_challenge2
from compare import compare as compare_reads, headline as compare_headline, elements_for
from governance.evidence_element_matcher import suggest_element_matches
from challenge_dossier import create_dossier, respond as respond_to_challenge, append as append_dossier
from caa.review import DISPOSITIONS
from playbook import LIBRARIES, load_controls
from review_queue import build_queue, next_action, project_control
from observations import observation_to_evidence_packet
from plugin_registry import get_plugin, list_plugins
from governance.decision_engine import evaluate as evaluate_governance
from governance.engine import plan as engine_plan, evaluate_control as engine_evaluate_control, advance_finding
from services import governance_service
from ui.governance_engine import render as render_governance_engine
from governance.resources import Resource, ResourceSelector
from governance.observation import Observation
from demo_evidence import generate_pack as generate_demo_evidence
from governance.source_review import extract_text as extract_source_text, best_excerpts
import folder_picker as fp
import tour

DATA = Path("data")
DATA.mkdir(exist_ok=True)
STATE_FILE = DATA / "assessments.json"
DEFAULT_PLAYBOOK = next(DATA.glob("*.xlsx"), None)

st.set_page_config(page_title="AI governance readiness workbench", layout="wide")


# ---------- uploaded source review ----------
def _render_uploaded_source_review(c):
    if c.lib != "MAS":
        return
    src = S.get("mas_source_review") or {}
    text = src.get("text") or ""
    if not text:
        return
    st.markdown("### MAS source under review")
    st.caption(f"{src.get('name','uploaded source')} · {len(text):,} extracted characters · review-only context")
    st.info("This uploaded document is source-review context. It does not replace the authoritative control contract, and it is not treated as organisational evidence.")
    hits = best_excerpts(text, c, limit=5)
    if not hits:
        st.warning("No strong source match was found for this control. Review the source manually or refine the control wording.")
        return
    for idx,h in enumerate(hits,1):
        with st.expander(f"Source match {idx} · score {h['score']} · paragraph {h['paragraph']}", expanded=(idx==1)):
            st.code(h['excerpt'], language="text")

# ---------- persistence ----------
#: Keys that are governance records, not UI state. GE-109: these are stripped on load and
#: rebuilt from the event ledger, so `assessments.json` cannot carry a decision forward even if
#: an old file has one in it. Saying the file is "cache only" in a comment is not the same as
#: making it true — before this, `_sync_authoritative_decisions` overwrote `decisions` only
#: `if projected`, so a cache with decisions and a ledger without them left the cache standing
#: as the record.
_LEDGER_OWNED = ("decisions",)


def load_state():
    base = {"org": "", "reviewer": "", "evidence": {}, "ai": {}, "decisions": {},
            "blind": {}, "challenge": {}, "challenge2": {}, "plugin_observations": {},
            "plugin_packets": {}, "mas_source_review": {}}
    if STATE_FILE.exists():
        base.update(json.loads(STATE_FILE.read_text()))
    for key in _LEDGER_OWNED:
        base[key] = {}
    return base


def save_state():
    """Write the UI/session cache.

    Governance records live in events.jsonl and are rebuilt from it on every load. Anything in
    `_LEDGER_OWNED` is written here for the current session's convenience and discarded on the
    next load — deleting this file must cost the reviewer their scroll position and their scan
    folder, never a decision.
    """
    STATE_FILE.write_text(json.dumps(st.session_state.s, indent=1, default=str))


def _event_decisions():
    """Project authoritative Lane A decisions from the append-only event log."""
    out = {}
    for row in events.decided():
        framework = str(row.get("framework") or "").strip()
        control_id = str(row.get("control_id") or "").strip()
        if not control_id:
            continue
        key = f"{framework}::{control_id}" if framework else control_id
        d = dict(row.get("decision") or {})
        d.setdefault("reviewer", row.get("decided_by"))
        d.setdefault("at", row.get("decision_recorded_at"))
        d["cycle_id"] = row.get("cycle_id")
        out[key] = d
    return out


def _sync_authoritative_decisions():
    """Rebuild decisions from the ledger. Unconditional — an empty ledger means no decisions."""
    S["decisions"] = _event_decisions()


def _cycle_states():
    """Current governed projection for each in-scope control, keyed by UI control key."""
    out = {}
    for c in in_scope if "in_scope" in globals() else []:
        cid = (S.get("cycle_ids") or {}).get(c.key)
        if cid:
            st_ = events.state(cid)
            if st_:
                out[c.key] = st_
    return out


def _decision_preview(c, blind, suff, mat, note):
    """Preview the same deterministic v0.8 decision posture used by cycle.decide()."""
    cid = (S.get("cycle_ids") or {}).get(c.key)
    governed_state = events.state(cid) if cid else {}
    history = [x for x in events.iter_states()
               if x.get("control_id") == c.id and x.get("cycle_id") != cid and x.get("stage") == "decided"]
    return evaluate_governance(
        control_id=c.id,
        reviewer_decision={"action": "accept", "sufficiency": suff, "maturity": int(mat), "reason": str(note or "").strip()},
        claims=(governed_state.get("claim_register") or {}).get("claims") or governed_state.get("claims") or [],
        challenges=governed_state.get("challenges") or (S.get("challenge") or {}).get(c.key, {}).get("challenges") or [],
        probes=(governed_state.get("falsification_engine") or {}).get("probes") or [],
        proposed=governed_state.get("proposal") or (S.get("ai") or {}).get(c.key),
        reviewer_read=governed_state.get("read") or blind, history=history,
    )


def _ensure_cycle(c, ev):
    """Create/reuse the append-only cycle that backs the current UI control.

    GE-110 follow-up: `record_proposal` raises `ContractInvalid` when the control's contract
    fails integrity, and that exception was reaching the top of the Streamlit script — so one
    bad contract in a bulk run killed the whole run and lost every control after it.

    Raising was the right call at the engine boundary and stays. What was wrong is that the
    caller treated a governed refusal as a crash. A contract that cannot be assessed is a
    *result*, the same way NOT_TESTABLE and CONTRACT_INVALID are results everywhere else here,
    so the cycle is still created and the evidence still bound — both are facts worth keeping —
    and only the proposal is withheld. The block is recorded on the cycle so the Review
    workspace can explain it rather than showing an empty assessment.
    """
    from governance.contract_integrity import ContractInvalid
    S.setdefault("cycle_ids", {})
    S.setdefault("contract_blocked", {})
    cid = S["cycle_ids"].get(c.key)
    if cid and events.state(cid):
        return cid
    cid = governance_cycle.start(c.id, framework=c.lib, actor=S.get("reviewer", "system") or "system")
    governance_cycle.bind_evidence(cid, dict(ev), actor=S.get("reviewer", "system") or "system")
    if S.get("ai", {}).get(c.key):
        try:
            governance_cycle.record_proposal(cid, S["ai"][c.key],
                                             model=S["ai"][c.key].get("model"),
                                             assessment_identity=S.get("assessment_identity"))
            S["contract_blocked"].pop(c.key, None)
        except ContractInvalid as exc:
            S["contract_blocked"][c.key] = exc.report
        except CycleError as exc:
            # A failed assessor call is refused by `record_proposal` too. Also not a crash.
            S["contract_blocked"][c.key] = {"status": "NOT_RECORDED", "executable": False,
                                            "error_count": 1, "warning_count": 0,
                                            "findings": [{"code": "PROPOSAL_REFUSED",
                                                          "severity": "error",
                                                          "message": str(exc)}]}
    S["cycle_ids"][c.key] = cid
    return cid


if "s" not in st.session_state:
    st.session_state.s = load_state()
S = st.session_state.s
S.setdefault("cycle_ids", {})
S.setdefault("plugin_observations", {})
S.setdefault("plugin_packets", {})
_sync_authoritative_decisions()

# Theme is a persisted preference, applied before any component draws.
THEME = "dark" if S.get("dark") else "light"
tour.apply_theme(THEME)
COL = tour.theme_colors(THEME)
pill = lambda s: f'<span class="pill" style="background:{COL.get(s, COL["pending"])}">{s}</span>'


def stages(*items) -> str:
    """A four-stage strip for the Review workspace: where you are, and what is still ahead.

    The assessment order is deliberate — the reviewer's own reading is recorded before any
    model output is shown — but a gate the user cannot see reads as a missing feature rather
    than a sequence. Hiding the challenge and assess buttons until a reading exists made the
    tab look like it had two controls when it has four. Showing all four stages, with the
    unreachable ones greyed, makes the order legible without making it optional.

    items: (label, state) where state is 'done', 'now' or 'wait'.
    """
    c = {"done": COL["full"], "now": COL["partial"], "wait": COL["pending"],
         "held": COL["pending"], "blocked": COL["none"]}
    parts = [f'<span class="pill" style="background:{c[st_]}">{i}. {label}</span>'
             for i, (label, st_) in enumerate(items, 1)]
    sep = ' <span style="opacity:.4">&rsaquo;</span> '
    return '<div style="margin:.15rem 0 .7rem 0">' + sep.join(parts) + '</div>'

_CONTRACT_LABELS = {
    "REQUIREMENT_AS_ARTEFACT": "requirement sentence in the artefact column",
    "CROSS_CONTROL_ELEMENT_CONTAMINATION": "elements belong to another control",
    "WRITE_BACK_PROVENANCE_MISMATCH": "element is verbatim a test step",
    "DUPLICATE_ELEMENT_ID": "duplicate element id",
    "PLACEHOLDER_EVIDENCE_ONLY": "declared evidence is a placeholder",
    "GENERATED_SOURCE_IN_AUTHORITATIVE_PATH": "contract loaded from generated output",
    "CONTRACT_UNREADABLE": "contract could not be loaded",
    "NO_DECLARED_EVIDENCE": "no declared evidence",
    "SOURCE_PROVENANCE_UNDECLARED": "workbook provenance undeclared",
}


def _contract_report(c):
    """GE-110. One call to the service, cached per control for the session.

    The app does not know which checks exist, what their severities are, or what blocks. It asks
    for a status and renders it. When the predicate engine lands the shape is the same — ask
    `evaluate(control_id, scope)`, render a ControlResult, never learn what a predicate is.
    """
    cache = st.session_state.setdefault("_contract_status", {})
    if c.key not in cache:
        try:
            cache[c.key] = governance_cycle.contract_status(
                c.id, c.lib, source_path=st.session_state.get("playbook_path"))
        except Exception as exc:
            cache[c.key] = {"status": "CONTRACT_INVALID", "executable": False,
                            "error_count": 1, "warning_count": 0,
                            "findings": [{"code": "CONTRACT_UNREADABLE", "severity": "error",
                                          "message": str(exc)}]}
    return cache[c.key]



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
    mas_src = st.file_uploader("MAS whitepaper / consultation source for review", type=["pdf","txt","md","docx"], key="mas_source_upload")
    if mas_src is not None:
        try:
            _txt = extract_source_text(mas_src.getvalue(), mas_src.name)
            S["mas_source_review"] = {"name": mas_src.name, "text": _txt, "uploaded_at": dt.datetime.now().isoformat(timespec="seconds")}
            save_state()
            st.success(f"MAS source staged for review: {mas_src.name}")
        except Exception as exc:
            st.error(f"Could not extract MAS source: {type(exc).__name__}: {exc}")
    elif S.get("mas_source_review"):
        st.caption(f"MAS source staged: {S['mas_source_review'].get('name','source')}")
        if st.button("Clear staged MAS source", key="clear_mas_source"):
            S["mas_source_review"] = {}
            save_state(); st.rerun()
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

tab_s, tab_a, tab_r, tab_o, tab_b, tab_h, tab_l, tab_m, tab_e = st.tabs(["Scan", "Review", "Report", "Outcomes", "Audit", "History", "Lifecycle", "Measurement", "Engine"])
# ---------- Outcomes ----------
with tab_o:
    st.subheader("Governance outcomes")
    st.caption("Outcome posture is computed from the authoritative append-only event projection and governed MAS/MGF mappings. Outcomes never replace the framework requirements.")

    mapping_errors = crosswalk_validation()
    rows = evaluate_all()

    # Graphical outcome surface: every tile is a deterministic projection of governed records.
    POSTURE_META = {
        "adequate": ("#2F7D5B", "ADEQUATE"),
        "remediate": ("#B7791F", "REMEDIATE"),
        "escalate": ("#8A5A00", "ESCALATE"),
        "defer": ("#A23B3B", "DEFER"),
    }
    CAP_META = {
        "supported": "#2F7D5B",
        "insufficient": "#B7791F",
        "blocked": "#A23B3B",
        "escalate": "#8A5A00",
    }
    st.markdown("""
    <style>
      .outcome-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(290px,1fr)); gap:12px; margin:8px 0 18px; }
      .outcome-card { border:1px solid #323944; border-radius:12px; padding:16px; background:#151A21; min-height:160px; }
      .outcome-card .id { font-size:.78rem; opacity:.72; letter-spacing:.02em; }
      .outcome-card .title { font-size:1.03rem; font-weight:750; margin:5px 0 9px; line-height:1.25; }
      .outcome-card .posture { display:inline-block; padding:4px 9px; border-radius:999px; color:white; font-size:.72rem; font-weight:800; letter-spacing:.04em; }
      .outcome-card .stats { display:flex; gap:16px; margin-top:11px; font-size:.82rem; opacity:.86; }
      .outcome-card .next { margin-top:10px; font-size:.79rem; opacity:.78; line-height:1.35; }
      .cap-heatmap { width:100%; border-collapse:separate; border-spacing:4px; font-size:.76rem; }
      .cap-heatmap th { text-align:left; padding:7px; opacity:.75; }
      .cap-heatmap td { padding:8px 7px; border-radius:6px; text-align:center; font-weight:700; }
    </style>
    """, unsafe_allow_html=True)

    if mapping_errors:
        st.error(f"Outcome mapping integrity blocked: {len(mapping_errors)} issue(s).")
        st.caption("The dashboard is intentionally fail-closed; invalid mappings never disappear from the posture calculation.")

    # Summary counts are calculated only from evaluate_all().
    counts = {p: sum(1 for r in rows if r.get("posture") == p) for p in ("adequate", "remediate", "escalate", "defer")}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Adequate", counts["adequate"])
    c2.metric("Remediate", counts["remediate"])
    c3.metric("Escalate", counts["escalate"])
    c4.metric("Defer", counts["defer"])

    cards = []
    for r in rows:
        color, label = POSTURE_META.get(r["posture"], ("#6B7280", r["posture"].upper()))
        total_caps = len(r.get("capabilities", {}))
        supported_caps = sum(1 for v in r.get("capabilities", {}).values() if v.get("status") == "supported")
        title = next((str(o.get("title")) for o in outcome_definitions() if str(o.get("outcome_id")) == r["outcome_id"]), r["outcome_id"])
        cards.append(
            f'<div class="outcome-card"><div class="id">{r["outcome_id"]}</div>'
            f'<div class="title">{title}</div>'
            f'<span class="posture" style="background:{color}">{label}</span>'
            f'<div class="stats"><span>Capabilities: <b>{supported_caps}/{total_caps}</b></span>'
            f'<span>Elements: <b>{r["full_count"]}/{r["mapped_count"]}</b></span></div>'
            f'<div class="next">Next: {r["next_action"]}</div></div>'
        )
    st.markdown('<div class="outcome-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)

    # Deterministic outcome selection for drill-down.
    st.markdown("**Open an outcome for governed detail**")
    button_cols = st.columns(min(4, max(1, len(rows))))
    for idx, r in enumerate(rows):
        with button_cols[idx % len(button_cols)]:
            if st.button(r["outcome_id"], key=f"outcome_open_{r['outcome_id']}", use_container_width=True):
                st.session_state["outcome_focus"] = r["outcome_id"]
                st.rerun()

    # Fast coverage heatmap: rows=outcomes, columns=catalogue capabilities.
    all_caps = sorted({cap for r in rows for cap in r.get("capabilities", {})})
    if all_caps:
        st.markdown("### Capability coverage")
        header = ''.join(f'<th title="{c}">{c.replace("_", " ")}</th>' for c in all_caps)
        body = []
        for r in rows:
            cells = []
            for cap in all_caps:
                v = r.get("capabilities", {}).get(cap)
                status = v.get("status") if v else "—"
                bg = CAP_META.get(status, "#313846") if status != "—" else "#202630"
                cells.append(f'<td style="background:{bg};color:white" title="{cap}: {status}">{status[:4].upper() if status != "—" else "—"}</td>')
            body.append(f'<tr><th>{r["outcome_id"]}</th>' + ''.join(cells) + '</tr>')
        st.markdown('<div style="overflow-x:auto"><table class="cap-heatmap"><thead><tr><th>Outcome</th>' + header + '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>', unsafe_allow_html=True)

    focus = st.session_state.get("outcome_focus")
    selected = next((r for r in rows if r["outcome_id"] == focus), None)
    if selected:
        st.markdown(f"### {selected['outcome_id']} · {selected['posture'].upper()}")
        if selected["errors"]:
            st.error("Crosswalk integrity failure: outcome is fail-closed.")
            st.json(selected["errors"])
        st.markdown(f"**Next:** {selected['next_action']}")
        st.dataframe([
            {"Framework": x["framework"], "Control": x["control_id"], "Element": x["element_id"],
             "Status": x["status"], "Evidence modes": ", ".join(x.get("evidence_modes") or []),
             "Blockers": ", ".join(x["blockers"]) or "—"}
            for x in selected["mapped_items"]
        ], width="stretch", hide_index=True)
        if selected["capabilities"]:
            st.markdown("**Capability status**")
            st.dataframe([
                {"Capability": k, "Status": v["status"], "Mapped elements": v["mapped_count"],
                 "Supported": v["full_count"]}
                for k, v in sorted(selected["capabilities"].items())
            ], width="stretch", hide_index=True)
        if st.button("Close outcome detail", key="outcome_close"):
            st.session_state.pop("outcome_focus", None)
            st.rerun()

    with st.expander("Audit table", expanded=False):
        st.dataframe([
            {"Outcome": r["outcome_id"], "Posture": r["posture"], "Mapped": r["mapped_count"],
             "Full": r["full_count"], "Next action": r["next_action"], "Integrity": "BLOCKED" if r["errors"] else "OK"}
            for r in rows
        ], width="stretch", hide_index=True)

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
            st.info("Go to the **Review** tab, choose a control, and work through one step at a time. "
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
            st.caption("Proposals are stored **hidden**. In the Review workspace each one stays "
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
                skipped = []
                S.setdefault("contract_blocked", {})
                for n, c in enumerate(todo):
                    bar.progress(n / len(todo), f"Assessing {c.id} ({n + 1}/{len(todo)})")
                    # GE-110: a contract that cannot be assessed does not get an assessor call.
                    # Running the model and then refusing to record it burns a minute per
                    # control to produce something the engine will not accept.
                    _blocked = not _contract_report(c).get("executable", True)
                    if _blocked:
                        skipped.append(c.id)
                        S["contract_blocked"][c.key] = _contract_report(c)
                        continue
                    S["evidence"][c.key] = build_evidence(c, matches[c.key], sigs)
                    # WB-023: the threshold changes which passages a control was assessed on, so it
                    # belongs with the evidence. Without it a stored proposal cannot be reproduced.
                    S["evidence"][c.key]["retrieval"] = {"min_ratio": min_ratio, "min_score": MIN_SCORE, "k": TOP_K}
                    S["ai"][c.key] = propose(c, S["evidence"][c.key])
                    fails += S["ai"][c.key].get("model") == "error"
                    S["decisions"].pop(c.key, None)
                    # Persist the assessment lifecycle in the append-only governance log.
                    _ensure_cycle(c, S["evidence"][c.key])
                    save_state()
                bar.empty()
                st.success(f"Assessed {len(todo) - len(skipped)} controls ({fails} errors). "
                           "**Nothing is recorded yet.** Go to the Review workspace — each proposal "
                           "stays hidden until you have recorded your own reading of the evidence.")
                if skipped:
                    st.warning(
                        f"**{len(skipped)} control(s) skipped — CONTRACT INVALID.** "
                        f"Their contracts fail integrity, so no assessment was run and none was "
                        f"recorded. This is a defect in the control library, not in the evidence.\n\n"
                        + ", ".join(skipped[:20]) + (" …" if len(skipped) > 20 else ""))

        # gap analysis
        if S["ai"] or S["decisions"]:
            st.subheader("Gap analysis")
            rows_ = gap_analysis(in_scope, S["ai"], S["decisions"])
            st.caption(f"{len(rows_)} controls below full. Proposed ratings are the assessor's; only reviewed ones are recorded.")
            st.dataframe([{k: v for k, v in r.items() if k != "Priority"} for r in rows_], width="stretch", hide_index=True, height=400)
            st.session_state.gap_rows = rows_

# ---------- Review workspace ----------
def _queue_markers(r) -> str:
    """The one-line step summary on each review-queue row.

    WB-108: this row ticked `AI ✓` while `Read —`, announcing across every row in the queue that
    a proposal was finished and waiting before the reviewer had read anything. WB-106 fixed the
    same display in the workspace progress bar and missed this one, which is the more exposed of
    the two — the queue is the first screen, and it says it for every control at once.

    A ready proposal behind an open blind read is shown `⏸`, matching the workspace. The
    proposal itself stays withheld either way; what changes is that the queue no longer presents
    a gated step as a completed one.

    Completeness and Challenge are included because the queue previously showed four of the
    seven steps, and a summary that silently omits steps is how the two indicators drifted apart
    in the first place.
    """
    ch = r.get("challenge") or {}
    if r.get("proposal_error"):
        ai = "!"
    elif not r.get("has_proposal"):
        ai = "—"
    elif not r.get("has_read"):
        ai = "⏸"
    else:
        ai = "✓"
    if not r.get("has_compare"):
        chal = "—"
    elif ch.get("blocked"):
        chal = "⚠"
    elif ch.get("produced_a_result"):
        chal = "✓" if not (ch.get("unresolved") or ch.get("unresolved_strong")) else "!"
    else:
        chal = "—"
    if r.get("contract_blocked"):
        # GE-110: one line, not a step strip. A blocked contract has no steps to be partway
        # through, and showing "Evidence ✓" beside it would imply progress that cannot happen.
        return "⛔ CONTRACT INVALID — assessment not executable"
    tick = lambda v: "✓" if v else "—"
    marks = {"evidence": tick(r.get("has_evidence")),
             "completeness": tick(r.get("has_completeness")),
             "reading": tick(r.get("has_read")),
             "assessment": ai,
             "compare": tick(r.get("has_compare")),
             "challenge": chal}
    # Keyed by REVIEW_STEPS so a step added to the workflow cannot silently vanish from the
    # queue summary — the drift that produced two disagreeing indicators in the first place.
    return " · ".join(f"{QUEUE_LABELS[k]} {marks[k]}" for k in REVIEW_STEPS if k in marks)


def _ai_proposed_clause(d, proposal):
    """How the report describes the assessor's position beside the recorded decision.

    WB-107: this line crashed with KeyError on every decision made through the review
    workspace. It guarded with `d.get('aiSufficiency')` and then read `d['aiSufficiency']`, and
    since `cycle.decide()` never writes that key the guard was always true and the read always
    failed. Only `pipeline.record_decision` sets it, and the app stopped using that path.

    The deeper error is the one the guard was making: `None != 'partial'` was read as "the AI
    proposed something different". Absent is not a value. There are three cases and the report
    now says which — the assessor agreed, the assessor proposed something else, or the assessor
    produced nothing at all. Reporting a failed or missing assessment as a difference of opinion
    would put a disagreement in the record that never happened.
    """
    ai = (d.get("aiSufficiency")
          or (proposal or {}).get("sufficiency"))
    if (proposal or {}).get("model") == "error":
        return " (the assessor call failed — no proposal was produced)"
    if not ai:
        return " (no assessor proposal was recorded)"
    if ai == d.get("sufficiency"):
        return ""
    return f" (AI proposed {ai})"


def _render_contract_block(c, report):
    """The panel shown instead of the review workspace when the contract will not assess."""
    from governance.contract_integrity import blocking_summary, warning_summary
    st.markdown(f"### {c.id} — {c.title}")
    st.error("**CONTRACT INVALID** — assessment not executable for this control.")
    for code, n in sorted(blocking_summary(report).items(), key=lambda kv: -kv[1]):
        st.markdown(f"- **{n} ×** {_CONTRACT_LABELS.get(code, code)}")
    st.caption(
        "This is a defect in the control contract, not in the evidence. Assessing against it "
        "would produce a rating that looks exactly like a sound one, so the assessment does not "
        "run. Repair the contract, or load a workbook whose artefact column has not been "
        "overwritten."
    )
    with st.expander("Every finding, in full"):
        for f in report.get("findings") or []:
            if f.get("severity") == "error":
                st.markdown(f"- `{f['code']}` — {f['message']}")
    warn = warning_summary(report)
    if warn:
        st.warning("**Warnings** — these do not block assessment:\n\n" +
                   "\n".join(f"- {n} × {_CONTRACT_LABELS.get(k, k)}" for k, n in warn.items()))
    if st.button("← Review queue", key=f"blocked_back_{c.key}"):
        st.session_state.pop("sel", None); st.session_state.pop("review_step", None); st.rerun()


def _completeness_docs(ev):
    """Evidence record -> documents for the WB-103 pass, via the same splitter the challenger
    quotes against. One splitter, so completeness and challenge see the same documents."""
    from governance.completeness import chunks_from_evidence
    return chunks_from_evidence(dict(ev or {}))


#: WB-106: the single definition of the review workflow. Both indicators derive from this.
#: Three hand-maintained copies of the step list had drifted apart — the pill row carried seven
#: steps while the strip inside each step carried five, silently dropping Completeness and
#: Challenge. A workflow the UI cannot describe consistently is not a workflow the user can
#: trust, so the list lives here and nowhere else.
REVIEW_STEPS = ["evidence", "completeness", "reading", "assessment", "compare", "challenge",
                "decision"]

#: Short forms for the queue row. Every step except `decision` — which the row already carries
#: as its "Next:" label — must appear here, and a test enforces that.
QUEUE_LABELS = {"evidence": "Evidence", "completeness": "Completeness", "reading": "Read",
                "assessment": "AI", "compare": "Compare", "challenge": "Challenge"}


def _review_step_states(row, current):
    """(label, state) for every step, from one projection of the cycle.

    `state` is 'done', 'now', 'wait' or 'held'. 'held' is the one worth explaining: a step whose
    own work is finished but which is gated behind an upstream step the reviewer has not reached.
    The assessor runs concurrently so the reviewer never waits on it, which previously meant the
    strip showed a green tick on 'AI assessment' while 'Your reading' was still pending — a
    completed step displayed ahead of the step that gates it. It never leaked the rating, but it
    announced that a proposal was ready and had succeeded, which is a nudge toward hurrying the
    reading, and it made the enforced order look broken. 'held' says ready-but-withheld instead.
    """
    ch = row.get("challenge") or {}
    done = {
        "evidence": bool(row.get("has_evidence")),
        # A scan that ran is done, whatever it found: gaps are a result, not an unfinished step.
        "completeness": bool(row.get("has_completeness")),
        "reading": bool(row.get("has_read")),
        "assessment": bool(row.get("has_proposal")) and not row.get("proposal_error"),
        "compare": bool(row.get("has_compare")),
        # A challenge step is done when a challenge pass actually produced a result and nothing
        # is left unresolved. A pass that never ran, or whose output was rejected in validation,
        # is not a clean challenge — it is no challenge, and must not show as complete.
        "challenge": (ch.get("produced_a_result", False)
                      and not (ch.get("unresolved") or ch.get("unresolved_strong"))
                      if row.get("has_compare") else False),
        "decision": bool(row.get("decision")),
    }
    out = []
    for step in REVIEW_STEPS:
        if step == "assessment" and done["assessment"] and not done["reading"]:
            state = "held"
        elif step == "challenge" and ch.get("blocked"):
            state = "blocked"
        elif done[step]:
            state = "done"
        elif step == current:
            state = "now"
        else:
            state = "wait"
        out.append((_review_label(step), state))
    return out


def _review_step_from_action(action):
    anchor = (action or {}).get("anchor")
    return {"evidence": "evidence", "completeness": "completeness", "blind": "reading",
            "ai": "assessment", "compare": "compare", "challenges": "challenge",
            "decision": "decision"}.get(anchor, "summary")


def _review_label(step):
    return {
        "evidence": "Evidence", "completeness": "Completeness", "reading": "Your reading",
        "assessment": "AI assessment", "compare": "Compare", "challenge": "Challenge",
        "decision": "Decision", "summary": "Complete"
    }.get(step, step.title())


def _render_review_progress(row, current):
    marker = {"done": "✓", "now": "→", "held": "⏸", "blocked": "⚠", "wait": "·"}
    colour = {"done": COL["full"], "now": COL["partial"], "held": COL["pending"],
              "blocked": COL["none"], "wait": COL["pending"]}
    parts = [f'<span style="display:inline-block;padding:.38rem .7rem;border-radius:999px;'
             f'background:{colour[state]};color:white;font-size:.78rem;'
             f'margin:0 .18rem .28rem 0">{marker[state]} {label}</span>'
             for label, state in _review_step_states(row, current)]
    st.markdown("".join(parts), unsafe_allow_html=True)
    _states = _review_step_states(row, current)
    if any(state == "held" for _, state in _states):
        st.caption("⏸ The assessor has finished and its proposal is withheld until your reading "
                   "is recorded.")
    if any(state == "blocked" for _, state in _states):
        st.caption("⚠ The challenge pass ran but no challenge survived validation. Your reading "
                   "is unchallenged — this is not the same as nothing being found.")


def _compact_control_header(c, row):
    cid=(S.get("cycle_ids") or {}).get(c.key)
    state=events.state(cid) if cid else {}
    updated=(state.get("updated") or row.get("updated") or "")[:16].replace("T"," ")
    st.markdown(
        f'<div style="padding:.8rem 1rem;border:1px solid rgba(127,127,127,.25);border-radius:.7rem;margin:.2rem 0 .8rem">'
        f'<div style="font-size:1.22rem;font-weight:780">{c.id} · {c.title}</div>'
        f'<div style="opacity:.72;margin-top:.18rem">{c.lib} · Cycle {cid or "not started"} · stage {state.get("stage", row.get("stage","open"))} · updated {updated or "—"}</div>'
        f'</div>', unsafe_allow_html=True)


def _render_evidence_context(c, ev, *, expanded=False):
    """Keep the authoritative evidence visible/readable throughout the review workspace.

    Evidence is read-only here; editing remains on the dedicated Evidence step. This prevents
    the progressive workspace from hiding the very material the reviewer must use for the
    independent reading, comparison, challenge, and decision stages.
    """
    has_text=bool((ev or {}).get("text"))
    has_file=bool((ev or {}).get("file_name") or (ev or {}).get("file_path"))
    if not (has_text or has_file):
        st.warning("No evidence is available for this review yet. Return to Evidence to add it.")
        return

    meta=[]
    if ev.get("source_type"):
        meta.append(str(ev.get("source_type")))
    if ev.get("provider"):
        meta.append(str(ev.get("provider")))
    if ev.get("target_id"):
        meta.append(str(ev.get("target_id")))
    if ev.get("file_name"):
        meta.append(f"file: {ev.get('file_name')}")
    if ev.get("observed_at"):
        meta.append(f"observed: {ev.get('observed_at')}")
    if ev.get("observation_sha256"):
        meta.append(f"sha256: {str(ev.get('observation_sha256'))[:16]}…")

    title="Evidence used for this review" + (f" · {' · '.join(meta)}" if meta else "")
    with st.expander(title, expanded=expanded):
        if has_file:
            st.caption(f"Attached evidence: {ev.get('file_name') or ev.get('file_path')}")
        if has_text:
            st.text_area(
                "Evidence text (read-only)",
                value=str(ev.get("text") or ""),
                height=320 if expanded else 220,
                disabled=True,
                key=f"review_evidence_context_{c.key}_{'open' if expanded else 'closed'}",
            )
        elif has_file:
            st.info("This review uses an attached file. Reopen the Evidence step to replace or inspect the source file.")
        if ev.get("plugin_packet"):
            packet=ev.get("plugin_packet") or {}
            st.caption(f"Locator: {packet.get('locator','—')}")
            if packet.get("excerpt") and packet.get("excerpt") not in str(ev.get("text") or ""):
                st.code(str(packet.get("excerpt"))[:2000])


def _render_review_workspace(c, row):
    # GE-110: contract integrity is checked before the workspace renders, so the reviewer cannot
    # click into an assessment that the engine would refuse anyway. The engine refuses
    # independently — `cycle.assess` and `cycle.record_proposal` both call
    # `assert_contract_executable` — so this panel is the explanation, not the enforcement.
    _report = _contract_report(c)
    if not _report.get("executable", True):
        _render_contract_block(c, _report)
        return
    st.session_state.setdefault("review_step", _review_step_from_action(row["next_action"]))
    step=st.session_state.get("review_step")
    if row["next_action"]["kind"] == "complete" and step not in {"summary","decision"}:
        step="summary"
        st.session_state.review_step=step

    _compact_control_header(c,row)
    _render_uploaded_source_review(c)
    if st.button("← Review queue", key=f"back_queue_{c.key}"):
        st.session_state.pop("sel", None)
        st.session_state.pop("review_step", None)
        st.rerun()

    _render_review_progress(row, step)
    st.caption(f"Next action: **{row['next_action']['label']}**")

    ev=S["evidence"].setdefault(c.key,{})
    blind=S.get("blind",{}).get(c.key)
    a=S.get("ai",{}).get(c.key)
    ch=S.get("challenge",{}).get(c.key)
    diff=S.get("compare",{}).get(c.key)
    d=S.get("decisions",{}).get(c.key)

    # ---------------- Evidence ----------------
    if step == "evidence":
        st.header("Evidence")
        st.caption("Bring in the evidence for this control. Previous stages stay out of the way until this step is complete.")
        source=st.radio("Source",["Manual","File","Plugin"],horizontal=True,key=f"compact_src_{c.key}")
        if source == "Plugin":
            plugins=list_plugins()
            if not plugins:
                st.warning("No plugins are registered.")
            else:
                pcols=st.columns(3)
                pid=pcols[0].selectbox("Plugin",[x["id"] for x in plugins],key=f"compact_plugin_{c.key}")
                target=pcols[1].text_input("Target",value="org/repo",key=f"compact_target_{c.key}")
                branch=pcols[2].text_input("Branch",value="main",key=f"compact_branch_{c.key}")
                if st.button("Collect",key=f"compact_collect_{c.key}",type="primary"):
                    try:
                        plugin=get_plugin(pid)
                        with st.spinner(f"Collecting {pid}…"):
                            obs=plugin.collect({"id":target,"branch":branch})
                        if not obs:
                            st.warning("Plugin returned no observations.")
                        else:
                            rows_obs=[o.to_dict() for o in obs]
                            S.setdefault("plugin_observations",{})[c.key]=rows_obs
                            packets=[observation_to_evidence_packet(o).to_dict() for o in obs]
                            S.setdefault("plugin_packets",{})[c.key]=packets
                            for rr in rows_obs:
                                governance_cycle.record_observation(rr,actor=f"plugin:{pid}",control_id=c.id,framework=c.lib)
                            save_state(); st.rerun()
                    except Exception as exc:
                        st.error(f"Plugin collection failed: {exc}")
            for packet in S.get("plugin_packets",{}).get(c.key,[]):
                st.markdown(f'**{packet.get("title","Plugin observation")}**  \n<small>{packet.get("provider")} · {packet.get("target_id")} · {packet.get("observed_at")} · {packet.get("locator")}</small>',unsafe_allow_html=True)
                st.code(packet.get("excerpt","")[:1200])
                if st.button("Use as evidence",key=f"compact_use_{c.key}_{packet.get('packet_id')}"):
                    ev["text"]=(ev.get("text","")+"\n\n" if ev.get("text") else "")+packet.get("excerpt","")
                    ev.update({"plugin_packet":dict(packet),"source_type":"plugin_observation","provider":packet.get("provider"),"target_id":packet.get("target_id"),"observed_at":packet.get("observed_at"),"observation_id":packet.get("observation_id"),"observation_sha256":packet.get("observation_sha256")})
                    save_state(); st.rerun()
        if source in ("Manual","Plugin"):
            ev["text"]=st.text_area("Evidence",ev.get("text",""),height=220,key=f"compact_evidence_{c.key}",placeholder="Paste or describe the governed evidence.")
        f=st.file_uploader("Attach file",type=["pdf","txt","md","csv","log","json"],key=f"compact_file_{c.key}")
        if f is not None:
            if f.type=="application/pdf":
                (DATA/"evidence").mkdir(exist_ok=True)
                pth=DATA/"evidence"/f"{c.key.replace('::','_').replace('/','-')}_{f.name}"
                pth.write_bytes(f.getvalue()); ev["file_name"],ev["file_path"]=f.name,str(pth)
            else:
                ev["text"]=(ev.get("text","")+"\n\n" if ev.get("text") else "")+f"[{f.name}]\n"+f.getvalue().decode(errors="ignore")[:20000]
        if ev.get("file_name"): st.caption(f"Attached: {ev['file_name']}")
        if st.button("Save evidence & continue →",type="primary",disabled=not bool(ev.get("text") or ev.get("file_path") or ev.get("file_name")),key=f"compact_save_ev_{c.key}"):
            cid=_ensure_cycle(c,ev)
            # WB-103: the completeness pass runs between evidence and the blind read. It is
            # deterministic and returns no rating, so showing it here cannot anchor the reading.
            try:
                governance_cycle.gap_scan(cid, _completeness_docs(ev),
                                          actor=S.get("reviewer","system") or "system")
            except Exception as exc:
                st.warning(f"Completeness scan did not run: {exc}")
            save_state(); st.session_state.review_step="completeness"; st.rerun()

    # ---------------- Completeness (WB-103) ----------------
    elif step == "completeness":
        st.markdown(stages(*_review_step_states(row, "completeness")), unsafe_allow_html=True)
        cid = _ensure_cycle(c, ev)
        comp = (events.state(cid) or {}).get("completeness") or {}
        if not comp:
            if st.button("Run completeness scan", type="primary", key=f"run_comp_{c.key}"):
                governance_cycle.gap_scan(cid, _completeness_docs(ev),
                                          actor=S.get("reviewer", "system") or "system")
                st.rerun()
        else:
            st.subheader("What this bundle is missing")
            st.caption(
                "Deterministic — no model was called. This step reports only which declared "
                "artefacts have no candidate document. It states nothing about whether the "
                "requirement is met, which is why it can be shown before your reading without "
                "influencing it."
            )
            st.markdown(f"**{completeness.headline(comp)}**")
            st.caption(f"{comp.get('documents_scanned', 0)} document(s) scanned · "
                       f"{comp.get('declared_count', 0)} declared artefact(s) · "
                       f"bundle `{comp.get('bundle_hash', '')}`")
            if not comp.get("testable"):
                st.warning(comp.get("not_testable_reason") or "Not testable.")
            _badge = {"present": "✓", "ambiguous": "~", "absent": "✗",
                      "unmatchable": "—", "NOT_TESTABLE": "?"}
            for r in comp.get("artefacts") or []:
                mark = _badge.get(r.get("status"), "·")
                st.markdown(f"{mark}  **{r.get('artefact')}** — `{r.get('status')}`")
                for cand in (r.get("candidates") or [])[:3]:
                    st.caption(f"     {cand.get('where')}: {cand.get('path')} "
                               f"({', '.join(cand.get('matched_terms') or [])})")
                if r.get("reason"):
                    st.caption(f"     {r['reason']}")
            st.caption("✓ named document · ~ mentioned only in a body · ✗ no candidate · "
                       "— declared artefact is a category label, not matchable · ? bundle too thin")

            st.divider()
            st.markdown("**Top up the evidence, or continue**")
            add = st.text_area("Additional evidence", "", height=140,
                               key=f"topup_{c.key}",
                               placeholder="Paste anything the scan says is missing.")
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Add evidence & rescan", disabled=not add.strip(),
                             key=f"topup_btn_{c.key}"):
                    ev["text"] = (ev.get("text", "") + "\n\n" if ev.get("text") else "") + \
                        f"--- Source: reviewer_topup ---\n{add.strip()}"
                    # Re-bind rather than editing silently: the record must show that this
                    # bundle was assembled against a checklist, and which bundle each later
                    # step saw.
                    governance_cycle.rebind_evidence(
                        cid, dict(ev), actor=S.get("reviewer", "system") or "system",
                        reason="added in response to the completeness scan")
                    governance_cycle.gap_scan(cid, _completeness_docs(ev),
                                              actor=S.get("reviewer", "system") or "system")
                    save_state(); st.rerun()
            with col_b:
                if st.button("Continue to my reading →", type="primary",
                             key=f"comp_continue_{c.key}"):
                    st.session_state.review_step = "reading"; st.rerun()
            if comp.get("gaps"):
                st.caption("Open gaps do not block your reading. A gap is a finding about the "
                           "bundle, and recording that you read incomplete evidence is more "
                           "useful than a gate that pushes you to fill boxes.")
        if st.button("← Back to evidence", key=f"comp_back_{c.key}"):
            st.session_state.review_step = "evidence"; st.rerun()

    # ---------------- Reading ----------------
    elif step == "reading":
        _ai = S["ai"].get(c.key)
        st.markdown(stages(*_review_step_states(row, "reading")), unsafe_allow_html=True)
        if not (ev.get("text") or ev.get("file_path")):
            st.session_state.review_step="evidence"; st.rerun()
        _render_evidence_context(c, ev, expanded=True)
        st.header("Your reading")
        st.caption("Your independent view is recorded before the AI proposal is shown.")
        levels=["none","partial","full"]
        k1,k2=st.columns(2)
        b_suff=k1.selectbox("Sufficiency",["—"]+levels,index=0,key=f"compact_bs_{c.key}")
        cap={"—":5,"none":1,"partial":3,"full":5}[b_suff]
        b_mat=k2.selectbox("Maturity",["—"]+list(range(1,cap+1)),index=0,key=f"compact_bm_{c.key}")
        elements=elements_for(c)
        el_state={}
        if elements:
            st.markdown("**Requirement elements — judge these, not the test procedure**")
            suggestions=suggest_element_matches(elements,ev.get("text","")) if ev.get("text") else []
            byid={m["element_id"]:m for m in suggestions}
            from governance.semantic_registry import element_semantics
            for e in elements:
                sem = element_semantics(c.id, c.lib, e["id"]) or {}
                with st.expander(f"{e['id']} · {e['text']}", expanded=True):
                    if sem.get("intent"):
                        st.caption(f"Intent: {sem['intent']}")
                    m1,m2,m3=st.columns(3)
                    m1.write(f"**Verification**\n{sem.get('verification','HUMAN_JUDGEMENT')}")
                    m2.write(f"**Applicability**\n{sem.get('applies_when') or 'Always'}")
                    m3.write(f"**Source**\n{sem.get('source_grounding') or 'Governed contract'}")
                    ee=sem.get("expected_evidence") or []
                    if ee:
                        st.write("**Expected evidence**")
                        for item in ee:
                            st.markdown(f"- {item}")
                    hint=byid.get(e["id"])
                    if hint:
                        st.caption(f"Evidence search candidate: {hint['confidence']}")
                    pick=st.radio("Your element judgement",["—","met","not evidenced","n/a"],index=0,horizontal=True,key=f"compact_verdict_{c.key}_{e['id']}")
                    el_state[e["id"]]={"—":"unset","met":"met","not evidenced":"not_evidenced","n/a":"not_applicable"}[pick]
        b_reason=st.text_area("Which rule or missing element decided it?",key=f"compact_reason_{c.key}",placeholder="Name the element satisfied or the gap shown.")
        b_amb=st.checkbox("Ambiguous — cannot be decided from this evidence",key=f"compact_amb_{c.key}")
        # One source of truth for "is there anything to read". Previously this condition was
        # recomputed inline on the button's disabled state, so the guard and the control could
        # drift apart.
        has_ev = bool(ev.get("text") or ev.get("file_path"))
        if blind:
            st.info(f"Recorded reading: {blind['sufficiency']} · maturity {blind['maturity']}/5. Reopen it from the review summary if you need to change it.")
        else:
            st.caption("Your own reading is recorded before anything a model produces is shown. "
                       "Saving it starts the independent assessment. "
                       "The proposal is withheld until your reading is recorded.")
            if st.button("Save my reading",type="primary",disabled=not has_ev,key=f"compact_save_read_{c.key}"):
                err=reason_error(b_reason,rating=b_suff)
                if not S.get("reviewer","").strip(): st.error("Set a reviewer name in the sidebar.")
                elif b_suff=="—" or b_mat=="—": st.error("Choose a sufficiency and a maturity.")
                elif err: st.error(err)
                else:
                    S["blind"][c.key]={"sufficiency":b_suff,"maturity":int(b_mat),"reason":b_reason.strip(),"ambiguous":b_amb,"labelled_by":S["reviewer"].strip(),"labelled_on":dt.datetime.now().isoformat(timespec="seconds"),"element_verdicts":[{"element_id":k,"status":v} for k,v in el_state.items()]}
                    cid=_ensure_cycle(c,ev); governance_cycle.record_read(cid,dict(S["blind"][c.key]),actor=S["reviewer"].strip())
                    # Saving the reading triggers the independent assessment. The reading itself is
                    # never passed to propose() — only the control and the evidence are, so the
                    # assessor cannot be anchored by the conclusion it is about to be compared with.
                    if not S["ai"].get(c.key) or is_error(S["ai"].get(c.key)):
                        S.setdefault("ai_status",{})[c.key]="running"; save_state()
                        with st.spinner("AI is independently assessing the evidence…"):
                            try:
                                pdf=Path(ev["file_path"]).read_bytes() if ev.get("file_path") else None
                                S["ai"][c.key] = propose(c, ev, pdf)
                                S["ai_status"][c.key]="error" if is_error(S["ai"].get(c.key)) else "ready"
                                S["decisions"].pop(c.key,None)
                                governance_cycle.check_bundle_unchanged(cid, dict(ev))
                                governance_cycle.record_proposal(cid,S["ai"][c.key],model=S["ai"][c.key].get("model"),assessment_identity=S.get("assessment_identity"))
                            except Exception as exc:
                                S["ai"][c.key]={"model":"error","error":str(exc)}; S["ai_status"][c.key]="error"
                    save_state(); st.session_state.review_step="assessment"; st.rerun()
        if not has_ev:
            st.caption("Add evidence on the previous step before recording a reading. A reading "
                       "with no evidence behind it cannot be compared or challenged.")
        if blind and a is None:
            st.caption("AI assessment has not completed yet.")

    # ---------------- Assessment ----------------
    elif step == "assessment":
        if not blind:
            st.session_state.review_step="reading"; st.rerun()
        _decided = bool(S["decisions"].get(c.key))
        st.markdown(stages(*_review_step_states(row, "assessment")), unsafe_allow_html=True)
        _render_evidence_context(c, ev, expanded=False)
        st.header("AI assessment")
        if not a:
            st.info("The AI assessment is not ready yet.")
            if st.button("Retry assessment",type="primary",key=f"compact_retry_ai_{c.key}"):
                with st.spinner("AI is independently assessing the evidence…"):
                    try:
                        cid=_ensure_cycle(c,ev); pdf=Path(ev["file_path"]).read_bytes() if ev.get("file_path") else None
                        S["ai"][c.key]=propose(c,ev,pdf); S.setdefault("ai_status",{})[c.key]="error" if is_error(S["ai"][c.key]) else "ready"
                        governance_cycle.check_bundle_unchanged(cid, dict(ev))
                        governance_cycle.record_proposal(cid,S["ai"][c.key],model=S["ai"][c.key].get("model"),assessment_identity=S.get("assessment_identity"))
                        save_state(); st.rerun()
                    except Exception as exc:
                        st.error(f"AI assessment failed: {exc}")
        elif is_error(a):
            st.error("The AI assessment failed; no AI rating was produced.")
            err_text = str(a.get("error") or "Unknown assessor error")
            st.code(err_text, language="text")
            provider = PROVIDER
            model = model_name()
            st.caption(f"Provider: {provider} · Model: {model}")
            if provider == "ollama":
                st.info(
                    "For Ollama, verify the local service is running and the configured model is pulled. "
                    "The retry below makes a new assessor call; it does not reuse the failed result."
                )
            if st.button("Retry assessment",type="primary",key=f"compact_retry_ai2_{c.key}"):
                with st.spinner("Retrying independent AI assessment…"):
                    try:
                        cid=_ensure_cycle(c,ev)
                        pdf=Path(ev["file_path"]).read_bytes() if ev.get("file_path") else None
                        S["ai"][c.key]=propose(c,ev,pdf)
                        S.setdefault("ai_status",{})[c.key]="error" if is_error(S["ai"][c.key]) else "ready"
                        if not is_error(S["ai"][c.key]):
                            governance_cycle.check_bundle_unchanged(cid, dict(ev))
                            governance_cycle.record_proposal(cid,S["ai"][c.key],
                                                             model=S["ai"][c.key].get("model"),
                                                             assessment_identity=S.get("assessment_identity"))
                            save_state(); st.session_state.review_step="assessment"; st.rerun()
                        save_state()
                    except Exception as exc:
                        S["ai"][c.key]={"status":"error","model":"error","error":f"{type(exc).__name__}: {exc}"}
                        S.setdefault("ai_status",{})[c.key]="error"
                        save_state(); st.error(f"Retry failed: {type(exc).__name__}: {exc}")
        else:
            _show_knowledge_trace(c.id, "assessor")
            st.markdown(f'{pill(a["sufficiency"])} maturity {a["proposedMaturity"]}/5 · <small>{a.get("model","")}</small>',unsafe_allow_html=True)
            st.write(a.get("rationale", ""))
            if a.get("excerpt"): st.markdown(f"> *{a['excerpt']}*")
            if a.get("elementVerdicts"):
                st.markdown("**Element assessment**")
                sems = {e.get("id"): e for e in elements_for(c)}
                for v in a.get("elementVerdicts") or []:
                    eid=v.get("element_id")
                    label=sems.get(eid,{}).get("text", eid)
                    status=str(v.get("status","unset")).replace("_"," ")
                    icon={"met":"✓","not evidenced":"✗","not applicable":"—","unset":"·"}.get(status,"·")
                    st.markdown(f"{icon} **{eid}** — {label} · `{status}`")
                    if v.get("excerpt"):
                        st.caption(f"Evidence: {v['excerpt']}")
            if a.get("supplemental_assessor_notes"):
                with st.expander("Assessor diagnostics (not governed findings)"):
                    for note in a.get("supplemental_assessor_notes"):
                        st.caption(note)
            if a.get("gaps"):
                if a.get("requirement_is_draft"):
                    st.warning("The requirement elements for this control are **draft** — derived "
                               "from the control library rather than authored against the source "
                               "instrument, and for many controls they restate the control title. "
                               "Element verdicts and the comparison carry no more authority than "
                               "the elements do.")
                st.markdown("**Gaps**")
                for g in a.get("gaps", []): st.markdown(f"- {g}")
            if a.get("remediation"):
                st.markdown("**Suggested actions**")
                for x in a["remediation"]: st.markdown(f"- {x}")
            if a.get("flags"):
                for fl in a["flags"]: st.warning(f"Validation: {fl}")
            st.success("AI output is now visible because your independent reading is already recorded.")
            if st.button("Continue to comparison →",type="primary",key=f"compact_to_compare_{c.key}"):
                st.session_state.review_step="compare"; st.rerun()

    # ---------------- Compare ----------------
    elif step == "compare":
        if not blind or not a or is_error(a):
            st.session_state.review_step="assessment"; st.rerun()
        _render_evidence_context(c, ev, expanded=False)
        st.header("Compare")
        diff=compare_reads(blind,a,c); S.setdefault("compare",{})[c.key]=diff
        cid=_ensure_cycle(c,ev)
        if not any(e.get("kind")=="compared" for e in events.cycle(cid)):
            governance_cycle.record_compare(cid,diff)
        st.markdown(compare_headline(diff))
        if diff.get("summary"):
            s=diff["summary"]; p1,p2,p3=st.columns(3)
            p1.metric("Compared", s.get("n_compared", 0)); p2.metric("Agreements", s.get("n_agree", s.get("agreements", 0))); p3.metric("Agreement", f'{s.get("agreement_rate"):.0%}' if s.get("agreement_rate") is not None else "—")
        if diff.get("rows"):
            sym={"met":"met","not_evidenced":"not evidenced","not_applicable":"n/a","unset":"—"}
            st.dataframe([{"Element":r["element_id"],"You":sym.get(r["reviewer"],r["reviewer"]),"AI":sym.get(r["ai"],r["ai"]),"Match":"✓" if r["agree"] else "✗" if r["compared"] else "·"} for r in diff["rows"]],hide_index=True,width="stretch")
        if diff.get("disagreements"):
            st.warning(f"{len(diff['disagreements'])} element disagreement(s) found. The next stage can challenge this disagreement.")
        if st.button("Continue to challenge →",type="primary",key=f"compact_to_challenge_{c.key}"):
            st.session_state.review_step="challenge"; st.rerun()

    # ---------------- Challenge ----------------
    elif step == "challenge":
        if not blind:
            st.session_state.review_step="reading"; st.rerun()
        _render_evidence_context(c, ev, expanded=False)
        st.header("Challenge")
        st.caption("The challenger asks questions; it does not rate and cannot turn into the recorded decision.")
        if not ch:
            if st.button("Challenge my reading",type="primary",key=f"compact_challenge_{c.key}"):
                with st.spinner("Challenging…"):
                    try:
                        out=run_challenge(c,ev.get("text",""),blind)
                        record={"challenger_model":out.get("model"),"reasoning_schema":out.get("reasoning_schema"),"overall_reasoning":out.get("overall_reasoning",""),"challenges":out.get("challenges") or [],"sharpest":out.get("sharpest",""),"unaddressed":out.get("unaddressed") or [],"knowledge":out.get("knowledge") or [],"reviewer_claims":out.get("reviewer_claims") or [],"reviewer_claim_vet_status":out.get("reviewer_claim_vet_status"),"reviewer_claim_vet_error":out.get("reviewer_claim_vet_error"),"validation_status":out.get("validation_status","ok"),"validation_error":out.get("validation_error"),"produced_a_result":bool(out.get("produced_a_result", out.get("validation_status") != "blocked")),"shown_on":dt.datetime.now().isoformat(timespec="seconds"),"shown_to":S["reviewer"].strip(),"changed":False}
                        cid=_ensure_cycle(c,ev)
                        if record.get("validation_status") == "blocked":
                            # A transport/validation failure is itself a governed challenge result.
                            # Record it so the decision engine can distinguish blocked from never-run.
                            S["challenge"][c.key]=record
                            governance_cycle.record_challenge(cid,record)
                            save_state(); st.rerun()
                        dossier=create_dossier(control_id=c.key,control_title=c.title,reviewer=S["reviewer"],blind=blind,challenges=record["challenges"],challenger_model=record["challenger_model"],knowledge=record["knowledge"],reasoning_schema=record["reasoning_schema"],assessment_id=(S.get("assessment_identity") or {}).get("assessment_id"),validation_status=record.get("validation_status",""))
                        append_dossier(dossier); record["dossier"]=dossier; S["challenge"][c.key]=record
                        governance_cycle.record_challenge(cid,record)
                        save_state(); st.rerun()
                    except Exception as exc:
                        # Last-resort UI containment. Normal transport timeouts are returned by
                        # challenge() as a blocked envelope, so this branch is only for unexpected
                        # application errors.
                        st.error(f"The challenger could not complete ({type(exc).__name__}). No challenge was admitted. {exc}")
        else:
            if ch.get("validation_status") == "blocked":
                st.warning("**Challenge unavailable — your reading remains unchallenged.**")
                err = ch.get("validation_error") or "The challenger did not complete."
                st.code(str(err), language="text")
                st.caption("This is recorded as a blocked challenge run; it is not the same as a clean run that found nothing.")
                if st.button("Retry challenge", type="primary", key=f"retry_challenge_{c.key}"):
                    S.get("challenge", {}).pop(c.key, None)
                    st.rerun()
                _show_knowledge_trace(c.id, "challenger")
                st.stop()
            _show_knowledge_trace(c.id, "challenger")
            if ch.get("reviewer_claim_vet_status")=="ok":
                st.caption(f"Reviewer-read claim vetting: {len(ch.get('reviewer_claims') or [])} material claim(s) decomposed.")
            if ch.get("overall_reasoning"): st.write(ch["overall_reasoning"])
            if ch.get("sharpest"): st.success(ch["sharpest"])
            if ch.get("knowledge"): st.caption("Governance knowledge consulted: "+", ".join(m.get("memory_id","?") for m in ch["knowledge"]))
            dossier=ch.get("dossier") or {}
            responses={x.get("challenge_no"):x.get("response") for x in dossier.get("challenges",[])}
            for idx,q in enumerate(ch.get("challenges",[]),1):
                with st.expander(f'Challenge {idx} · {str(q.get("severity","medium")).upper()} · {q.get("challenge_strength","weak")}',expanded=False):
                    st.write(q.get("challenge",""))
                    if q.get("observation"): st.caption(q["observation"])
                    if q.get("evidence_basis"):
                        st.markdown("**Evidence basis**")
                        for x in q["evidence_basis"]: st.markdown(f"- {x}")
                    if q.get("requirement_basis"):
                        st.markdown("**Requirement basis**")
                        for x in q["requirement_basis"]: st.markdown(f"- {x}")
                    fp=q.get("factual_pointer") or {}
                    if fp.get("quote"): st.code(f"{fp.get('source','?')} · {fp.get('locator','?')}\n{fp.get('quote','')}")
                    if q.get("risk_to_address"): st.markdown(f"**Risk:** {q['risk_to_address']}")
                    if q.get("resolution_pointer"): st.markdown(f"**Resolve with:** {q['resolution_pointer']}")
                    existing=responses.get(idx)
                    if existing:
                        st.success(f"Response: {existing.get('disposition','?')} — {existing.get('note','')}")
                    else:
                        disp=st.selectbox("Disposition",["accept","reject","evidence_provided","escalate"],key=f"compact_cd_disp_{c.key}_{idx}")
                        note=st.text_area("Response / reasoning",key=f"compact_cd_note_{c.key}_{idx}")
                        evidence_text=st.text_area("Evidence supplied (optional)",key=f"compact_cd_ev_{c.key}_{idx}")
                        if st.button("Record response",key=f"compact_cd_save_{c.key}_{idx}"):
                            try:
                                updated=respond_to_challenge(dossier,idx,response=disp,reviewer=S["reviewer"],note=note,evidence=[evidence_text] if evidence_text.strip() else [])
                                append_dossier(updated); ch["dossier"]=updated
                                cid=_ensure_cycle(c,ev); rr=dict(updated.get("challenges",[])[idx-1].get("response") or {}) if len(updated.get("challenges",[]))>=idx else {}
                                rr.update({"challenge_no":idx,"disposition":disp,"note":note,"evidence":[evidence_text] if evidence_text.strip() else []})
                                target=(ch.get("challenges") or [])[idx-1] if len(ch.get("challenges") or [])>=idx else {}; rr["challenge_id"]=target.get("challenge_id")
                                governance_cycle.record_note(cid,{"challenge_responses":[rr]},actor=S["reviewer"].strip())
                                save_state(); st.rerun()
                            except ValueError as exc: st.error(str(exc))
            if ch.get("unaddressed"): st.warning("Unaddressed requirement elements: "+", ".join(ch["unaddressed"]))
            st.caption(f"Challenge dossier: {dossier.get('dossier_id','—')} · status: {dossier.get('status','open')}")
        diff=S.get("compare",{}).get(c.key)
        if diff and diff.get("disagreements"):
            ch2=S.get("challenge2",{}).get(c.key)
            if not ch2 and st.button(f"Challenge the disagreement ({len(diff['disagreements'])})",key=f"compact_ch2_{c.key}"):
                try:
                    with st.spinner("Challenging the disagreement…"):
                        out2=run_challenge2(c,ev.get("text",""),blind,a,diff)
                    S.setdefault("challenge2",{})[c.key]={"challenger_model":out2.get("model"),"reasoning_schema":out2.get("reasoning_schema"),"overall_reasoning":out2.get("overall_reasoning",""),"challenges":out2.get("challenges") or [],"sharpest":out2.get("sharpest",""),"scope_elements":out2.get("scope_elements") or [],"out_of_scope_dropped":out2.get("out_of_scope_dropped",0),"supports_tally":out2.get("supports_tally") or {},"challenge_outcome":out2.get("challenge_outcome"),"diff_sha":out2.get("diff_sha"),"at":dt.datetime.now().isoformat(timespec="seconds")}
                    save_state(); st.rerun()
                except Exception as exc: st.error(f"The disagreement challenge failed ({type(exc).__name__}) — nothing was recorded. {exc}")
        if st.button("Continue to decision →",type="primary",key=f"compact_to_decision_{c.key}"):
            st.session_state.review_step="decision"; st.rerun()

    # ---------------- Decision ----------------
    elif step == "decision":
        if not blind:
            st.session_state.review_step="reading"; st.rerun()
        _render_evidence_context(c, ev, expanded=False)
        st.header("Decision")
        if d:
            st.success(f"Decision recorded: {d.get('sufficiency')} · maturity {d.get('maturity')}/5")
            st.caption(f"Recorded by {d.get('reviewer')} · {str(d.get('at',''))[:16].replace('T',' ')}")
            if d.get("note"): st.write(d["note"])
            if st.button("Return to queue",type="primary",key=f"compact_done_{c.key}"):
                st.session_state.pop("sel",None); st.session_state.pop("review_step",None); st.rerun()
        else:
            levels=["none","partial","full"]
            k1,k2=st.columns(2)
            suff=k1.selectbox("Sufficiency",levels,index=levels.index(blind["sufficiency"]),key=f"compact_dec_suff_{c.key}")
            mat=k2.selectbox("Maturity",[1,2,3,4,5],index=blind["maturity"]-1,key=f"compact_dec_mat_{c.key}")
            note=st.text_area("Which rule or missing element decided it?",value=blind["reason"],key=f"compact_dec_note_{c.key}")
            moved=suff!=blind["sufficiency"] or mat!=blind["maturity"]
            try:
                preview=_decision_preview(c,blind,suff,mat,note)
                p1,p2=st.columns([1,3]); p1.metric("Posture",str(preview.get("posture","—")).title())
                if preview.get("decision_eligible"): p2.success("Eligible — no hard governance blocker detected.")
                else: p2.error("Blocked — "+", ".join(preview.get("blockers") or ["UNKNOWN_BLOCKER"]))
                if preview.get("escalations"): st.warning("Escalation signals: "+", ".join(preview["escalations"]))
            except Exception as exc: st.caption(f"Decision preview unavailable: {exc}")
            if st.button("Record decision",type="primary",key=f"compact_record_decision_{c.key}"):
                if not S.get("reviewer","").strip():
                    st.error("Set a reviewer name in the sidebar.")
                else:
                    err=reason_error(note,rating=suff,revised=moved,previous=blind["reason"])
                    if err: st.error(err)
                    else:
                        try:
                            cid=_ensure_cycle(c,ev)
                            rec=governance_cycle.decide(cid,sufficiency=suff,maturity=mat,reason=note,reviewer=S["reviewer"].strip(),action="accept")
                            rec["blind"]=dict(blind); rec["assessor_shown"]=bool(a); rec["challenged"]=bool(ch); dif=S.get("compare",{}).get(c.key)
                            if dif: rec["element_diff"]={"comparable":dif.get("comparable"),"reason":dif.get("reason"),"summary":dif.get("summary"),"rating":dif.get("rating"),"disagreements":dif.get("disagreements"),"diff_sha":dif.get("diff_sha"),"rows":[{k:x[k] for k in ("element_id","reviewer","ai","agree","direction")} for x in (dif.get("rows") or [])]}
                            ch2=S.get("challenge2",{}).get(c.key); rec["challenged_disagreement"]=bool(ch2)
                            if ch2: rec["disagreement_challenge"]={"challenger_model":ch2.get("challenger_model"),"scope_elements":ch2.get("scope_elements"),"supports_tally":ch2.get("supports_tally"),"challenge_outcome":ch2.get("challenge_outcome"),"diff_sha":ch2.get("diff_sha")}
                            if moved:
                                rec["supersedes"]={k:blind[k] for k in ("sufficiency","maturity","reason")}; rec["revised_after_assessor"]=bool(a); rec["revised_after_challenge"]=bool(ch); rec["revised_after_compare"]=bool(dif and dif.get("comparable")); rec["revised_after_disagreement_challenge"]=bool(ch2)
                            S["decisions"][c.key]=rec; _sync_authoritative_decisions(); save_state(); st.session_state.review_step="summary"; st.rerun()
                        except ValueError as exc: st.error(str(exc))

    # ---------------- Completion ----------------
    elif step == "summary":
        st.header("Review complete")
        if d:
            st.success(f"Recorded decision: {d.get('sufficiency')} · maturity {d.get('maturity')}/5")
            st.caption(f"Cycle {(S.get('cycle_ids') or {}).get(c.key,'—')} · reviewer {d.get('reviewer','—')} · {str(d.get('at',''))[:16].replace('T',' ')}")
            if d.get("note"): st.write(d["note"])
        nxt=next((x for x in build_queue(in_scope,cycle_states=_cycle_states(),cache=S) if x["next_action"]["kind"]!="complete" and x["key"]!=c.key),None)
        if nxt and st.button(f"Next pending: {nxt['control_id']} →",type="primary",key=f"compact_next_{c.key}"):
            st.session_state.sel=nxt["key"]; st.session_state.review_step=_review_step_from_action(nxt["next_action"]); st.rerun()
        if st.button("Return to review queue",key=f"compact_queue_done_{c.key}"):
            st.session_state.pop("sel",None); st.session_state.pop("review_step",None); st.rerun()


def _show_knowledge_trace(control_id: str, role: str | None = None):
    try:
        from governance.knowledge_monitor import latest as latest_knowledge_usage
        row = latest_knowledge_usage(control_id=control_id, role=role)
        if not row:
            st.caption("Knowledge: no runtime retrieval recorded yet.")
            return
        local = row.get("local") or {}; testing = row.get("control_testing") or {}; web = row.get("internet") or {}
        parts = [f"Local {len(local.get('memory_ids') or [])}",
                 f"Testing KB {len(testing.get('controls') or [])}",
                 f"Internet findings {len(web.get('sources') or [])}"]
        if web.get("attempted") and not web.get("used"):
            parts.append("web attempted / no findings")
        elif not web.get("attempted"):
            parts.append("web not attempted")
        st.info("Knowledge runtime · " + " · ".join(parts))
        with st.expander("What was actually consulted", expanded=False):
            st.json(row)
    except Exception as exc:
        st.caption(f"Knowledge trace unavailable: {type(exc).__name__}: {exc}")


def _render_review_queue():
    cycle_states=_cycle_states(); queue=build_queue(in_scope,cycle_states=cycle_states,cache=S)
    pending=[r for r in queue if r["next_action"]["kind"]!="complete"]
    done=len(queue)-len(pending)
    st.subheader("Review")
    q1,q2,q3=st.columns(3); q1.metric("In scope",len(queue)); q2.metric("Need action",len(pending)); q3.metric("Completed",done)
    if not queue:
        st.info("No controls are currently in scope."); return
    st.caption("Choose a control and the app will present one task at a time. Completed steps collapse into a summary so the next action stays visible.")
    q_filter=st.multiselect("Show",["Needs action","Completed","Strong challenges","No evidence"],default=["Needs action"],key="review_compact_filter")
    shown=[]
    for r in queue:
        matches=[]
        if "Needs action" in q_filter and r["next_action"]["kind"]!="complete": matches.append(True)
        if "Completed" in q_filter and r["next_action"]["kind"]=="complete": matches.append(True)
        if "Strong challenges" in q_filter and r["challenge"]["unresolved_strong"]: matches.append(True)
        if "No evidence" in q_filter and not r["has_evidence"]: matches.append(True)
        if matches: shown.append(r)
    # GE-110: flag blocked contracts on the rows actually rendered, not on all 195. The status
    # is cached per control, but assembling a contract is a file read and the queue redraws on
    # every interaction.
    _by_key = {c.key: c for c in in_scope}
    for r in shown[:50]:
        _c = _by_key.get(r["key"])
        r["contract_blocked"] = (not _contract_report(_c).get("executable", True)) if _c else False
        a1,a2,a3=st.columns([4.8,3.2,1.2])
        a1.markdown(f'**{r["control_id"]} · {r["title"]}**  \n<small>{r["library"]} · Cycle {r["cycle_id"] or "not started"}</small>',unsafe_allow_html=True)
        _c = next((x for x in in_scope if x.key == r["key"]), None)
        if _c is not None:
            r["contract_blocked"] = not _contract_report(_c).get("executable", True)
        label = "Contract invalid" if r.get("contract_blocked") else r["next_action"]["label"]
        if r["challenge"]["unresolved_strong"] and not r.get("contract_blocked"):
            label += " · strong blocker"
        a2.markdown(f'**Next:** {label}  \n<small>{_queue_markers(r)}</small>', unsafe_allow_html=True)
        if a3.button("Open",key=f"compact_open_{r['key']}",type="primary" if r["next_action"]["kind"]!="complete" else "secondary"):
            st.session_state.sel=r["key"]; st.session_state.review_step=_review_step_from_action(r["next_action"]); st.rerun()


# ---------- Review ----------
with tab_a:
    if not controls:
        st.info("Load a playbook workbook to use this tab.")
    elif st.session_state.get("sel") in by_key:
        current_key=st.session_state["sel"]; current_control=by_key[current_key]
        current_row=next((r for r in build_queue(in_scope,cycle_states=_cycle_states(),cache=S) if r["key"]==current_key),None)
        if current_row:
            _render_review_workspace(current_control,current_row)
        else:
            st.session_state.pop("sel",None); st.rerun()
    else:
        _render_review_queue()

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
                   f"- Rating: {d['sufficiency']}, maturity {d['maturity']}/5 — recorded by {d['reviewer']} on {d['at'][:10]}"
                   + _ai_proposed_clause(d, a),
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
    st.subheader("Knowledge runtime monitor")
    st.caption("Runtime trace for assessor/challenger retrieval. LOCAL and TESTING KB are internal advisory channels; INTERNET findings are live external context. Retrieval never becomes an organisational evidence item or a decision.")
    try:
        from governance.knowledge_monitor import read as read_knowledge_usage, summary as knowledge_usage_summary
        km = knowledge_usage_summary()
        k1,k2,k3,k4,k5 = st.columns(5)
        k1.metric("Retrievals", km["runs"])
        k2.metric("Local used", km["local_runs"])
        k3.metric("Testing KB used", km["testing_runs"])
        k4.metric("Internet findings", km["internet_findings"])
        k5.metric("Web attempts", km["internet_attempts"])
        rows_k = read_knowledge_usage(100)
        if not rows_k:
            st.info("No assessor/challenger knowledge retrieval has been recorded yet.")
        else:
            def _channels(r):
                ch=[]
                if (r.get("local") or {}).get("used"): ch.append("LOCAL")
                if (r.get("control_testing") or {}).get("used"): ch.append("TESTING KB")
                if (r.get("internet") or {}).get("used"): ch.append("INTERNET")
                return " + ".join(ch) if ch else "NONE FOUND"
            view=[]
            for r in reversed(rows_k):
                web=r.get("internet") or {}; local=r.get("local") or {}; testing=r.get("control_testing") or {}
                view.append({
                    "Time": str(r.get("ts", ""))[:19].replace("T", " "),
                    "Role": r.get("role", ""),
                    "Control": f"{r.get('framework','')} {r.get('control_id','')}".strip(),
                    "Channel(s)": _channels(r),
                    "Local memories": ", ".join(local.get("memory_ids") or []) or "—",
                    "Testing KB": ", ".join(testing.get("controls") or []) or "—",
                    "Web findings": len(web.get("sources") or []),
                    "Web status": "findings" if web.get("used") else ("attempted / none" if web.get("attempted") else "not attempted"),
                })
            st.dataframe(view, width="stretch", hide_index=True)
            with st.expander("Latest runtime trace", expanded=True):
                st.json(rows_k[-1])
    except Exception as exc:
        st.warning(f"Knowledge monitor unavailable: {type(exc).__name__}: {exc}")

    st.divider()
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
            # Maturity is rendered as text, not as a number. Mixing ints with the "—"
            # placeholder in one column gave pyarrow an unconvertible object column and a
            # traceback on every render; coercing the other way is worse, because pandas turns
            # int-plus-missing into float64 and the table would show "3.0" for maturity 3.
            #
            # A numeric column would also have to represent "not assessed" as NaN, which is the
            # absent-versus-value collapse this project refuses everywhere else. Maturity here is
            # an ordinal label in a display table, 1 to 5, so string sorting is well behaved and
            # "not assessed" stays visibly distinct from any rating.
            st.dataframe([{"Control": f"{c['id']} {c['title'][:70]}", "Library": c["lib"],
                           "Design rating": (c["rating"] or "not assessed") + ("" if c["recorded"] or not c["rating"] else " (proposed)"),
                           "Maturity": str(c["maturity"]) if c["maturity"] else "—"}
                          for c in v["controls"]], width="stretch", hide_index=True)
        else:
            st.caption("None of this play's controls are in the selected scope.")


# ---- Step 8: per-use-case lifecycle cards (judge proposes, reviewer decides) ----
with tab_l:
    if plays:
        st.markdown("---")
        import lifecycle_cards
        lifecycle_cards.render(plays, st.session_state.get("index"), latest_lane_b())


# ---------------------------------------------------------------- Measurement (GE-110b.5)

with tab_m:
    st.subheader("Measurement runs")
    st.caption(
        "A projection of the stored MeasurementRun record. Every figure below is read from the "
        "run; nothing on this page is recalculated, because a UI that recomputes a metric can "
        "disagree with the record it claims to display."
    )
    try:
        from eval.evaluators import load_runs
        _runs = load_runs()
    except Exception as exc:
        _runs, = [], 
        st.warning(f"Could not load runs: {exc}")

    if not _runs:
        st.info("No measurement runs recorded yet.")
    else:
        _labels = [f"{r['evaluator']} · labels {r['lineage']['labelset_sha'][:8]} · "
                   f"evaluator {r['lineage']['evaluator_sha'][:8]}" for r in _runs]
        _sel = st.selectbox("Run", range(len(_runs)), format_func=lambda i: _labels[i],
                            key="measurement_run_pick")
        r = _runs[_sel]
        lin = r["lineage"]

        st.markdown("**Lineage**")
        l1, l2, l3, l4 = st.columns(4)
        l1.metric("Contract", lin["contract_sha"][:12])
        l2.metric("Corpus", lin["corpus_sha"][:12])
        l3.metric("Labels", lin["labelset_sha"][:12])
        l4.metric("Evaluator", lin["evaluator_sha"][:12])
        st.caption(f"cases {', '.join(lin['cases'])} · {lin['n_elements']} element(s) · "
                   f"{lin['n_judgements']} adjudicated judgement(s)")

        st.divider()
        m1, m2, m3 = st.columns(3)
        m1.metric("Scored judgements", r["n_scored"])
        _acc = r.get("element_accuracy")
        m2.metric("Element accuracy", f"{_acc:.1%}" if _acc is not None else "not computed")
        _margin = r.get("margin_over_strongest_trivial")
        m3.metric(f"Margin over {r.get('strongest_trivial_strategy') or 'baseline'}",
                  f"{_margin:+.3f}" if _margin is not None else "—")
        st.caption(
            f"excluded as not applicable (gold n/a): {r['n_excluded_not_applicable']}"
            + (f" · declined {r['n_declined']}" if r.get("n_declined") else "")
            + (f" · no answer {r['n_no_answer']}" if r.get("n_no_answer") else "")
            + f" · baseline population: {r.get('baseline_population', 'unrecorded')}"
        )
        if r.get("evaluator_errors"):
            st.warning(f"{len(r['evaluator_errors'])} judgement(s) raised in the evaluator and "
                       f"are recorded as unanswered, not as wrong answers.")

        if r.get("aggregate_not_computed"):
            st.error("**Aggregate outcome — NOT COMPUTED**\n\n" + r["aggregate_not_computed"])

        st.markdown("**Limitations travelling with this result**")
        st.caption("Each names the claim it blocks. They are attached to the result rather than "
                   "folded into the score.")
        for _l in r.get("limitations") or []:
            st.markdown(f"- **{_l['code']}** — blocks {_l['blocks']}  \n"
                        f"  <small>{_l['detail']}</small>", unsafe_allow_html=True)

        with st.expander("Per-element accuracy"):
            for _eid, _p in sorted((r.get("per_element") or {}).items(),
                                   key=lambda kv: (kv[1]["accuracy"] is None, kv[1]["accuracy"])):
                st.markdown(f"`{_eid}`  {_p['accuracy']:.0%} over {_p['n']} judgement(s)")

        with st.expander("Baselines"):
            for _k, _v in sorted((r.get("baselines") or {}).items()):
                st.markdown(f"{_k}: {_v:.1%}")
            st.caption("Descriptive. There is no pass mark here; the comparison is the reader's.")


# ---------------------------------------------------------------- Governance Engine / GE-116

with tab_e:
    st.subheader("Governance engine")
    st.caption(
        "Thin UI projection. Services coordinate the governed engine; this page does not define "
        "predicates, calculate verdicts, or decide what blocks."
    )
    if not in_scope:
        st.info("Load a playbook workbook to use the governance engine.")
    else:
        _eng_control_key = st.selectbox("Control", [c.key for c in in_scope], key="engine_control")
        _eng_control = by_key[_eng_control_key]
        _raw_obs = (S.get("plugin_observations") or {}).get(_eng_control_key) or []
        _eng_obs = []
        for _row in _raw_obs:
            try:
                _eng_obs.append(Observation(**_row))
            except Exception:
                continue
        _available_caps = sorted({cap for pl in list_plugins() for cap in (pl.get("capabilities") or [])})
        render_governance_engine(
            st,
            control=_eng_control,
            service=type("GovernanceService", (), {
                "Resource": Resource,
                "verification_plan": staticmethod(governance_service.verification_plan),
                "deterministic_evaluate": staticmethod(governance_service.deterministic_evaluate),
            }),
            observations=_eng_obs,
            capabilities=_available_caps,
        )
