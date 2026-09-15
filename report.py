"""WB-046 — the assurance workpaper, generated from the event store.

Why generate rather than write
------------------------------
A workpaper written by hand after the fact is an account of an assessment. A workpaper generated
from the event log IS the assessment, rendered. Every figure in the output traces to an event with
a timestamp, an actor and a position in the hash chain, and `wb.py verify` can be run against the
same log to show the chain was intact when the report was produced.

That is the difference between a report a reviewer signs and a report a reviewer can defend.

Three rules the generator follows, all of which make the document less impressive and more
useful:

  Nothing is inferred. Every number comes from a stored event. Where a cycle lacks something —
  no element verdicts, no challenge, no comparison — the workpaper says so rather than omitting
  the row, because an absent test and a passed test must never look alike on a page.

  Coverage is stated before findings. A reader's first question is what was NOT looked at. The
  scope section leads with controls with no evidence and cycles that never reached a decision.

  The chain state is printed on the cover. If `verify()` finds a break, the workpaper says so on
  page one in place of the summary. A tamper-evident log whose verification result is buried on
  the last page is decoration.

Usage:
    python report.py --out reports/assurance-workpaper.docx
    python report.py --control M3.6 --out reports/m3-6.docx
    python report.py --markdown --out reports/workpaper.md
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import events  # noqa: E402

# House style: navy / ice-blue, Cambria headings, Calibri body — the regulatory-grade
# workpaper format, deliberately distinct from the dark keynote deck style.
NAVY = "1F3A5F"
ICE = "DCE6F1"
RULE = "8DA9C4"
MUTED = "5A6B7C"
BAD = "8C3A2E"


def gather(control: str | None = None) -> dict:
    states = [s for s in events.iter_states() if not control or s.get("control_id") == control]
    chain = events.verify()
    decided = [s for s in states if s.get("stage") == "decided"]
    open_cycles = [s for s in states if s.get("stage") != "decided"]

    rows = []
    for s in decided:
        d = s["decision"]
        diff = d.get("element_diff") or {}
        summary = diff.get("summary") or {}
        rows.append({
            "cycle_id": s["cycle_id"],
            "control_id": s["control_id"],
            "framework": s.get("framework", ""),
            "reviewer": s.get("decided_by", ""),
            "blind": (s.get("read") or {}).get("sufficiency"),
            "proposal": (s.get("proposal") or {}).get("sufficiency"),
            "decision": d.get("sufficiency"),
            "maturity": d.get("maturity"),
            "reason": d.get("reason", ""),
            "compared": summary.get("n_compared"),
            "agree": summary.get("n_agree"),
            "disagree": summary.get("n_disagree"),
            "disagreements": diff.get("disagreements") or [],
            "challenged": bool(d.get("challenged")),
            "revised": bool(d.get("supersedes")),
            "imported": bool(d.get("imported")),
            "assessor_shown": bool(d.get("assessor_shown")),
            "ts": s.get("updated"),
        })

    compared = [r for r in rows if r["compared"]]
    total_elements = sum(r["compared"] or 0 for r in compared)
    total_agree = sum(r["agree"] or 0 for r in compared)
    return {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "scope_control": control,
        "chain": chain,
        "rows": sorted(rows, key=lambda r: (r["framework"], r["control_id"])),
        "open": open_cycles,
        "counts": {
            "cycles": len(states),
            "decided": len(decided),
            "open": len(open_cycles),
            "imported": sum(r["imported"] for r in rows),
            "challenged": sum(r["challenged"] for r in rows),
            "revised": sum(r["revised"] for r in rows),
            "blind_unseen": sum(not r["assessor_shown"] for r in rows),
            "with_comparison": len(compared),
            "elements_compared": total_elements,
            "elements_agreed": total_agree,
            # None, not zero: an agreement rate over nothing is not a rate, and a zero in a
            # workpaper reads as a finding rather than as an absence of measurement.
            "element_agreement": round(total_agree / total_elements, 3) if total_elements else None,
        },
        "by_rating": collections.Counter(r["decision"] for r in rows),
        "by_framework": collections.Counter(r["framework"] for r in rows),
    }


# ---------------------------------------------------------------- markdown

def render_markdown(d: dict) -> str:
    c, chain = d["counts"], d["chain"]
    out = [f"# AI governance assurance workpaper",
           "",
           f"Generated {d['generated']} from the append-only assessment record.",
           f"Scope: {d['scope_control'] or 'all controls with a recorded cycle'}.",
           ""]
    if not chain["intact"]:
        out += ["## Record integrity — FAILED", "",
                f"The event chain is broken at {len(chain['breaks'])} point(s). "
                "The figures below are not evidence until this is resolved.", ""]
        for b in chain["breaks"][:10]:
            out.append(f"- event {b.get('index')}: {b['reason']}")
        out.append("")
    else:
        out += [f"Record integrity: {chain['events']} events, hash chain intact.", ""]

    out += ["## Scope and coverage", "",
            f"- Cycles opened: **{c['cycles']}**",
            f"- Reached a reasoned decision: **{c['decided']}**",
            f"- Still open: **{c['open']}** — unassessed, which is not the same as assessed and found adequate"
            if c["open"] else f"- Still open: **0**",
            f"- Decided without the assessor being consulted: **{c['blind_unseen']}**",
            f"- Migrated from the legacy record rather than recorded contemporaneously: **{c['imported']}**",
            ""]
    if c["imported"]:
        out.append("> Imported cycles are reconstructed from a mutable file. They are shown for "
                   "completeness and are weaker evidence than contemporaneous records.\n")

    out += ["## Assessment outcomes", "",
            "| Control | Framework | Reviewer read | Assessor | Decision | Maturity | Elements agreed | Challenged | Revised |",
            "|---|---|---|---|---|---|---|---|---|"]
    for r in d["rows"]:
        agreed = (f"{r['agree']}/{r['compared']}" if r["compared"] else "not compared")
        out.append(f"| {r['control_id']} | {r['framework'].replace('Control Library - ', '')} "
                   f"| {r['blind'] or '—'} | {r['proposal'] or '—'} | **{r['decision']}** "
                   f"| {r['maturity']} | {agreed} | {'yes' if r['challenged'] else 'no'} "
                   f"| {'yes' if r['revised'] else 'no'} |")
    out.append("")

    if c["element_agreement"] is None:
        out += ["Element-level agreement is not reported: no cycle carried verdicts on both "
                "sides. This is an absence of measurement, not a finding of agreement.", ""]
    else:
        out += [f"Element-level agreement between the reviewer and the assessor: "
                f"**{c['element_agreement']:.0%}** across {c['elements_compared']} compared "
                f"elements in {c['with_comparison']} cycle(s).", ""]

    disagreed = [r for r in d["rows"] if r["disagreements"]]
    if disagreed:
        out += ["## Where the reviewer and the assessor differed", ""]
        for r in disagreed:
            out.append(f"- **{r['control_id']}** — elements {', '.join(r['disagreements'])}. "
                       f"Reviewer {r['blind']}, assessor {r['proposal']}, decided {r['decision']}"
                       + (" after challenge." if r["challenged"] else "."))
        out.append("")

    out += ["## Decisions and their reasons", ""]
    for r in d["rows"]:
        out += [f"**{r['control_id']} — {r['decision']} (maturity {r['maturity']})**  ",
                f"{r['reviewer']} · {r['ts']} · cycle `{r['cycle_id']}`  ",
                f"{r['reason']}", ""]

    if d["open"]:
        out += ["## Not concluded", "",
                "These cycles were opened and carry no decision. They are unassessed, and a "
                "reader should treat them as such rather than as controls found adequate.", ""]
        for s in d["open"]:
            out.append(f"- {s['control_id']} — {s['stage']} (`{s['cycle_id']}`)")
        out.append("")

    out += ["## Basis of preparation", "",
            "Every figure above is derived from an append-only event log in which each event "
            "carries the SHA-256 of the event before it. The log was verified at generation "
            "time and the result is stated at the head of this document. Ratings were proposed "
            "by a model, recorded independently by a named reviewer before the proposal was "
            "shown, compared element by element deterministically, and decided by that reviewer "
            "with a reason that was checked for substance. No rating in this document was set "
            "by a model.", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- docx

def render_docx(d: dict, out_path: Path) -> None:
    script = out_path.parent / "_build_workpaper.js"
    payload = out_path.parent / "_workpaper.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload.write_text(json.dumps(d, default=str))
    script.write_text(_JS.replace("__PAYLOAD__", payload.name).replace("__OUT__", out_path.name))
    r = subprocess.run(["node", script.name], cwd=out_path.parent,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"docx build failed:\n{r.stdout}\n{r.stderr}")
    script.unlink(missing_ok=True)
    payload.unlink(missing_ok=True)


_JS = r"""
const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType,
        ShadingType, AlignmentType, BorderStyle, HeadingLevel, PageNumber, Footer } = require('docx');

const d = JSON.parse(fs.readFileSync('__PAYLOAD__', 'utf8'));
const NAVY = '1F3A5F', ICE = 'DCE6F1', RULE = '8DA9C4', MUTED = '5A6B7C', BAD = '8C3A2E';
const body = (t, o = {}) => new Paragraph({ spacing: { after: 120 },
  children: [new TextRun({ text: t, font: 'Calibri', size: 21, color: o.color || '000000',
                           bold: !!o.bold, italics: !!o.italics })] });
const h1 = t => new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 320, after: 160 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 6 } },
  children: [new TextRun({ text: t, font: 'Cambria', size: 30, bold: true, color: NAVY })] });
const h2 = t => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 240, after: 100 },
  children: [new TextRun({ text: t, font: 'Cambria', size: 24, bold: true, color: NAVY })] });

const W = 9360, cols = [1150, 1250, 1150, 1100, 1100, 900, 1210, 1500];
const cell = (t, o = {}) => new TableCell({
  width: { size: o.w, type: WidthType.DXA },
  shading: { type: ShadingType.CLEAR, fill: o.fill || 'FFFFFF' },
  margins: { top: 60, bottom: 60, left: 90, right: 90 },
  children: [new Paragraph({ children: [new TextRun({ text: String(t), font: 'Calibri', size: 18,
              bold: !!o.bold, color: o.color || '000000' })] })] });

const kids = [];
kids.push(new Paragraph({ spacing: { after: 60 },
  children: [new TextRun({ text: 'AI GOVERNANCE ASSURANCE', font: 'Calibri', size: 16,
                           color: MUTED, characterSpacing: 60 })] }));
kids.push(new Paragraph({ spacing: { after: 100 },
  children: [new TextRun({ text: 'Assessment workpaper', font: 'Cambria', size: 44, bold: true, color: NAVY })] }));
kids.push(new Paragraph({ spacing: { after: 240 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: NAVY, space: 8 } },
  children: [new TextRun({ text: `Generated ${d.generated} · scope: ${d.scope_control || 'all controls with a recorded cycle'}`,
                           font: 'Calibri', size: 19, color: MUTED })] }));

if (!d.chain.intact) {
  kids.push(h1('Record integrity — FAILED'));
  kids.push(body(`The event chain is broken at ${d.chain.breaks.length} point(s). The figures in this document are not evidence until that is resolved.`, { bold: true, color: BAD }));
  d.chain.breaks.slice(0, 8).forEach(b => kids.push(body(`event ${b.index}: ${b.reason}`, { color: BAD })));
} else {
  kids.push(body(`Record integrity: ${d.chain.events} events, hash chain intact at generation.`, { color: MUTED, italics: true }));
}

const c = d.counts;
kids.push(h1('Scope and coverage'));
kids.push(body('What was not examined comes before what was found.', { italics: true, color: MUTED }));
[[`Cycles opened`, c.cycles], [`Reached a reasoned decision`, c.decided],
 [`Still open — unassessed, not assessed and found adequate`, c.open],
 [`Decided without the assessor being consulted`, c.blind_unseen],
 [`Migrated from the legacy record`, c.imported]].forEach(([k, v]) =>
  kids.push(new Paragraph({ spacing: { after: 60 }, bullet: { level: 0 },
    children: [new TextRun({ text: `${k}: `, font: 'Calibri', size: 21 }),
               new TextRun({ text: String(v), font: 'Calibri', size: 21, bold: true, color: NAVY })] })));

kids.push(h1('Assessment outcomes'));
const head = ['Control', 'Framework', 'Reviewer', 'Assessor', 'Decision', 'Mat.', 'Elements', 'Challenge'];
const rows = [new TableRow({ tableHeader: true, children: head.map((t, i) =>
  cell(t, { w: cols[i], fill: NAVY, bold: true, color: 'FFFFFF' })) })];
d.rows.forEach((r, n) => {
  const f = n % 2 ? ICE : 'FFFFFF';
  const el = r.compared ? `${r.agree}/${r.compared} agreed` : 'not compared';
  rows.push(new TableRow({ children: [
    cell(r.control_id, { w: cols[0], fill: f, bold: true }),
    cell((r.framework || '').replace('Control Library - ', ''), { w: cols[1], fill: f }),
    cell(r.blind || '—', { w: cols[2], fill: f }),
    cell(r.proposal || '—', { w: cols[3], fill: f }),
    cell(r.decision, { w: cols[4], fill: f, bold: true, color: NAVY }),
    cell(r.maturity, { w: cols[5], fill: f }),
    cell(el, { w: cols[6], fill: f }),
    cell(r.challenged ? 'yes' : 'no', { w: cols[7], fill: f })] }));
});
kids.push(new Table({ columnWidths: cols, width: { size: W, type: WidthType.DXA }, rows }));

kids.push(new Paragraph({ spacing: { before: 160, after: 120 }, children: [new TextRun({
  text: c.element_agreement === null
    ? 'Element-level agreement is not reported: no cycle carried verdicts on both sides. This is an absence of measurement, not a finding of agreement.'
    : `Element-level agreement between reviewer and assessor: ${(c.element_agreement * 100).toFixed(0)}% across ${c.elements_compared} compared elements in ${c.with_comparison} cycle(s).`,
  font: 'Calibri', size: 21, italics: c.element_agreement === null, color: c.element_agreement === null ? MUTED : '000000' })] }));

const dis = d.rows.filter(r => (r.disagreements || []).length);
if (dis.length) {
  kids.push(h1('Where the reviewer and the assessor differed'));
  dis.forEach(r => kids.push(new Paragraph({ spacing: { after: 80 }, bullet: { level: 0 },
    children: [new TextRun({ text: `${r.control_id} `, font: 'Calibri', size: 21, bold: true }),
               new TextRun({ text: `— elements ${r.disagreements.join(', ')}. Reviewer ${r.blind}, assessor ${r.proposal}, decided ${r.decision}${r.challenged ? ' after challenge.' : '.'}`,
                             font: 'Calibri', size: 21 })] })));
}

kids.push(h1('Decisions and their reasons'));
d.rows.forEach(r => {
  kids.push(h2(`${r.control_id} — ${r.decision} (maturity ${r.maturity})`));
  kids.push(body(`${r.reviewer} · ${r.ts} · cycle ${r.cycle_id}`, { color: MUTED, italics: true }));
  kids.push(body(r.reason));
});

if (d.open.length) {
  kids.push(h1('Not concluded'));
  kids.push(body('These cycles carry no decision. They are unassessed, which is not the same as found adequate.', { italics: true, color: MUTED }));
  d.open.forEach(s => kids.push(new Paragraph({ spacing: { after: 60 }, bullet: { level: 0 },
    children: [new TextRun({ text: `${s.control_id} — ${s.stage}`, font: 'Calibri', size: 21 })] })));
}

kids.push(h1('Basis of preparation'));
kids.push(body('Every figure in this document is derived from an append-only event log in which each event carries the SHA-256 of the event before it. The log was verified at generation time and the result is stated at the head of this document. Ratings were proposed by a model, recorded independently by a named reviewer before the proposal was shown, compared element by element deterministically, and decided by that reviewer with a reason checked for substance. No rating in this document was set by a model.'));

const doc = new Document({
  styles: { default: { document: { run: { font: 'Calibri', size: 21 } } } },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1080, bottom: 1080, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: 'Generated from the assessment record · page ', font: 'Calibri', size: 16, color: MUTED }),
                 new TextRun({ children: [PageNumber.CURRENT], font: 'Calibri', size: 16, color: MUTED })] })] }) },
    children: kids }] });

Packer.toBuffer(doc).then(b => fs.writeFileSync('__OUT__', b));
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--control", help="restrict to one control id")
    ap.add_argument("--out", type=Path, default=Path("reports/assurance-workpaper.docx"))
    ap.add_argument("--markdown", action="store_true", help="emit markdown instead of docx")
    a = ap.parse_args()

    d = gather(a.control)
    if not d["rows"] and not d["open"]:
        print("No cycles in the event log. Run some assessments through wb.py or the app,\n"
              "or migrate the legacy record with: python wb.py migrate data/assessments.json")
        return 0

    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.markdown or a.out.suffix == ".md":
        a.out.write_text(render_markdown(d))
    else:
        render_docx(d, a.out)
    print(f"{a.out}  —  {d['counts']['decided']} decision(s), "
          f"{d['counts']['open']} open, chain "
          f"{'intact' if d['chain']['intact'] else 'BROKEN'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
