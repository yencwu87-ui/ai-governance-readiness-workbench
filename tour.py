"""
Guided tour and theme for the workbench.

Two things live here because both are presentation and neither belongs in app.py:

  * A deterministic next-step guide. It reads the actual state of the session and
    names the first thing that has not been done. It does NOT call the assessor.
    The policy says the AI may not record a decision, sign a result or set a gate
    outcome, and a model improvising "you look ready to sign this" sits close
    enough to that line to be worth avoiding. A rule that reads state cannot be
    wrong about whether a folder has been indexed.

  * A light/dark token set. Streamlit's own widgets are themed from
    .streamlit/config.toml, which cannot change at run time, so the toggle here
    restyles the app surface and this app's own components. Set base="dark" in
    config.toml if you want the widgets to match without a toggle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import streamlit as st

# ---------- theme ----------

_TOKENS = {
    "light": {
        "ink": "#16324F", "ink_soft": "#4A5C6E", "surface": "#FFFFFF",
        "raised": "#F3F7FB", "line": "#D7E1EA", "accent": "#16324F",
        "pass": "#2F7D5B", "fail": "#A23B3B", "warn": "#B7791F", "muted": "#6B7A8A",
    },
    "dark": {
        "ink": "#E6EDF3", "ink_soft": "#9FB0C0", "surface": "#0E1621",
        "raised": "#16232F", "line": "#263542", "accent": "#7FB2E5",
        "pass": "#5FB98C", "fail": "#E07A7A", "warn": "#E0A94F", "muted": "#8896A4",
    },
}


def apply_theme(mode: str = "light") -> dict:
    """Inject the token set and this app's own styles. Returns the tokens for use in Python."""
    t = _TOKENS.get(mode, _TOKENS["light"])
    dark_surface = f"""
      [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{ background:{t['surface']}; }}
      [data-testid="stSidebar"] {{ background:{t['raised']}; }}
      body, p, li, label, .stMarkdown {{ color:{t['ink']}; }}
      [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {{ color:{t['ink']}; }}
      thead th, tbody td {{ color:{t['ink']} !important; }}
    """ if mode == "dark" else ""
    st.markdown(f"""<style>
      :root {{
        --ink:{t['ink']}; --ink-soft:{t['ink_soft']}; --surface:{t['surface']};
        --raised:{t['raised']}; --line:{t['line']}; --accent:{t['accent']};
      }}
      h1,h2,h3 {{ font-family:Cambria,Georgia,serif; }}
      /* Streamlit's own emotion rules are more specific than a bare h1 selector,
         so the heading colour has to be forced, anchor span included. */
      h1,h2,h3,h1 *,h2 *,h3 * {{ color:var(--ink) !important; }}
      .req {{ background:var(--raised); border-left:3px solid var(--accent);
             padding:8px 12px; margin:6px 0 10px; color:var(--ink); }}
      .pill {{ display:inline-block; padding:2px 8px; border-radius:3px; color:#fff;
              font-size:12px; font-weight:600; }}
      .tour {{ background:var(--raised); border:1px solid var(--line); border-left:3px solid var(--accent);
              padding:10px 12px 12px; margin:4px 0 10px; border-radius:3px;
              position:relative; overflow:hidden; }}
      .tour-step {{ font-size:11px; letter-spacing:.08em; text-transform:uppercase;
                   color:var(--ink-soft); margin-bottom:4px; }}
      .tour-title {{ font-weight:600; color:var(--ink); margin-bottom:4px; }}
      .tour-body {{ font-size:13px; color:var(--ink-soft); line-height:1.45; }}
      .tour-done {{ color:var(--ink-soft); font-size:13px; padding:1px 0;
                   animation:tour-row .35s ease both; }}
      .tour-now {{ color:var(--ink); }}
      .tour-bar {{ height:2px; background:var(--line); margin:10px -12px -12px; }}
      .tour-bar > i {{ display:block; height:100%; width:0; background:var(--accent); }}
      .tour-dot {{ display:inline-block; width:6px; height:6px; border-radius:50%;
                  background:var(--accent); margin-right:7px; vertical-align:middle; }}
      @keyframes tour-row {{ from {{ opacity:0; transform:translateY(3px); }}
                            to {{ opacity:1; transform:none; }} }}
      @keyframes tour-pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:.3; }} }}
      @media (prefers-reduced-motion: reduce) {{
        .tour-done {{ animation:none; }}
      }}
      {dark_surface}
    </style>""", unsafe_allow_html=True)
    return t


def theme_colors(mode: str) -> dict:
    """Verdict and rating colours for the current mode, for pills built in app.py."""
    t = _TOKENS.get(mode, _TOKENS["light"])
    return {"full": t["pass"], "partial": t["warn"], "none": t["fail"], "pending": t["muted"],
            "PASS": t["pass"], "FAIL": t["fail"], "NOT_TESTABLE": t["muted"]}


# ---------- tour ----------

@dataclass(frozen=True)
class Step:
    key: str
    tab: str
    title: str
    body: str
    done: Callable[[dict], bool]
    blocked: Callable[[dict], str | None] = lambda ctx: None


def _has(ctx: dict, key: str) -> bool:
    v = ctx.get(key)
    return bool(v) if not isinstance(v, (int, float)) else v > 0


STEPS: list[Step] = [
    Step(
        key="playbook", tab="Sidebar",
        title="Load the playbook workbook",
        body="Upload the AI Governance Playbook .xlsx in the sidebar, or drop it in data/. "
             "The control libraries and the eleven lifecycle plays are read from it. "
             "Audit and History work without it; everything else needs it.",
        done=lambda ctx: _has(ctx, "controls"),
    ),
    Step(
        key="reviewer", tab="Sidebar",
        title="Put your name in as reviewer",
        body="Nothing can be signed by an unnamed reviewer — an unattributed decision is "
             "reopened, not accepted. Set it once and it persists.",
        done=lambda ctx: bool(str(ctx.get("reviewer", "")).strip()),
    ),
    Step(
        key="scan", tab="Scan",
        title="Index an evidence folder",
        body="Point at the folder holding your policies, model cards, eval results and "
             "infrastructure config. Files are read locally, split into passages and matched "
             "to in-scope controls. Nothing leaves the machine.",
        done=lambda ctx: _has(ctx, "indexed_docs"),
    ),
    Step(
        key="assess", tab="Assess",
        title="Run the assessor on a control",
        body="The assessor proposes a sufficiency rating and cites the passages it relied on. "
             "It proposes only. Read the citations before you agree with it.",
        done=lambda ctx: _has(ctx, "ai_proposals"),
        blocked=lambda ctx: None if _has(ctx, "indexed_docs") else "Index a folder first.",
    ),
    Step(
        key="decide", tab="Assess",
        title="Record a decision",
        body="Accept, adjust or reject the proposed rating. This is the step that produces "
             "the audit trail — the proposal is not a finding until a named person stands behind it.",
        done=lambda ctx: _has(ctx, "decisions"),
        blocked=lambda ctx: None if _has(ctx, "ai_proposals") else "Assess a control first.",
    ),
    Step(
        key="audit", tab="Audit",
        title="Run continuous control testing",
        body="Lane B tests the operating reality deterministically — change tickets, eval runs, "
             "policy hashes, dependency pins. It writes a hashed evidence bundle. No model involved.",
        done=lambda ctx: _has(ctx, "bundles"),
    ),
    Step(
        key="triage", tab="Audit",
        title="Work the failing controls",
        body="Failures need a disposition: accepted, exception raised, or escalated. "
             "Controls that could not be tested need attention too — a control that examined "
             "nothing has not passed, it did not run.",
        done=lambda ctx: not _has(ctx, "open_failures") and not _has(ctx, "open_inconclusive"),
        blocked=lambda ctx: None if _has(ctx, "bundles") else "Run a control test first.",
    ),
    Step(
        key="lifecycle", tab="Lifecycle",
        title="Check design against operation",
        body="The plays join the two lanes: what you designed (Lane A) against what actually "
             "operates (Lane B). A play green on design and red on operation is the gap worth "
             "arguing about.",
        done=lambda ctx: _has(ctx, "lifecycle_viewed"),
        blocked=lambda ctx: None if _has(ctx, "controls") else "Load the playbook first.",
    ),
    Step(
        key="report", tab="Report",
        title="Export the readiness summary",
        body="Gap register, ratings by library, and the lifecycle view, as a workpaper you can "
             "hand to someone. Every rating carries the reviewer who signed it.",
        done=lambda ctx: False,  # terminal: always the last thing offered
    ),
]


def next_step(ctx: dict) -> tuple[Step, int, int]:
    """First step not yet done, its 1-based position, and the total. Never returns None."""
    for i, s in enumerate(STEPS):
        if not s.done(ctx):
            return s, i + 1, len(STEPS)
    return STEPS[-1], len(STEPS), len(STEPS)


def render(ctx: dict, *, container=None, show_all: bool = False) -> None:
    """Draw the guide. Pass container=st.sidebar to put it there.

    The card animates when the guide moves on, not on every rerun. Streamlit reruns
    the whole script constantly, so the animation is keyed to the step: the class
    names and keyframe names carry step.key, which means unchanged state produces
    byte-identical markup that React leaves alone, and a changed step produces new
    class names that restart the animation.
    """
    c = container or st
    step, pos, total = next_step(ctx)
    reason = step.blocked(ctx)
    done_n = sum(1 for s in STEPS if s.done(ctx))
    pct = round(100 * done_n / total)
    a = f"tour-{step.key}"  # per-step namespace, see docstring

    c.markdown(f"""<style>
      @keyframes {a}-in {{ from {{ opacity:0; transform:translateY(6px); }}
                          to {{ opacity:1; transform:none; }} }}
      @keyframes {a}-bar {{ from {{ width:0; }} to {{ width:{pct}%; }} }}
      .{a} {{ animation:{a}-in .45s cubic-bezier(.2,.7,.3,1) both; }}
      .{a} .tour-bar > i {{ animation:{a}-bar .9s .15s cubic-bezier(.2,.7,.3,1) both; }}
      .{a} .tour-dot {{ animation:tour-pulse 2.4s ease-in-out infinite; }}
      @media (prefers-reduced-motion: reduce) {{
        .{a} {{ animation-duration:1ms; }}
        .{a} .tour-bar > i {{ animation-delay:0s; animation-duration:1ms; }}
        .{a} .tour-dot {{ animation:none; }}
      }}
    </style>"""
    f'<div class="tour {a}">'
    f'<div class="tour-step"><span class="tour-dot"></span>'
    f'Next step &nbsp;·&nbsp; {pos} of {total} &nbsp;·&nbsp; {step.tab}</div>'
    f'<div class="tour-title">{step.title}</div>'
    f'<div class="tour-body">{step.body}</div>'
    f'<div class="tour-bar"><i></i></div>'
    f'</div>', unsafe_allow_html=True)
    if reason:
        c.caption(f"Blocked — {reason}")

    if show_all:
        with c.expander(f"All steps ({done_n} of {total} done)"):
            for i, s in enumerate(STEPS, 1):
                mark = "●" if s.done(ctx) else "○"
                cls = "tour-done tour-now" if i == pos else "tour-done"
                st.markdown(
                    f'<div class="{cls}" style="animation-delay:{(i - 1) * 45}ms">'
                    f'{mark} <b>{i}. {s.title}</b> — {s.tab}</div>',
                    unsafe_allow_html=True)
