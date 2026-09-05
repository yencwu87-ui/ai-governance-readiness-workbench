import datetime as dt
import json
import os
from pathlib import Path

import streamlit as st

from assessor import PROVIDER, assess, model_name
from playbook import LIBRARIES, load_controls, write_back
from scanner import Index, scan_documents, scan_environment, signals_for

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
        st.info("Upload the AI Governance Playbook workbook, or place it in the data/ folder.")
        st.stop()
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


controls = _load(str(src)) if isinstance(src, Path) else load_controls(src)
in_scope = [c for lib, rows in controls.items() if scope.get(lib) for c in rows]
by_key = {c.key: c for c in in_scope}

st.title("AI governance readiness workbench")
st.caption("Evidence in, sufficiency rating proposed by AI, decision recorded by a named reviewer. Ratings are not a determination of regulatory compliance.")

tab_s, tab_c, tab_a, tab_r = st.tabs(["Scan", "Controls", "Assess", "Report"])


# ---------- Scan ----------
with tab_s:
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
            chunks = scan_documents(folder, lambda n, t, name: bar.progress((n + 1) / max(t, 1), f"Reading {name}"))
            bar.empty()
            st.session_state.index = Index(chunks)
            st.session_state.signals = scan_environment(folder)
            files = len({c.path for c in chunks})
            st.success(f"Indexed {files} documents into {len(chunks)} passages. Found {len(st.session_state.signals)} environment signals.")
    idx = st.session_state.get("index")
    sigs = st.session_state.get("signals", [])

    if sigs:
        with st.expander(f"Environment signals ({len(sigs)})"):
            st.dataframe([{"File": s_.path, "Kind": s_.kind, "What to check": s_.hint, "Relevant controls": ", ".join(s_.controls)} for s_ in sigs],
                         width="stretch", hide_index=True)

    if idx:
        matches = {c.key: idx.query(c, k=3, min_score=min_score) for c in in_scope}
        found = [c for c in in_scope if matches[c.key]]
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
                ev_text = "\n\n".join(f"--- Source: {ch.label} ---\n{ch.text}" for ch, _ in matches[c.key])
                sg = signals_for(c, sigs)
                if sg:
                    ev_text += "\n\n--- Environment signals ---\n" + "\n".join(f"{x.path}: {x.hint}" for x in sg)
                S["evidence"][c.key] = {"text": ev_text[:20000], "file_name": "", "auto": True, "sources": [ch.path for ch, _ in matches[c.key]]}
                try:
                    S["ai"][c.key] = assess(c, ev_text)
                    S["decisions"].pop(c.key, None)
                except Exception as e:
                    fails += 1
                    S["ai"][c.key] = {"sufficiency": "none", "proposedMaturity": 1, "rationale": f"Assessment failed: {e}", "excerpt": "", "gaps": [], "remediation": [], "flags": ["assessor error"], "model": "error"}
                save_state()
            bar.empty()
            st.success(f"Assessed {len(todo)} controls ({fails} errors). Review each on the Assess tab — nothing is recorded until you accept or override.")

    # gap analysis
    if S["ai"] or S["decisions"]:
        st.subheader("Gap analysis")
        rating = lambda k: S["decisions"].get(k, {}).get("sufficiency") or S["ai"].get(k, {}).get("sufficiency")
        rows_ = []
        for c in in_scope:
            r = rating(c.key)
            if r == "full":
                continue
            a = S["ai"].get(c.key, {})
            no_ev = c.key not in S["ai"]
            rows_.append({"Priority": 0 if r == "none" else 1 if no_ev else 2, "Control": f"{c.id} {c.title}", "Library": c.lib,
                          "Finding": "not assessed — no evidence located" if no_ev else r + (" (proposed, not yet reviewed)" if c.key not in S["decisions"] else ""),
                          "Gaps": "; ".join(a.get("gaps", [])) if not no_ev else "No document in the scanned folder matched this control",
                          "Suggested action": "; ".join(a.get("remediation", [])) if a.get("remediation") else ("Produce evidence: " + (c.req[:120] if no_ev else "see gaps")),
                          "Owner": c.owner})
        rows_.sort(key=lambda r: r["Priority"])
        st.caption(f"{len(rows_)} controls below full. Proposed ratings are the assessor's; only reviewed ones are recorded.")
        st.dataframe([{k: v for k, v in r.items() if k != "Priority"} for r in rows_], width="stretch", hide_index=True, height=400)
        st.session_state.gap_rows = rows_

# ---------- Controls ----------
with tab_c:
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
                try:
                    pdf = Path(ev["file_path"]).read_bytes() if ev.get("file_path") else None
                    S["ai"][c.key] = assess(c, ev.get("text", ""), pdf, ev.get("file_name", ""))
                    S["decisions"].pop(c.key, None)
                except Exception as e:
                    st.error(f"Assessment failed: {e}")
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
                S["decisions"][c.key] = {"sufficiency": suff, "maturity": mat, "note": note, "reviewer": S["reviewer"] or "Unnamed reviewer",
                                         "at": dt.datetime.now().isoformat(timespec="seconds"), "aiSufficiency": a["sufficiency"], "aiMaturity": a["proposedMaturity"]}
                save_state(); st.rerun()

# ---------- Report ----------
with tab_r:
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
    report = "\n".join(md)

    c1, c2 = st.columns(2)
    c1.download_button("Download report (.md)", report, file_name=f"AI_readiness_{(S['org'] or 'org').replace(' ', '_')}.md", type="primary")
    if c2.button("Write results back to playbook"):
        out = DATA / f"playbook_assessed_{dt.date.today()}.xlsx"
        n = write_back(src if isinstance(src, Path) else src, str(out), controls, S["decisions"], S["ai"], S["evidence"])
        st.success(f"{n} control rows updated → {out}")
        st.download_button("Download updated playbook", out.read_bytes(), file_name=out.name)
