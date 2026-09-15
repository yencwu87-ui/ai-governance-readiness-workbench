"""GE-110b.3 — deterministic ownership for the measurement layer.

Three times in this project a file under `eval/` has been modified between one operation and the
next by something other than the designated writer. The third occurrence left
`label_provenance.py` internally inconsistent — `summary()` calling a key `calibration_admissible()`
no longer returned — and the module raised `KeyError` at import-time use.

The content of that mutation was not the problem. Some of it was an improvement. The problem is
that a characterisation result is only meaningful if you can say exactly which source produced
it, and a shared scratch surface cannot support that claim. A measurement instrument whose own
code changes without record is not an instrument.

So: one designated writer per file, a hash manifest, and a test that fails on any unrecorded
mutation. The manifest does not prevent a change — nothing here can — it makes the change
*visible* at the moment it happens rather than three operations later when something breaks.

Two classes, deliberately different:

  `source`     the measurement code itself. A hash mismatch is a failure. Changing one of these
               means updating the manifest in the same operation, which is the record.

  `data`       corpora, labels, characterisation output. These change as work proceeds and their
               hashes are recorded for provenance, not enforced. A measurement report can then
               cite exactly which corpus state it ran against.

Updating the manifest is a deliberate act: `python -m eval.source_integrity --adopt --owner NAME`.
There is no automatic refresh, because a manifest that silently re-pins itself records nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "ge110b3.source-integrity.1"
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "eval" / "SOURCE_MANIFEST.json"

#: The measurement layer's source. Mutation of these without a manifest update is a test failure.
SOURCE_FILES = (
    "eval/label_provenance.py",
    "eval/corpus_adequacy.py",
    "eval/corpus_labels.py",
    "eval/source_integrity.py",
    "eval/measurement_run.py",
    "eval/evaluators.py",
)

#: Provenance-recorded, not enforced.
DATA_GLOBS = (
    "eval/corpus/*/elements.yaml",
    "eval/corpus/*/LABELS.md",
    "eval/corpus/*/AUTHORED_CASES.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collect() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rel in SOURCE_FILES:
        p = ROOT / rel
        if p.exists():
            out[rel] = {"sha256": sha256(p), "bytes": p.stat().st_size, "class": "source"}
    for pattern in DATA_GLOBS:
        for p in sorted(ROOT.glob(pattern)):
            rel = str(p.relative_to(ROOT))
            out[rel] = {"sha256": sha256(p), "bytes": p.stat().st_size, "class": "data"}
    return out


def load_manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def verify() -> dict[str, Any]:
    """Compare the tree against the manifest. Reports; the test decides what fails the build."""
    man = load_manifest()
    recorded = man.get("files") or {}
    current = _collect()

    drifted, added, removed = [], [], []
    for rel, meta in current.items():
        old = recorded.get(rel)
        if old is None:
            added.append({"path": rel, "class": meta["class"]})
        elif old["sha256"] != meta["sha256"]:
            drifted.append({"path": rel, "class": meta["class"],
                            "recorded": old["sha256"][:16], "current": meta["sha256"][:16],
                            "owner": old.get("owner", "unassigned")})
    for rel in recorded:
        if rel not in current:
            removed.append({"path": rel, "class": recorded[rel]["class"]})

    src_drift = [d for d in drifted if d["class"] == "source"]
    src_added = [a for a in added if a["class"] == "source"]
    return {
        "schema": SCHEMA,
        "manifest_present": bool(man),
        "adopted_at": man.get("adopted_at"),
        "adopted_by": man.get("adopted_by"),
        "drifted": drifted,
        "added": added,
        "removed": removed,
        "source_drift": src_drift,
        "unrecorded_source": src_added,
        # Only source drift fails. Data drift is expected and is recorded so a characterisation
        # result can name the corpus state it ran against.
        "ok": not src_drift and not src_added and not [r for r in removed if r["class"] == "source"],
    }


def adopt(owner: str, note: str = "") -> dict[str, Any]:
    """Re-pin the manifest. A deliberate act with a named owner, never automatic."""
    import datetime
    if not owner.strip():
        raise ValueError("adopting a manifest requires a named owner")
    files = _collect()
    prev = (load_manifest().get("files") or {})
    for rel, meta in files.items():
        meta["owner"] = owner.strip()
        if rel in prev and prev[rel]["sha256"] != meta["sha256"]:
            meta["supersedes"] = prev[rel]["sha256"][:16]
    doc = {"schema": SCHEMA,
           "adopted_at": datetime.date.today().isoformat(),
           "adopted_by": owner.strip(),
           "note": note,
           "rule": ("One designated writer per source file. A hash mismatch against this "
                    "manifest is a test failure, not a warning. Data files are recorded for "
                    "provenance and are not enforced."),
           "files": files}
    MANIFEST.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return doc


def report(v: dict[str, Any]) -> str:
    if not v["manifest_present"]:
        return "No manifest. Run --adopt to establish one."
    if v["ok"] and not v["drifted"]:
        return f"Source and data match the manifest adopted {v['adopted_at']} by {v['adopted_by']}."
    lines = [f"Manifest adopted {v['adopted_at']} by {v['adopted_by']}."]
    for d in v["source_drift"]:
        lines.append(f"  SOURCE DRIFT  {d['path']} — recorded {d['recorded']}, now {d['current']} "
                     f"(owner: {d['owner']})")
    for a in v["unrecorded_source"]:
        lines.append(f"  UNRECORDED    {a['path']} — source file absent from the manifest")
    for d in v["drifted"]:
        if d["class"] == "data":
            lines.append(f"  data changed   {d['path']} — {d['recorded']} -> {d['current']}")
    for r in v["removed"]:
        lines.append(f"  removed        {r['path']} ({r['class']})")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--adopt", action="store_true", help="re-pin the manifest to the current tree")
    ap.add_argument("--owner", default="", help="who is taking ownership")
    ap.add_argument("--note", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.adopt:
        doc = adopt(a.owner, a.note)
        print(f"Manifest adopted by {doc['adopted_by']} on {doc['adopted_at']}: "
              f"{len(doc['files'])} file(s).")
        return 0
    v = verify()
    print(json.dumps(v, indent=2) if a.json else report(v))
    return 0 if v["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
