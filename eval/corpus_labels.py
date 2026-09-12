"""Derive each corpus document's label from its per-element decisions, and check the corpus.

    cd repo && python eval/corpus_labels.py            # derive and report
    python eval/corpus_labels.py --check              # non-zero exit on any problem (for CI)
    python eval/corpus_labels.py --json               # machine-readable, for score.py

The label of a corpus document is not an opinion to be asserted. It is a consequence of the
element decisions written down before the document was drafted — that is what makes the
corpus blind-equivalent without a second labeller. This script computes that consequence, so
the boundary in LABELS.md and the label a scorer uses cannot drift apart.

Expected layout, one directory per control:

    eval/corpus/M3.12/elements.yaml
    eval/corpus/M3.12/LABELS.md
    eval/corpus/M3.12/<opaque>_a.md   _b.md   _c.md

elements.yaml:

    control: M3.12
    elements:
      - id: e0
        text: The change register is complete and internally consistent
        lane: b            # optional; lane b elements are excluded, as in calibration()
        a: Y               # Y | N | n/a | ?   — n/a means the element does not apply here
        b: Y
        c: N

Derivation, in this order — the order matters:

    any '?'                 -> UNDECIDED   (the corpus is not ready; this is not a label)
    no Y and no N           -> ERROR       (every element n/a: the document tests nothing)
    no N                    -> full
    no Y                    -> none
    otherwise               -> partial

The shell version of this had 'full' before the no-Y test, so a document whose elements were
all n/a derived as full. An authoring mistake became the strongest possible pass.

There is no author-stated label anywhere. LABELS.md is generated from elements.yaml and is a
rendering, not a second opinion — where it disagrees with the derivation it is stale and must
be regenerated. A separately written label is what let M3.6_a carry `full` for a week while
failing three elements, with the model that rated it `partial` being right.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path

try:
    import yaml
except ImportError:
    print("pyyaml is not installed in this environment: pip install pyyaml")
    raise SystemExit(2)

HERE = Path(__file__).parent
REPO = HERE.parent
CORPUS = HERE / "corpus"
DOCS = ("a", "b", "c")
VALID = {"Y", "N", "n/a", "?"}
LEVELS = ("none", "partial", "full")

# The corpus and the assessor must agree on which elements are in play. They are filtered by
# the same overlay settings the loader uses, imported rather than reimplemented — two places
# deciding independently which elements count is how a corpus and a scorer drift apart.
#
# One list, not two. The previous version named the imports in a `from playbook import ...`
# line and re-declared them as lambdas in the except branch, so the two had to be kept in
# step by hand and nothing checked that they were. They drifted on the first addition:
# overlay_path was used in render_labels, absent from both, and the failure was a NameError
# raised only on the --write-labels path. Now FALLBACKS is the single declaration of what
# this module needs, and each name is taken from playbook where it exists.
sys.path.insert(0, str(REPO))

FALLBACKS = {
    "load_overlay": lambda: {},
    "overlay_path": lambda: None,
    "overlay_settings": lambda: {"element_scopes": ("model",)},
    "scoped_elements": lambda _cid: [],
}
try:
    import playbook as _pb
except Exception as _e:  # noqa: BLE001 — the corpus check must run without the workbook
    print(f"note: requirement overlay unavailable ({_e}); scope filtering is off")
    _pb = None
_missing = [n for n in FALLBACKS if _pb is not None and not hasattr(_pb, n)]
if _missing:
    print(f"note: playbook is missing {', '.join(_missing)} — falling back for those")
for _name, _stub in FALLBACKS.items():
    globals()[_name] = getattr(_pb, _name, _stub) if _pb is not None else _stub


def derive(values: list[str]) -> tuple[str, dict]:
    """Return (label, counts). Label may be UNDECIDED or ERROR — neither is a rating."""
    counts = {v: values.count(v) for v in ("Y", "N", "n/a", "?")}
    if counts["?"]:
        return "UNDECIDED", counts
    if not counts["Y"] and not counts["N"]:
        return "ERROR", counts
    if not counts["N"]:
        return "full", counts
    if not counts["Y"]:
        return "none", counts
    return "partial", counts


def rendered_labels(control_dir: Path) -> dict[str, str]:
    """The labels currently written in LABELS.md.

    LABELS.md is generated from elements.yaml and carries "do not edit by hand" in its own
    header, so this is NOT a second opinion to check the derivation against — there is only
    one definition of the label and it is the derivation. What can go wrong is staleness: an
    element value is edited, the file is not regenerated, and a reader is looking at a label
    the corpus no longer produces.

    So a disagreement here means LABELS.md needs regenerating, never that the derivation is
    wrong. An earlier version of this function read an author-stated label instead, which is
    the arrangement that let M3.6_a carry `full` for a week while failing three elements.
    """
    p = control_dir / "LABELS.md"
    if not p.exists():
        return {}
    out = {}
    # Only the case headings — `### `M3.6_a.md` → **partial**`. Scanning every line for a
    # document marker near a rating word read incidental prose instead: the Cases preamble
    # contains "how `M3.6_a` carried `full` for a week", and a `where` cell reads "_b has
    # none". Both matched, both came before the headings, and the check silently compared
    # against sentences rather than labels. M3.12 passed only because that same sentence
    # happens to name the label M3.12_a really has.
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("###"):
            continue
        m = re.search(r"_([abc])\b[^\n]*?\*\*(full|partial|none)\*\*", line, re.I)
        if m:
            out[m.group(1).lower()] = m.group(2).lower()
    return out


def load_control(d: Path) -> dict:
    spec = yaml.safe_load((d / "elements.yaml").read_text(encoding="utf-8")) or {}
    elements = spec.get("elements") or []
    cid = spec.get("control") or d.name
    problems, rows = [], {}

    scored = [e for e in elements if str(e.get("lane", "")).lower() != "b"]
    lane_b = len(elements) - len(scored)

    # Scope. An element the assessor is never asked to evaluate must not be able to pull a
    # document's label down. M3.6's e6-e8 are programme-scoped — a validation standard or a
    # trigger register evidences them, and a single model's report cannot. Deriving a label
    # over all eight while the assessor sees only the model-scoped five makes `full`
    # unreachable by construction, and the shortfall reads as assessor failure.
    ov_els = scoped_elements(cid)
    in_scope_ids = {str(e.get("id")) for e in ov_els}
    all_ov = (load_overlay().get("controls") or {}).get(cid) or {}
    known_ids = {str(e.get("id")) for e in (all_ov.get("elements") or [])}
    cond_ids = {str(e.get("id")) for e in (all_ov.get("conditional_elements") or []) if e.get("id")}
    scopes = overlay_settings()["element_scopes"]

    out_of_scope = []
    if known_ids:
        keep = []
        for e in scored:
            eid = str(e.get("id"))
            if eid in known_ids and eid not in in_scope_ids:
                out_of_scope.append(eid)
            else:
                keep.append(e)
        scored = keep

        # Ids in the corpus the overlay has never heard of, and vice versa. Either is a
        # silent divergence between what is labelled and what is asked.
        corpus_ids = {str(e.get("id")) for e in elements}
        unknown = sorted(corpus_ids - known_ids - cond_ids)
        absent = sorted(in_scope_ids - corpus_ids)
        if unknown:
            problems.append(f"corpus elements not in the requirement overlay: {', '.join(unknown)}")
        if absent:
            problems.append(f"in-scope requirement elements missing from the corpus: {', '.join(absent)}")
        if corpus_ids & cond_ids:
            problems.append("corpus labels conditional elements the assessor is never given: "
                            + ", ".join(sorted(corpus_ids & cond_ids)))
    else:
        problems.append(f"no requirement overlay entry for {cid} — scope filtering could not be applied")

    if not elements:
        problems.append("elements.yaml lists no elements")
    if not scored and elements:
        problems.append("every element is excluded (lane b or out of scope) — nothing is scored here")

    for e in elements:
        for k in DOCS:
            v = e.get(k)
            if v is None:
                problems.append(f"element {e.get('id', '?')} has no value for _{k}")
            elif str(v) not in VALID:
                problems.append(f"element {e.get('id', '?')}._{k} is {v!r}, expected one of {sorted(VALID)}")

    shown = rendered_labels(d)
    for k in DOCS:
        vals = [str(e.get(k)) for e in scored if e.get(k) is not None]
        label, counts = derive(vals)
        row = {"derived": label, "counts": counts, "rendered": shown.get(k),
               "file": next((f.name for f in d.glob(f"*_{k}.*")), None)}
        if row["file"] is None:
            problems.append(f"no document file found for _{k}")
        if row["rendered"] and label in LEVELS and row["rendered"] != label:
            problems.append(f"_{k}: LABELS.md shows {row['rendered']} but the elements now derive "
                            f"{label} — LABELS.md is stale, regenerate it")
        rows[k] = row

    return {"control": cid, "dir": d.name, "elements": len(elements),
            "scored_elements": len(scored), "lane_b_elements": lane_b,
            "out_of_scope": sorted(set(out_of_scope)), "element_scopes": list(scopes),
            "rendered_missing": not shown, "docs": rows, "problems": problems}



# ---------------------------------------------------------------------------
# Rendering LABELS.md
#
# LABELS.md carries "generated from elements.yaml, do not edit by hand" in its own header,
# but nothing generated it — it was maintained alongside the corpus, which is how M3.6_a
# carried `full` for a week while failing three elements. A staleness check catches that
# after the fact. Generating the file means it cannot be written wrong in the first place.
#
# Everything above "## Boundary for this control" is preserved verbatim: that preamble is
# authored prose about why filenames are opaque and why the documents must not be reused as
# few-shot examples, and none of it is derived. Everything from that heading down is written
# from requirements/mas.yaml and elements.yaml, so a reader and a scorer see one label.
# ---------------------------------------------------------------------------
def _wrap(text: str, width: int = 92) -> str:
    """Hard-wrap prose so a regeneration diffs line by line.

    An unwrapped paragraph makes every regeneration a whole-paragraph change in git, which
    hides the one word that actually moved. 92 matches the width the corpus files were
    hand-wrapped to; if a control's file was written to a different width, measure it with
    `awk '{print length}' LABELS.md | sort -n | tail -3` rather than guessing.
    """
    return "\n".join(textwrap.wrap(" ".join(text.split()), width=width))


BOUNDARY_H = "## Boundary for this control"
WHERE_FIELDS = ("where", "why", "note", "evidence")
WHERE_MAX = 150          # the width the hand-written tables were truncated to
UNCONFIRMED = "claude-unconfirmed"


def _where(e: dict) -> str:
    """Where in the documents the decision was read from. Truncated, as the corpus files
    were — the cell is a pointer for a reader who has the documents open, not the evidence."""
    for f in WHERE_FIELDS:
        if e.get(f):
            t = " ".join(str(e[f]).split())
            return t if len(t) <= WHERE_MAX else t[:WHERE_MAX].rstrip() + " …"
    return ""


def render_labels(d: Path, r: dict, spec: dict) -> str:
    cid = r["control"]
    ov = (load_overlay().get("controls") or {}).get(cid) or {}
    els = spec.get("elements") or []
    ov_by_id = {str(e.get("id")): e for e in (ov.get("elements") or [])}
    scored_ids = {str(e.get("id")) for e in scoped_elements(cid)}

    existing = (d / "LABELS.md").read_text(encoding="utf-8") if (d / "LABELS.md").exists() else ""
    head = existing.split(BOUNDARY_H)[0].rstrip() if BOUNDARY_H in existing else (
        f"# {cid}\n\nLabels fixed at authoring time, before any assessor run. Filenames are "
        f"opaque on purpose:\nscan_documents() prepends the filename to the chunk text, so a name "
        f"containing the label\nwould be read by the assessor.\n\n"
        f"**Do not reuse these documents as few-shot prompt examples.**\n\n---")

    out = [head, "", BOUNDARY_H, ""]
    # The directory matters: a bare "mas.yaml" is ambiguous with the superseded drafts the
    # loader also searches, and naming the wrong one is how two rounds were lost already.
    _ovp = overlay_path()
    try:
        _ovname = str(_ovp.relative_to(REPO)) if _ovp else "the requirement file"
    except ValueError:
        _ovname = str(_ovp)
    out += [_wrap(f"**Defined in `{_ovname}` under `controls.{cid}`, not here.** That file is what "
                  f"the assessor is judged against and what a reviewer reads. Restating it here "
                  f"created two definitions of `full` for one control and they diverged. Reproduced "
                  f"below for reading convenience only; if the two disagree, the requirement file "
                  f"wins and these labels must be re-argued."), ""]
    if ov.get("requirement"):
        out += [_wrap(f"**Requirement.** {' '.join(str(ov['requirement']).split())}"), ""]

    # "Model-scoped elements" where that is what they are — the corpus files said so, and it
    # is the more precise heading given e6-e8 exist on M3.6 and are deliberately excluded.
    _scopes = list(overlay_settings()["element_scopes"])

    # Elements the overlay declares but this corpus does not carry, because their scope is
    # not being assessed. They have to be listed: the heading says "(10)" and a reader with
    # the requirement file open can see thirteen, so the file must account for the other
    # three. Iterating only the corpus elements is why the first version silently dropped
    # them — e6-e8 exist in mas.yaml and nowhere in elements.yaml.
    corpus_ids = {str(e.get("id")) for e in els}
    excluded = {}
    for e in (ov.get("elements") or []):
        eid = str(e.get("id"))
        if eid in corpus_ids or eid in scored_ids:
            continue
        excluded.setdefault(str(e.get("scope", "model")).lower(), []).append(e)

    # "Model-scoped elements" only where some are excluded for scope; otherwise the plain
    # heading, which is what a control with a single scope already says.
    _heading = "Model-scoped elements" if excluded else "Elements"
    out += [f"**{_heading} ({len(els)}) — every applicable one must be evidenced for `full`:**", ""]
    for e in els:
        eid = str(e.get("id"))
        text = " ".join(str(ov_by_id.get(eid, {}).get("text") or e.get("text") or "").split())
        mark = " *(lane b — tested deterministically, not scored here)*" \
            if str(e.get("lane", "")).lower() == "b" else ""
        out.append(f"- `{eid}` — {text}{mark}")

    for scope, rows in excluded.items():
        out += ["", f"{scope.capitalize()}-scoped ({len(rows)}), excluded by "
                    f"`settings.element_scopes: [{', '.join(_scopes)}]`:"]
        for e in rows:
            out.append(f"- `{e.get('id')}` — {' '.join(str(e.get('text', '')).split())}")
    cond = ov.get("conditional_elements") or []
    if cond:
        out += ["", "Conditional, not scored until the loader handles them:"]
        for ce in cond:
            when = str(ce.get("applies_when") or ce.get("id") or "conditional")
            out.append(f"- *{when}* — {' '.join(str(ce.get('text', '')).split())}")
    out += ["", "| Rating | Condition (from the requirement file) |", "|---|---|"]
    for lvl in ("full", "partial", "none"):
        cond = " ".join(str((ov.get("boundary") or {}).get(lvl, "")).split())
        out.append(f"| {lvl} | {cond} |")
    out += ["", "Maturity is judged separately and is not the label under test here.", "", "---",
            "## Cases", "",
            _wrap("**Generated by `python eval/corpus_labels.py --write-labels`. Do not edit by "
                  "hand.** The label is derived, not stated: all applicable elements evidenced = "
                  "full, some = partial, none = none. Writing a label here independently is how "
                  "`M3.6_a` carried `full` for a week while failing three elements — the model "
                  "that rated it `partial` was right and the label was wrong."), "",
            _wrap("Filenames are opaque on purpose: scan_documents() prepends the filename to the "
                  "chunk text, so a name containing the label would be read by the assessor."), ""]

    show_where = any(_where(e) for e in els)
    docmap = spec.get("documents") if isinstance(spec.get("documents"), dict) else {}

    # Elements whose value was decided by a model on documents the same model wrote. This is
    # a statement about the standing of the whole corpus, not a detail — a score built on
    # unconfirmed decisions is not independent evidence of anything, and the file has to say
    # so where the labels are read. It was in the hand-written version and must survive.
    unconfirmed = [str(e.get("id")) for e in els
                   if str(e.get("decided_by", "")).lower() == UNCONFIRMED
                   and (not ov_by_id or str(e.get("id")) in scored_ids)]

    for i, k in enumerate(DOCS):
        row = r["docs"][k]
        c = row["counts"]
        if i:
            out += ["---", ""]
        fname = docmap.get(k) or row["file"] or f"{cid}_{k}"
        out += [f"### `{fname}` → **{row['derived']}**", ""]
        na = f", {c['n/a']} not applicable" if c["n/a"] else ""
        out += [f"{c['Y']} evidenced, {c['N']} not evidenced{na}.", ""]
        out += ["| element | | where |" if show_where else "| element | |",
                "|---|---|---|" if show_where else "|---|---|"]
        for e in els:
            eid = str(e.get("id"))
            if ov_by_id and eid not in scored_ids:
                continue
            v = str(e.get(k, ""))
            out.append(f"| `{eid}` | {v} | {_where(e)} |" if show_where else f"| `{eid}` | {v} |")
        out.append("")
        if unconfirmed:
            out += [_wrap(f"*{len(unconfirmed)} of these elements are marked "
                          f"`decided_by: {UNCONFIRMED}` in `elements.yaml` — decided by Claude on "
                          f"documents Claude wrote. Not independent.*"), ""]
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit non-zero if the corpus is not ready")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    ap.add_argument("--control", default=None, help="one control id, e.g. M3.12")
    ap.add_argument("--write-labels", action="store_true",
                    help="regenerate LABELS.md from elements.yaml and the requirement file")
    a = ap.parse_args()

    if not CORPUS.is_dir():
        print(f"no corpus at {CORPUS}")
        return 2
    dirs = sorted(d for d in CORPUS.iterdir()
                  if d.is_dir() and (d / "elements.yaml").exists()
                  and (a.control is None or d.name == a.control))
    if not dirs:
        print("no control directories with an elements.yaml")
        return 2

    results = [load_control(d) for d in dirs]

    if a.write_labels:
        for d, r in zip(dirs, results):
            spec = yaml.safe_load((d / "elements.yaml").read_text(encoding="utf-8")) or {}
            if any(r["docs"][k]["derived"] not in LEVELS for k in DOCS):
                print(f"{r['control']}: not written — a document derives "
                      f"{[r['docs'][k]['derived'] for k in DOCS]}, which is not a label")
                continue
            (d / "LABELS.md").write_text(render_labels(d, r, spec), encoding="utf-8")
            print(f"{r['control']}: LABELS.md written — "
                  + ", ".join(f"_{k}={r['docs'][k]['derived']}" for k in DOCS))
        return 0

    if a.json:
        print(json.dumps(results, indent=1))
        return 0

    dist, blocked = {}, 0
    for r in results:
        excl = []
        if r["lane_b_elements"]:
            excl.append(f"{r['lane_b_elements']} lane b")
        if r["out_of_scope"]:
            excl.append(f"{len(r['out_of_scope'])} out of scope ({', '.join(r['out_of_scope'])})")
        print(f"\n{r['control']}  ({r['scored_elements']} scored elements"
              + (", " + " and ".join(excl) + " excluded" if excl else "") + ")")
        for k in DOCS:
            row = r["docs"][k]
            c = row["counts"]
            mark = "" if row["derived"] in LEVELS else "   <-- not a label"
            agree = "" if not row["rendered"] else (" ✓" if row["rendered"] == row["derived"] else f"  != LABELS.md ({row['rendered']})")
            # n/a means the element's precondition is absent ("applies only where privileged
            # access management is in place"), so it neither helps nor hurts — that is the
            # intended behaviour, not an accident of counting. But a `full` reached with
            # elements not applicable was tested against less than a `full` with none, and a
            # reader comparing two documents should be able to see that.
            na = "" if not c["n/a"] else f"   ({c['n/a']} not applicable)"
            print(f"  _{k}: Y={c['Y']} N={c['N']} n/a={c['n/a']} ?={c['?']}"
                  f"  -> {row['derived']}{agree}{mark}{na}")
            dist[row["derived"]] = dist.get(row["derived"], 0) + 1
        if r.get("rendered_missing"):
            print("  · no LABELS.md rendering found — the derivation stands, but there is no "
                  "generated file for a reader to check against")
        for p in r["problems"]:
            print(f"  ! {p}")
            blocked += 1

    total = sum(dist.values())
    scopes = results[0].get("element_scopes") if results else []
    print(f"\n{len(results)} controls, {total} documents"
          + (f"  ·  element_scopes = {scopes}" if scopes else ""))
    print("  Every label below is derived under that scope setting. Changing it in the "
          "overlay changes the labels, so a stored score is only comparable to another "
          "run under the same setting.")
    print("  label distribution: " + ", ".join(f"{k}={v}" for k, v in sorted(dist.items())))

    # The first golden set could not distinguish a good model from one answering 'full'
    # unconditionally, because 17 of 20 cases were labelled full. A constructed corpus is
    # supposed to be balanced by design, so a skew here means the construction slipped.
    for lvl in LEVELS:
        n = dist.get(lvl, 0)
        if total and n / total > 0.5:
            print(f"  ! {n} of {total} documents derive {lvl} — a model answering {lvl} "
                  f"unconditionally would score {n / total:.0%}. Rebalance before scoring.")
            blocked += 1
        if total and n == 0:
            print(f"  ! no document derives {lvl} — that rating is untested by this corpus")
            blocked += 1

    if blocked:
        print(f"\n{blocked} problem(s). The corpus is not ready to score against.")
    else:
        print("\nCorpus is internally consistent and ready to score against.")
    return 1 if (a.check and blocked) else 0


if __name__ == "__main__":
    raise SystemExit(main())
