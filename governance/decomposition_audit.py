"""Decomposition quality — is this element set a decomposition, or the control restated?

Six defect classes, each one found in the live 562-element library rather than imagined:

  EMPTY_ELEMENT          the element text is the control id, or is too short to state anything
  TEMPLATE_WRAPPED       "The organization must ensure that <fragment>" — the control description
                         wrapped in a stock prefix, usually leaving it ungrammatical
  TITLE_ECHO             the element restates its own control title
  DUPLICATE_OBLIGATION   two elements carry identical text
  TEMPLATED_SET          the whole element set is an archetype with the control title spliced in,
                         so several unrelated controls end up with the same requirements
  TEST_PROCEDURE         the element is an instruction to a tester, not an obligation

The one that matters most is TEMPLATED_SET, because it is invisible to every other check. The
ids are unique, the texts differ character by character, nothing is empty, and the contract
validates — yet five controls carry the same four requirements with a different noun dropped in.
An assessor scoring them is scoring the template. Detection normalises the control title out
first, which is the only way the collapse becomes visible.

The audit reports. It does not rewrite, because the correct text for a templated element is a
decomposition of that control's source, and nothing mechanical can supply it — generating a
replacement automatically is how the defect got there.
"""
from __future__ import annotations

import collections
import re
from typing import Any, Iterable

SCHEMA = "decomposition-audit.1"

_TEMPLATE_PREFIXES = (
    re.compile(r"^the organi[sz]ation must ensure that\b", re.I),
    re.compile(r"^the (?:fi|entity|firm) must ensure that\b", re.I),
    re.compile(r"^it must be ensured that\b", re.I),
)

_PROCEDURE = re.compile(
    r"^(obtain|sample|inspect|trace|re-?perform|walk through|select a sample|compare the|"
    r"review the (?:sample|population)|confirm that the tester)\b", re.I)

#: An element shorter than this cannot state an obligation with a subject and a predicate.
MIN_WORDS = 5


def _norm(text: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower()).split())


def _skeleton(text: str, title: str) -> str:
    """Element text with its control's title normalised out.

    This is the whole trick. `"...authority boundary for Agent mandate definition — permitted
    actions..."` and `"...authority boundary for Gateway interception of actions — permitted
    actions..."` are different strings and the same requirement.
    """
    t, ti = _norm(text), _norm(title)
    return t.replace(ti, "<TITLE>") if ti and len(ti) > 6 and ti in t else t


def audit_control(control: dict) -> list[dict[str, Any]]:
    """Per-element defects for one control. Set-level defects come from `audit_library`."""
    cid = str(control.get("control_id") or control.get("id") or "")
    title = str(control.get("title") or "")
    out: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    for e in control.get("elements") or []:
        eid = str(e.get("id") or "")
        text = str(e.get("text") or "").strip()
        ref = f"{cid}.{eid}"

        if not text or _norm(text) == _norm(cid) or len(text.split()) < MIN_WORDS:
            out.append({"code": "EMPTY_ELEMENT", "ref": ref, "severity": "error",
                        "detail": f"element text is {text!r}"})
            continue

        for pat in _TEMPLATE_PREFIXES:
            if pat.match(text):
                out.append({"code": "TEMPLATE_WRAPPED", "ref": ref, "severity": "error",
                            "detail": f"stock prefix wrapping a fragment: {text[:80]!r}"})
                break

        if _PROCEDURE.match(text):
            out.append({"code": "TEST_PROCEDURE", "ref": ref, "severity": "error",
                        "detail": f"instruction to a tester, not an obligation: {text[:70]!r}"})

        if title and len(_norm(title)) > 6 and _norm(title) in _norm(text):
            out.append({"code": "TITLE_ECHO", "ref": ref, "severity": "warning",
                        "detail": "element restates its own control title"})

        key = _norm(text)
        if key in seen:
            out.append({"code": "DUPLICATE_OBLIGATION", "ref": ref, "severity": "error",
                        "detail": f"identical to {seen[key]}"})
        else:
            seen[key] = ref

    return out


def audit_library(controls: Iterable[dict]) -> dict[str, Any]:
    """Whole-library audit, including the set-level defect no per-control check can see."""
    rows = list(controls)
    findings: list[dict[str, Any]] = []
    for c in rows:
        findings.extend(audit_control(c))

    # TEMPLATED_SET — controls whose title-normalised element skeletons are identical.
    sigs: dict[tuple, list[str]] = collections.defaultdict(list)
    for c in rows:
        title = str(c.get("title") or "")
        sig = tuple(_skeleton(str(e.get("text") or ""), title)
                    for e in (c.get("elements") or []))
        if sig:
            sigs[sig].append(str(c.get("control_id") or c.get("id") or ""))
    for sig, cids in sigs.items():
        if len(cids) > 1:
            for cid in cids:
                findings.append({
                    "code": "TEMPLATED_SET", "ref": cid, "severity": "error",
                    "detail": (f"element set is an archetype shared with "
                               f"{', '.join(c for c in cids if c != cid)}; "
                               f"{len(sig)} element(s) differ only by the control title")})

    # Cross-control identical element text, distinct from a whole shared set.
    by_text: dict[str, list[str]] = collections.defaultdict(list)
    for c in rows:
        cid = str(c.get("control_id") or c.get("id") or "")
        for e in (c.get("elements") or []):
            by_text[_norm(e.get("text"))].append(f"{cid}.{e.get('id')}")
    for text, refs in by_text.items():
        if len(refs) > 1 and text:
            findings.append({"code": "SHARED_ELEMENT_TEXT", "ref": refs[0], "severity": "warning",
                             "detail": f"identical text at {', '.join(refs[1:])}"})

    # A ref is either a control id ("S1.2") or an element ref ("A.5.2.e1"), and control ids
    # themselves contain dots. Splitting on the first dot mapped every ISO and NIST finding to a
    # framework of "?" — resolve by longest matching control id instead.
    by_fw: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    fw_of = {str(c.get("control_id") or c.get("id")): str(c.get("framework") or "?") for c in rows}
    by_len = sorted(fw_of, key=len, reverse=True)

    def _framework(ref: str) -> str:
        for cid in by_len:
            if ref == cid or ref.startswith(cid + "."):
                return fw_of[cid]
        return "?"

    for f in findings:
        by_fw[_framework(str(f["ref"]))][f["code"]] += 1
        f["framework"] = _framework(str(f["ref"]))

    codes = collections.Counter(f["code"] for f in findings)
    errors = [f for f in findings if f["severity"] == "error"]
    return {
        "schema": SCHEMA,
        "n_controls": len(rows),
        "n_elements": sum(len(c.get("elements") or []) for c in rows),
        "findings": findings,
        "by_code": dict(codes),
        "by_framework": {k: dict(v) for k, v in by_fw.items()},
        "error_count": len(errors),
        "warning_count": len(findings) - len(errors),
        "clean": not errors,
    }


def report(a: dict[str, Any]) -> str:
    lines = [f"{a['n_controls']} control(s), {a['n_elements']} element(s) — "
             f"{a['error_count']} error(s), {a['warning_count']} warning(s)"]
    for code, n in sorted(a["by_code"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {code:22} {n}")
    lines.append("  by framework:")
    for fw, codes in sorted(a["by_framework"].items()):
        lines.append(f"    {fw:14} {codes}")
    return "\n".join(lines)
