import datetime as dt
import json
import os
from pathlib import Path

import streamlit as st

from assessor import PROVIDER, model_name
from scanner import signals_for
from pipeline import (build_evidence, control_history, export_playbook, gap_analysis, index_folder, list_bundles, load_bundle,
                      match_controls, open_items, propose, record_decision, run_audit, sign_result, unsign_result,
                      latest_lane_b, lifecycle_view)
from plays import load_plays
from caa.review import DISPOSITIONS
from playbook import LIBRARIES, load_controls

DATA = Path("data")
DATA.mkdir(exist_ok=True)
STATE_FILE = DATA / "assessments.json"
DEFAULT_PLAYBOOK = next(DATA.glob("*.xlsx"), None)

st.set_page_config(page_title="AI governance readiness workbench", layout="wide")
st.markdown("""<style>
h1,h2,h3{font-family:Cambria,Georgia,serif}
.req{background:#F3F7FB;border-left:3px solid #16324F;padding:8px 12px;margin:6px 0 10px}
.pill{display:inline-block;padding:2px 8px;border-radius:3px;color:#fff;font-size:12px;font-weight:600}
</style>""", unsafe_allow_html=True)
COL = {"full": "#2F7D5B", "partial": "#B7791F", "none": "#A23B3B", "pending": "#6B7A8A"}
pill = lambda s: f'<span class="pill" style="background:{COL.get(s, COL["pending"])}">{s}</span>'


# ---------- persistence ----------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"org": "", "reviewer": "", "evidence": {}, "ai": {}, "decisions": {}}


def save_state():
    STATE_FILE.write_text(json.dumps(st.session_state.s, indent=1, default=str))


if "s" not in st.session_state:
    st.session_state.s = load_state()
S = st.session_state.s

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
    save_state()


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

st.title("AI governance readiness workbench")
st.caption("Evidence in, sufficiency rating proposed by AI, decision recorded by a named reviewer. Ratings are not a determination of regulatory compliance.")

tab_s, tab_c, tab_a, tab_r, tab_b, tab_h, tab_l = st.tabs(["Scan", "Controls", "Assess", "Report", "Audit", "History", "Lifecycle"])
VCOL = {"PASS": "#2F7D5B", "FAIL": "#A23B3B", "NOT_TESTABLE": "#6B7A8A"}
vpill = lambda v: f'<span class="pill" style="background:{VCOL[v]}">{v}</span>'


# ---------- Scan ----------
with tab_s:
    if not controls:
        st.info("Load a playbook workbook to use this tab.")
    else:
        st.subheader("Scan a folder for evidence")
        st.caption("Reads PDF, Word, Excel, Markdown, text, CSV, JSON and YAML files under the folder, maps them to in-scope controls, and runs the assessor on the best matches. Environment signals (IaC, CI, IAM, logging, prompts, secrets files) are detected by filename pattern. Everything stays on this machine.")
        folder = st.text_input("Folder path", S.get("scan_folder", "") or str(Path("sample_evidence").resolve()), placeholder="/Users/you/Documents/ai-governance-evidence")
        S["scan_folder"] = folder
        c1, c2, c3 = st.columns([1, 1, 2])
        min_score = c3.slider("Match threshold (lower finds more, noisier)", 1.0, 10.0, 4.0, 0.5)
        do_index = c1.button("1. Index folder", type="primary", disabled=not folder)
        if do_index:
            if not os.path.isdir(folder):
                st.error("Folder not found. Paste the full path (in Finder: right-click the folder, hold Option, Copy as Pathname).")
            else:
                bar = st.progress(0.0, "Reading files…")
                st.session_state.index, st.session_state.signals = index_folder(folder, lambda n, t, name: bar.progress((n + 1) / max(t, 1), f"Reading {name}"))
                bar.empty()
                chunks = st.session_state.index.chunks
                files = len({c.path for c in chunks})
                st.success(f"Indexed {files} documents into {len(chunks)} passages. Found {len(st.session_state.signals)} environment signals.")
        idx = st.session_state.get("index")
        sigs = st.session_state.get("signals", [])

        if sigs:
            with st.expander(f"Environment signals ({len(sigs)})"):
                st.dataframe([{"File": s_.path, "Kind": s_.kind, "What to check": s_.hint, "Relevant controls": ", ".join(s_.controls)} for s_ in sigs],
                             width="stretch", hide_index=True)

        if idx:
            matches = match_controls(idx, in_scope, min_score=min_score)
            found = [c for c in in_scope if c.key in matches]
            st.write(f"Candidate evidence found for **{len(found)}** of {len(in_scope)} in-scope controls; **{len(in_scope) - len(found)}** have no matching document.")
            with st.expander("Preview matches"):
                st.dataframe([{"Control": f"{c.id} {c.title}", "Library": c.lib, "Best match": matches[c.key][0][0].label, "Score": round(matches[c.key][0][1], 1),
                               "Signals": len(signals_for(c, sigs))} for c in found], width="stretch", hide_index=True)
            only_new = st.checkbox("Skip controls that already have a recorded decision", True)
            todo = [c for c in found if not (only_new and c.key in S["decisions"])]
            if c2.button(f"2. Assess {len(todo)} matched controls", disabled=not todo):
                bar = st.progress(0.0)
                fails = 0
                for n, c in enumerate(todo):
                    bar.progress(n / len(todo), f"Assessing {c.id} ({n + 1}/{len(todo)})")
                    S["evidence"][c.key] = build_evidence(c, matches[c.key], sigs)
                    S["ai"][c.key] = propose(c, S["evidence"][c.key])
                    fails += S["ai"][c.key].get("model") == "error"
                    S["decisions"].pop(c.key, None)
                    save_state()
                bar.empty()
                st.success(f"Assessed {len(todo)} controls ({fails} errors). Review each on the Assess tab — nothing is recorded until you accept or override.")

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
            state = d["sufficiency"] if d else ("pending" if c.key in S["ai"] else None)
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

        reuse = st.selectbox("Reuse this evidence on another control", [""] + [k for k in by_key if k != c.key],
                             format_func=lambda k: "—" if not k else f"{by_key[k].id} {by_key[k].title[:50]}")
        b1, b2 = st.columns(2)
        if b2.button("Copy evidence", disabled=not reuse):
            S["evidence"][reuse] = dict(ev)
            st.toast("Evidence copied. Cross-mapped controls still need their own assessment.")
        if b1.button("Assess with AI", type="primary"):
            if not ev.get("text") and not ev.get("file_path"):
                st.error("Add evidence before assessing.")
            else:
                with st.spinner("Assessing…"):
                    pdf = Path(ev["file_path"]).read_bytes() if ev.get("file_path") else None
                    S["ai"][c.key] = propose(c, ev, pdf)
                    S["decisions"].pop(c.key, None)
                    if S["ai"][c.key].get("model") == "error":
                        st.error(S["ai"][c.key]["rationale"])
        save_state()

        a = S["ai"].get(c.key)
        if a:
            st.markdown("### AI proposal")
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

            st.markdown("### Reviewer decision — only this is recorded")
            d = S["decisions"].get(c.key)
            if d:
                over = " **(overrides AI)**" if d["sufficiency"] != a["sufficiency"] else ""
                st.markdown(f'{pill(d["sufficiency"])} maturity {d["maturity"]}/5 — recorded by {d["reviewer"]}, {d["at"][:16].replace("T"," ")}{over}', unsafe_allow_html=True)
                if d.get("note"):
                    st.caption("Note: " + d["note"])
                if st.button("Reopen"):
                    S["decisions"].pop(c.key); save_state(); st.rerun()
            else:
                k1, k2, k3 = st.columns([1, 1, 2])
                suff = k1.selectbox("Sufficiency", ["none", "partial", "full"], index=["none", "partial", "full"].index(a["sufficiency"]))
                mat = k2.selectbox("Maturity", [1, 2, 3, 4, 5], index=a["proposedMaturity"] - 1)
                note = k3.text_input("Note (optional)")
                changed = suff != a["sufficiency"] or mat != a["proposedMaturity"]
                if st.button("Record override" if changed else "Accept proposal", type="primary"):
                    S["decisions"][c.key] = record_decision(a, suff, mat, note, S["reviewer"])
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
              "Evidence sufficiency is proposed by an AI assistant and accepted or overridden by the named reviewer. Ratings describe how far supplied evidence supports each control. They are not a determination of regulatory compliance.\n",
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
                   f"- Rating: {d['sufficiency']}, maturity {d['maturity']}/5 — accepted by {d['reviewer']} on {d['at'][:10]}" + (f" (AI proposed {d['aiSufficiency']})" if d.get('aiSufficiency') != d['sufficiency'] else ""),
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
