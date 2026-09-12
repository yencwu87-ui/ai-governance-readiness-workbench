"""Diagnose the BM25 match threshold in scanner.Index.query().

Answers four questions the slider cannot:
  1. Is one global threshold defensible, or does it mean different things
     per control and per library?
  2. When a control returns nothing, was it the threshold or the top-k cut?
  3. Do wordier controls score structurally higher (query-length bias)?
  4. Is the evidence folder contaminated by the playbook itself?

Does NOT require any change to scanner.py — it rebuilds scores from the
index directly, so it runs against the code as it stands.

Usage:
    python eval/threshold_probe.py --folder <evidence folder> \
        --playbook data/AI_Governance_Playbook_..._v3_CSA_backref.xlsx

    # smoke test only, includes normally-skipped fixture dirs:
    python eval/threshold_probe.py --folder sample_evidence \
        --playbook <workbook> --allow-skipped

    # one library at a time:
    python eval/threshold_probe.py --folder <folder> --playbook <wb> --libs SAFR

Writes eval/threshold_trace.csv and prints the analysis.
"""

import argparse
import csv
import statistics
import sys
from pathlib import Path

# repo root on the path so `import scanner` works when run from eval/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import Index, scan_documents, _tok  # noqa: E402

SWEEP = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0]
UI_DEFAULT = 4.0


# ----------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------
def load_controls(path, libs=None):
    """playbook.load_controls returns dict[lib_name, list[Control]]."""
    import playbook

    by_lib = playbook.load_controls(path)
    if not by_lib:
        raise SystemExit("Workbook loaded but no control libraries were found.")

    wanted = libs or sorted(by_lib)
    missing = [l for l in wanted if l not in by_lib]
    if missing:
        raise SystemExit(f"Unknown library {missing}.\nAvailable: {sorted(by_lib)}")

    print("  controls per library:")
    for lib in wanted:
        n = len(by_lib[lib])
        flag = "   <-- EMPTY, header row may not have matched" if n == 0 else ""
        print(f"    {lib:<16} {n:4d}{flag}")

    controls = [c for lib in wanted for c in by_lib[lib]]
    if not controls:
        raise SystemExit("No controls in the selected libraries.")
    print(f"    {'TOTAL':<16} {len(controls):4d}\n")
    return controls


# ----------------------------------------------------------------------
# scoring
# ----------------------------------------------------------------------
def score_control(index, control, depth):
    """Return (n_query_terms, [(rank, chunk_label, chunk_path, score), ...])."""
    q = _tok(f"{control.title} {control.req} {control.maps}")
    scores = index.bm25.get_scores(q)
    ranked = sorted(range(len(scores)), key=lambda i: -scores[i])[:depth]
    rows = [
        (rank + 1, index.chunks[i].label, index.chunks[i].path, float(scores[i]))
        for rank, i in enumerate(ranked)
    ]
    return len(q), rows


def survivors(rows, k, threshold):
    """How many chunks would actually reach the assessor."""
    return sum(1 for rank, _, _, score in rows if rank <= k and score >= threshold)


def spread(values):
    v = sorted(values)
    return v[0], statistics.median(v), v[-1]


def safe_corr(xs, ys):
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    try:
        return statistics.correlation(xs, ys)
    except Exception:
        return None


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True, help="evidence folder to scan")
    ap.add_argument("--playbook", required=True, help="path to the playbook workbook")
    ap.add_argument("--libs", nargs="*", default=None,
                    help="limit to these libraries (default: all)")
    ap.add_argument("--k", type=int, default=3, help="top-k as used in query()")
    ap.add_argument("--depth", type=int, default=10, help="how deep to trace")
    ap.add_argument("--out", default="eval/threshold_trace.csv")
    ap.add_argument("--allow-skipped", action="store_true",
                    help="smoke test only - scan dirs normally excluded")
    args = ap.parse_args()

    if args.allow_skipped:
        import scanner
        scanner.SKIP_DIRS = {".git", "node_modules", ".venv", "venv",
                             "__pycache__", ".idea", ".vscode", "site-packages"}
        print("WARNING: fixture dirs included. Smoke test only - "
              "do not choose a threshold from this run.\n")

    # ---------- scan ----------
    print(f"scanning {args.folder} ...")
    chunks = scan_documents(args.folder)
    if not chunks:
        raise SystemExit(
            "No chunks produced. Either the folder is empty of supported "
            "file types, or every path component is in scanner.SKIP_DIRS."
        )
    files = {c.path for c in chunks}
    print(f"  {len(chunks)} chunks from {len(files)} files")

    # ---------- contamination check ----------
    pb_name = Path(args.playbook).name.lower()
    hits = [f for f in files
            if Path(f).name.lower() == pb_name or "playbook" in Path(f).name.lower()]
    if hits:
        print("\n  !! CONTAMINATION: the scanned folder contains the playbook "
              "(or a copy):")
        for f in sorted(hits):
            print(f"       {f}")
        print("     It holds every control's requirement text verbatim, so it will")
        print("     match every control near-perfectly and inflate the whole")
        print("     distribution. Do not pick a threshold from this run.\n")

    index = Index(chunks)
    controls = load_controls(args.playbook, args.libs)

    # ---------- score ----------
    per_control = {}
    for c in controls:
        n_terms, rows = score_control(index, c, args.depth)
        per_control[c.key] = {"lib": c.lib, "terms": n_terms, "rows": rows}

    # ---------- csv ----------
    trace = []
    for key, d in per_control.items():
        for rank, label, path, score in d["rows"]:
            trace.append({
                "control_key": key,
                "library": d["lib"],
                "query_terms": d["terms"],
                "rank": rank,
                "chunk": label,
                "chunk_path": path,
                "score": round(score, 4),
                "within_k": rank <= args.k,
                "passes_ui_default": score >= UI_DEFAULT,
            })
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(trace[0].keys()))
        w.writeheader()
        w.writerows(trace)
    print(f"wrote {out} ({len(trace)} rows)\n")

    libs = sorted({d["lib"] for d in per_control.values()})

    # ---------- 1 ----------
    print("=" * 70)
    print("1. TOP SCORE PER CONTROL - can one threshold serve all of them?")
    print("=" * 70)
    tops = {k: d["rows"][0][3] for k, d in per_control.items() if d["rows"]}
    lo, mid, hi = spread(tops.values())
    ratio = f"   ratio {hi / lo:.0f}x" if lo > 0 else ""
    print(f"  ALL              min {lo:7.2f}   median {mid:7.2f}   max {hi:7.2f}{ratio}")
    if len(libs) > 1:
        print()
        for lib in libs:
            vals = [v for k, v in tops.items() if per_control[k]["lib"] == lib]
            if not vals:
                continue
            lo2, mid2, hi2 = spread(vals)
            print(f"  {lib:<16} min {lo2:7.2f}   median {mid2:7.2f}   max {hi2:7.2f}")
    print("\n  weakest 10 controls (these starve first as you raise the bar):")
    for k, s in sorted(tops.items(), key=lambda kv: kv[1])[:10]:
        print(f"    {s:8.2f}  {k}")
    print("\n  strongest 5:")
    for k, s in sorted(tops.items(), key=lambda kv: -kv[1])[:5]:
        print(f"    {s:8.2f}  {k}")

    # ---------- 2 ----------
    print("\n" + "=" * 70)
    print(f"2. THRESHOLD SWEEP (at k={args.k})")
    print("=" * 70)
    print("  thresh    controls with 0 chunks     avg chunks passed")
    for t in SWEEP:
        counts = [survivors(d["rows"], args.k, t) for d in per_control.values()]
        empty = sum(1 for c in counts if c == 0)
        pct = 100.0 * empty / len(counts)
        mark = "   <- UI default" if t == UI_DEFAULT else ""
        print(f"  {t:5.1f}     {empty:4d} / {len(counts):-4d}  ({pct:5.1f}%)"
              f"        {statistics.mean(counts):.2f}{mark}")

    if len(libs) > 1:
        print(f"\n  controls with 0 chunks at the UI default ({UI_DEFAULT}), by library:")
        for lib in libs:
            rows = [d for d in per_control.values() if d["lib"] == lib]
            if not rows:
                continue
            empty = sum(1 for d in rows if survivors(d["rows"], args.k, UI_DEFAULT) == 0)
            print(f"    {lib:<16} {empty:4d} / {len(rows):-4d}"
                  f"  ({100.0 * empty / len(rows):5.1f}%)")
        print("  -> wide variation here means the threshold is a different")
        print("     standard depending on which library a control came from.")

    # ---------- 3 ----------
    print("\n" + "=" * 70)
    print(f"3. ATTRIBUTION at threshold {UI_DEFAULT}, k={args.k}")
    print("=" * 70)
    starved = [k for k, d in per_control.items()
               if survivors(d["rows"], args.depth, UI_DEFAULT)
               > survivors(d["rows"], args.k, UI_DEFAULT)]
    print(f"  controls with qualifying chunks below rank {args.k}: "
          f"{len(starved)} / {len(per_control)}")
    print("  -> for these, evidence passes the threshold but never reaches the")
    print(f"     assessor, because top-{args.k} truncates first. Lowering the")
    print("     slider cannot recover them; only raising k can.")
    if starved:
        print("\n  examples:")
        for k in starved[:5]:
            d = per_control[k]
            deep = survivors(d["rows"], args.depth, UI_DEFAULT)
            near = survivors(d["rows"], args.k, UI_DEFAULT)
            print(f"    {k}: {near} reach the assessor, {deep} qualify")

    # ---------- 4 ----------
    print("\n" + "=" * 70)
    print("4. QUERY-LENGTH BIAS - do wordier controls score higher?")
    print("=" * 70)
    xs = [d["terms"] for d in per_control.values() if d["rows"]]
    ys = [d["rows"][0][3] for d in per_control.values() if d["rows"]]
    r = safe_corr(xs, ys)
    if r is None:
        print("  not enough variation to compute a correlation")
    else:
        print(f"  correlation(query terms, top score) = {r:+.2f}")
        if r > 0.4:
            print("  -> strong bias. A global threshold is a harder standard for")
            print("     terse controls. Normalise (score / query terms) or set the")
            print("     threshold per library before trusting any reported gap.")
        elif r > 0.2:
            print("  -> mild bias. Worth normalising.")
        else:
            print("  -> little bias. A global threshold is defensible on this axis.")
    print(f"  query terms: min {min(xs)}  median {statistics.median(xs):.0f}  max {max(xs)}")

    if len(libs) > 1:
        print("\n  mean query terms by library (crosswalk columns, and the MAS")
        print("  'Expectation: ... Source: ...' prefix, both inflate this):")
        for lib in libs:
            vals = [d["terms"] for d in per_control.values() if d["lib"] == lib]
            if vals:
                print(f"    {lib:<16} {statistics.mean(vals):6.1f}")

    print(f"\nFull per-chunk detail in {out}")


if __name__ == "__main__":
    main()
