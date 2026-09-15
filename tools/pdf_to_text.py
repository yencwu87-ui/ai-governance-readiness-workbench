#!/usr/bin/env python3
"""WB-065 — convert source instruments to text, and record what was converted.

`draft_elements.py` anchors every proposed element in a verbatim quote from an instrument. That
anchor is only as good as the knowledge of *which* document, and which version of it, the quote
came from. A folder of .txt files with no provenance is the same failure as the corpus labels that
went stale under a changed requirement: the anchor still matches, and it no longer means anything.

So this writes a manifest beside the text — filename, SHA-256 of the source PDF, page count, word
count, and a caller-supplied authority note. A draft can then say not just "anchored in the MGF"
but "anchored in this MGF, this file, this hash".

    python tools/pdf_to_text.py whitepapers/ --out instruments/
    python tools/pdf_to_text.py whitepapers/SAFR.pdf --out instruments/ \
        --authority "MAS / BuildFin.ai SAFR white paper, 3 Jul 2026 — industry paper, not a rule"

Extraction is deliberately plain. Ligatures and hyphenation at line breaks are repaired because
they break verbatim matching; nothing else is normalised, because every further cleanup is a
chance to alter the words the anchor is supposed to hold.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

#: Repaired because they silently defeat a verbatim check: a quote copied by a model from
#: rendered text will not contain the ligature or the line-break hyphen.
_LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
              "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
              "\u2013": "-", "\u2014": "-", "\u00a0": " "}


def clean(text: str) -> str:
    for bad, good in _LIGATURES.items():
        text = text.replace(bad, good)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)      # hyphenation across a line break
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def convert(pdf: Path, out_dir: Path) -> dict:
    from pypdf import PdfReader
    raw = pdf.read_bytes()
    reader = PdfReader(str(pdf))
    pages = [(p.extract_text() or "") for p in reader.pages]
    text = clean("\n\n".join(pages))
    target = out_dir / (pdf.stem.replace(" ", "_") + ".txt")
    target.write_text(text, encoding="utf-8")
    words = len(text.split())
    return {
        "source_pdf": pdf.name,
        "text_file": target.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "pages": len(reader.pages),
        "words": words,
        "converted_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        # A scanned PDF extracts almost nothing and would silently produce a draft anchored in
        # whitespace. Say so here rather than letting it fail quietly downstream.
        "usable": words > 500,
        "warning": None if words > 500 else
                   "little or no extractable text — this PDF is probably scanned and needs OCR "
                   "before it can anchor anything",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="a PDF or a folder of them")
    ap.add_argument("--out", type=Path, default=Path("instruments"))
    ap.add_argument("--authority", default="",
                    help="what this document IS — a rule, a guideline, a consultation draft, a "
                         "voluntary playbook. Recorded in the manifest and worth the sentence.")
    a = ap.parse_args()

    pdfs = ([a.source] if a.source.is_file() else sorted(a.source.glob("*.pdf")))
    if not pdfs:
        sys.exit(f"no PDF found at {a.source}")
    a.out.mkdir(parents=True, exist_ok=True)

    manifest_path = a.out / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"instruments": {}}

    for pdf in pdfs:
        row = convert(pdf, a.out)
        if a.authority:
            row["authority"] = a.authority
        prev = manifest["instruments"].get(row["text_file"])
        if prev and prev.get("sha256") != row["sha256"]:
            # The instrument changed under drafts that were anchored in it. Same class of event
            # as a requirement changing under a corpus label, and it gets the same treatment:
            # reported, not silently overwritten.
            row["supersedes_sha256"] = prev["sha256"]
            print(f"  !! {row['text_file']} changed since the last conversion "
                  f"({prev['sha256'][:12]} -> {row['sha256'][:12]}). Any draft anchored in the "
                  f"previous version needs re-checking.")
        manifest["instruments"][row["text_file"]] = row
        flag = "" if row["usable"] else "   NOT USABLE"
        print(f"  {row['source_pdf'][:46]:48} -> {row['text_file'][:38]:40} "
              f"{row['pages']:3}p {row['words']:6}w  {row['sha256'][:12]}{flag}")
        if row["warning"]:
            print(f"      {row['warning']}")

    manifest["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    manifest_path.write_text(json.dumps(manifest, indent=1))
    print(f"\nmanifest: {manifest_path}")
    missing = [k for k, v in manifest["instruments"].items() if not v.get("authority")]
    if missing:
        print("\nNo authority note recorded for: " + ", ".join(missing))
        print("Re-run with --authority for each. A draft anchored in a consultation paper and one "
              "anchored in\na final rule look identical in the output otherwise, and they are not "
              "the same claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
