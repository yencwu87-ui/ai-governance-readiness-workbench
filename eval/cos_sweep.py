"""Measure cosine similarity per control against a real evidence folder.

The question this answers: can ONE cosine threshold serve all five control
libraries, or does it starve the terse ones the way an absolute BM25 floor did?

Requires Ollama running with the embedding model pulled:
    ollama pull nomic-embed-text

    python eval/cos_sweep.py --folder <evidence folder> \
        --playbook data/AI_Governance_Playbook_..._v3_CSA_backref.xlsx

First run embeds every chunk and every control query, which is slow; vectors are
cached to retriever/.cache/embeddings.jsonl so later runs are fast.
"""

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import retriever  # noqa: E402
from playbook import load_controls  # noqa: E402
from retriever import HybridIndex, chunk_documents  # noqa: E402
from scanner import DOC_EXT, extract, iter_files  # noqa: E402

GRID = [0.0, 0.20, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70]


def read_docs(folder: str) -> dict[str, str]:
    """Reuse scanner's extractors and skip rules, hand the text to retriever's chunker."""
    docs = {}
    for p in iter_files(folder, DOC_EXT):
        docs[str(p)] = extract(p)
    return docs


def query_for(c) -> str:
    return f"{c.title} {c.req} {c.maps}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--playbook", required=True)
    ap.add_argument("--scope", default=None, help="comma-separated libraries (default: all)")
    ap.add_argument("--k", type=int, default=3)
    a = ap.parse_args()

    by_lib = load_controls(a.playbook)
    libs = [s.strip() for s in a.scope.split(",")] if a.scope else sorted(by_lib)
    in_scope = [(lib, c) for lib in libs for c in by_lib.get(lib, [])]
    print(f"{len(in_scope)} controls across {libs}")

    print(f"reading {a.folder} ...")
    docs = read_docs(a.folder)
    chunks = chunk_documents(docs)
    print(f"  {len(chunks)} chunks from {len(docs)} documents")
    print("embedding (first run is slow, then cached) ...")
    index = HybridIndex(chunks, use_embeddings=True)
    print(f"  embeddings: {index.embed_status}")
    if index.vectors is None:
        raise SystemExit(
            "Embeddings unavailable, so there is no cosine to measure.\n"
            "Start Ollama and run: ollama pull " + retriever.EMBED_MODEL
        )

    # best cosine per control
    best = {}
    for n, (lib, c) in enumerate(in_scope, 1):
        if n % 25 == 0:
            print(f"  {n}/{len(in_scope)}")
        hits = index.search(query_for(c), k=a.k, min_cos=0.0)
        best[c.key] = (lib, max((h.cos or 0.0) for h in hits) if hits else 0.0)

    print("\n" + "=" * 70)
    print("BEST COSINE PER CONTROL — is one threshold defensible?")
    print("=" * 70)
    allv = sorted(v for _, v in best.values())
    print(f"  ALL              min {allv[0]:.3f}   median {statistics.median(allv):.3f}   max {allv[-1]:.3f}")
    print()
    for lib in libs:
        vals = sorted(v for l, v in best.values() if l == lib)
        if vals:
            print(f"  {lib:<16} min {vals[0]:.3f}   median {statistics.median(vals):.3f}   max {vals[-1]:.3f}")

    print("\n  weakest 10 controls:")
    for key, (lib, v) in sorted(best.items(), key=lambda kv: kv[1][1])[:10]:
        print(f"    {v:.3f}  {key}")

    print("\n" + "=" * 70)
    print(f"MIN_COS SWEEP (k={a.k})")
    print("=" * 70)
    header = "  min_cos   overall  " + "".join(f"{lib[:11]:>13}" for lib in libs)
    print(header)
    for t in GRID:
        kept = {key: (lib, v) for key, (lib, v) in best.items() if v >= t}
        row = "".join(
            f"{sum(1 for l, _ in kept.values() if l == lib):>6d} /{len(by_lib.get(lib, [])):>4d}"
            for lib in libs
        )
        print(f"  {t:5.2f}    {len(kept):4d}/{len(best):-4d}  {row}")

    print("\nWhat to look for: if the per-library columns fall away together, one")
    print("threshold works and you can pick it from the overall distribution. If")
    print("one library empties far ahead of the others, cosine is tracking control")
    print("wordiness too and needs per-library values — the same failure the")
    print("absolute BM25 floor had. Either way, open the folder and check a few")
    print("dropped controls by hand before trusting a 'no evidence' result.")


if __name__ == "__main__":
    main()
