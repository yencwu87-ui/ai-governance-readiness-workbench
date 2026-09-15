"""One canonical source for element text, and a check that the derived views still agree.

The D1.2 incident: the same six elements existed in `control_contracts.yaml`,
`contracts/mgf_agentic.yaml` and `predicate_specs.yaml`. Two were repaired, one was not, and
nothing noticed until an unrelated test asserted the corrected wording and failed. `A.5.2` and
three other ISO elements had drifted the same way into `semantic_registry.yaml` — eleven
elements where the canonical contract said one thing and a derived view said another.

That class of defect is not fixable by being careful. It is fixable by naming one writable
representation and making every other one derived:

    control_contracts.yaml          canonical — element text is authored here and nowhere else
        |
        +-- contracts/<framework>.yaml      derived
        +-- semantic_registry.yaml          derived (field: governed_text)
        +-- predicate_specs.yaml            derived (elements keyed by id)

A derived view may add fields the canon does not carry — `verification`, `expected_evidence`,
predicate specifications, intent. What it may not do is restate the requirement differently,
because then there are two requirements and no way to tell which one an assessment was against.

`check()` reports drift and `sync()` repairs it in one direction only. There is deliberately no
reverse sync: a derived file cannot promote its own wording to canonical, because the whole point
is that authoring happens in one place. Fixing drift by copying the derived text back would make
whichever file was edited last the source of truth, which is where this started.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

SCHEMA = "semantic-canon.1"
ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "governance" / "knowledge"
CANONICAL = KNOWLEDGE / "control_contracts.yaml"


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split())


# ---------------------------------------------------------------- canonical

def canonical_elements(path: Path | None = None) -> dict[tuple[str, str], str]:
    """{(control_id, element_id): text} from the one authored file."""
    doc = yaml.safe_load((path or CANONICAL).read_text(encoding="utf-8")) or {}
    out: dict[tuple[str, str], str] = {}
    for c in doc.get("controls") or []:
        cid = str(c.get("control_id") or c.get("id") or "")
        for e in c.get("elements") or []:
            out[(cid, str(e.get("id")))] = _norm(e.get("text"))
    return out


# ---------------------------------------------------------------- derived views
#
# Each view declares how to walk it. Adding a new derived representation means adding an entry
# here — which is the point: a representation nobody declared is a representation nobody checks.

def _walk_contract(doc: Any) -> Iterable[tuple[str, str, dict, str]]:
    ctrls = doc.get("controls") if isinstance(doc, dict) else doc
    if isinstance(ctrls, dict):
        ctrls = list(ctrls.values())
    for c in ctrls or []:
        cid = str(c.get("control_id") or c.get("id") or "")
        for e in c.get("elements") or []:
            yield cid, str(e.get("id")), e, "text"


def _walk_registry(doc: Any) -> Iterable[tuple[str, str, dict, str]]:
    for c in (doc or {}).get("controls") or []:
        cid = str(c.get("control_id") or "")
        for e in c.get("elements") or []:
            yield cid, str(e.get("id")), e, "governed_text"


def _walk_predicate_specs(doc: Any) -> Iterable[tuple[str, str, dict, str]]:
    """Two shapes in one file: a top-level control, and a `frameworks` block of them."""
    def _one(block: dict):
        cid = str(block.get("control_id") or "")
        els = block.get("elements") or {}
        items = els.items() if isinstance(els, dict) else (
            (str(e.get("id")), e) for e in els)
        for eid, e in items:
            if isinstance(e, dict):
                yield cid, str(eid), e, "text"
    if not isinstance(doc, dict):
        return
    yield from _one(doc)
    fw = doc.get("frameworks")
    if isinstance(fw, dict):
        for block in fw.values():
            for b in (block if isinstance(block, list) else [block]):
                if isinstance(b, dict):
                    yield from _one(b)


DERIVED: list[tuple[str, Callable]] = [
    *[(f"governance/knowledge/contracts/{n}.yaml", _walk_contract)
      for n in ("mas", "mgf_agentic", "safr", "nist_ai_rmf", "iso_42001")],
    ("governance/knowledge/semantic_registry.yaml", _walk_registry),
    ("governance/knowledge/predicate_specs.yaml", _walk_predicate_specs),
]


# ---------------------------------------------------------------- check / sync

def check(root: Path | None = None) -> dict[str, Any]:
    """Every place a derived view restates the requirement differently from the canon."""
    base = root or ROOT
    canon = canonical_elements(base / "governance/knowledge/control_contracts.yaml")
    findings: list[dict[str, Any]] = []
    seen_views = []
    for rel, walk in DERIVED:
        p = base / rel
        if not p.exists():
            continue
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        n = 0
        for cid, eid, el, field in walk(doc):
            n += 1
            key = (cid, eid)
            if key not in canon:
                findings.append({"view": rel, "ref": f"{cid}.{eid}", "code": "NOT_IN_CANON",
                                 "detail": "derived view defines an element the canon does not"})
                continue
            if _norm(el.get(field)) != canon[key]:
                findings.append({
                    "view": rel, "ref": f"{cid}.{eid}", "code": "TEXT_DRIFT",
                    "canonical": canon[key][:120], "derived": _norm(el.get(field))[:120]})
        seen_views.append({"view": rel, "elements": n})
    return {"schema": SCHEMA, "canonical_elements": len(canon), "views": seen_views,
            "findings": findings,
            "drift": len([f for f in findings if f["code"] == "TEXT_DRIFT"]),
            "orphans": len([f for f in findings if f["code"] == "NOT_IN_CANON"]),
            "clean": not findings}


def sync(root: Path | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    """Rewrite derived element text from the canon. One direction, always."""
    base = root or ROOT
    canon = canonical_elements(base / "governance/knowledge/control_contracts.yaml")
    changed: list[dict[str, str]] = []
    for rel, walk in DERIVED:
        p = base / rel
        if not p.exists():
            continue
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        n = 0
        for cid, eid, el, field in walk(doc):
            key = (cid, eid)
            if key in canon and _norm(el.get(field)) != canon[key]:
                changed.append({"view": rel, "ref": f"{cid}.{eid}"})
                el[field] = canon[key]
                n += 1
        if n and not dry_run:
            p.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100),
                         encoding="utf-8")
    return {"schema": SCHEMA, "updated": len(changed), "changes": changed, "dry_run": dry_run}


def report(c: dict[str, Any]) -> str:
    if c["clean"]:
        return (f"{c['canonical_elements']} canonical element(s); "
                f"{len(c['views'])} derived view(s) agree.")
    lines = [f"{c['drift']} drifted, {c['orphans']} orphaned across {len(c['views'])} view(s):"]
    for f in c["findings"][:20]:
        if f["code"] == "TEXT_DRIFT":
            lines.append(f"  {f['ref']:12} {Path(f['view']).name}")
            lines.append(f"     canon  : {f['canonical'][:88]}")
            lines.append(f"     derived: {f['derived'][:88]}")
        else:
            lines.append(f"  {f['ref']:12} {Path(f['view']).name} — {f['detail']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if "--sync" in sys.argv:
        r = sync(dry_run="--dry-run" in sys.argv)
        print(f"{r['updated']} derived element(s) {'would be' if r['dry_run'] else ''} updated")
    else:
        c = check()
        print(report(c))
        raise SystemExit(0 if c["clean"] else 2)
