"""Versioned MAS regulatory-change draft workflow.

The live requirements/mas.yaml is never edited by this module. A change is drafted under
requirements/drafts/, impact-scoped, tested in shadow mode, approved, and only then promoted.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
import hashlib
import json
import yaml

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "requirements" / "mas.yaml"
DRAFT_DIR = ROOT / "requirements" / "drafts"


def _sha(obj) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def load_requirements(path: Path | str = LIVE) -> dict:
    return yaml.safe_load(Path(path).read_text()) or {}


def control_diff(current: dict, proposed: dict) -> dict:
    a = current.get("controls") or {}
    b = proposed.get("controls") or {}
    changed, added, removed = [], [], []
    for cid in sorted(set(a) | set(b)):
        if cid not in a:
            added.append(cid)
        elif cid not in b:
            removed.append(cid)
        elif a[cid] != b[cid]:
            changed.append(cid)
    return {"added": added, "removed": removed, "changed": changed}


def build_draft(proposed_controls: dict, *, source_title: str, source_reference: str,
                effective_from: str | None = None, change_ticket: str | None = None,
                notes: str = "") -> dict:
    current = load_requirements()
    proposal = deepcopy(current)
    proposal["version"] = str(proposal.get("version", "")) + "-DRAFT"
    proposal["status"] = "draft"
    proposal["draft"] = True
    proposal["regulatory_change"] = {
        "source_title": source_title,
        "source_reference": source_reference,
        "effective_from": effective_from,
        "change_ticket": change_ticket,
        "notes": notes,
        "drafted_on": date.today().isoformat(),
        "base_version": current.get("version"),
        "base_sha256": _sha(current),
    }
    proposal["controls"] = proposed_controls
    proposal["change_impact"] = control_diff(current, proposal)
    proposal["change_impact"]["control_count"] = len(proposal["controls"])
    return proposal


def validate_draft(draft: dict) -> list[str]:
    errors: list[str] = []
    meta = draft.get("regulatory_change") or {}
    for k in ("source_title", "source_reference", "base_version", "base_sha256"):
        if not meta.get(k):
            errors.append(f"missing regulatory_change.{k}")
    if draft.get("status") != "draft" or draft.get("draft") is not True:
        errors.append("draft must have status=draft and draft=true")
    controls = draft.get("controls") or {}
    if not isinstance(controls, dict) or not controls:
        errors.append("controls mapping is required")
    return errors


def save_draft(draft: dict, path: Path | str | None = None) -> Path:
    errors = validate_draft(draft)
    if errors:
        raise ValueError("invalid draft: " + "; ".join(errors))
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    target = Path(path) if path else DRAFT_DIR / f"mas-{date.today().isoformat()}-draft.yaml"
    target.write_text(yaml.safe_dump(draft, sort_keys=False, allow_unicode=False))
    return target


def promote_draft(path: Path | str, *, approved_by: str, change_ticket: str) -> Path:
    p = Path(path)
    draft = load_requirements(p)
    if validate_draft(draft):
        raise ValueError("cannot promote invalid draft")
    if not approved_by or not change_ticket:
        raise ValueError("approved_by and change_ticket are required")
    # Promotion is explicit and creates a separate immutable release file. Caller then
    # switches the live pointer under normal change control; this function never overwrites LIVE.
    releases = ROOT / "requirements" / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    promoted = deepcopy(draft)
    promoted["status"] = "approved"
    promoted["draft"] = False
    promoted["approval"] = {"approved_by": approved_by, "change_ticket": change_ticket, "approved_on": date.today().isoformat()}
    out = releases / (p.stem.replace("-draft", "") + "-approved.yaml")
    out.write_text(yaml.safe_dump(promoted, sort_keys=False, allow_unicode=False))
    return out


def impact_report(draft: dict, testing_catalog: dict | None = None) -> dict:
    """Create a control-by-control impact report for a regulatory draft."""
    current = load_requirements()
    diff = control_diff(current, draft)
    cat = (testing_catalog or {}).get("controls") or []
    by_id = {x.get("control_id"): x for x in cat if isinstance(x, dict)}
    affected = []
    for cid in sorted(set(diff["changed"] + diff["added"] + diff["removed"])):
        row = {"control_id": cid, "change_type": "changed" if cid in diff["changed"] else "added" if cid in diff["added"] else "removed"}
        if cid in by_id:
            row["design_test_id"] = by_id[cid].get("design_test_id")
            row["operating_test_id"] = by_id[cid].get("operating_test_id")
        row["requires_test_review"] = True
        affected.append(row)
    return {"base_version": current.get("version"), "draft_version": draft.get("version"), "affected_controls": affected, "counts": {"changed": len(diff["changed"]), "added": len(diff["added"]), "removed": len(diff["removed"])}}
