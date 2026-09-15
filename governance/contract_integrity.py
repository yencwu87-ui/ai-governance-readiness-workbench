"""GE-110a — contract integrity. A corrupted contract is not assessable.

Three classes of corruption were found in the workbook currently sitting in `data/`, all of them
silent, and all of them reaching the assessor as if authoritative:

  A. **Wrong control content.** M1.1 (board and senior management accountability) carries M3.6's
     evaluation elements verbatim. Not a paraphrase — the same string.

  B. **Requirement sentences in the artefact column.** "Post-implementation verification and
     closure or exception handling are required" is a requirement, not a document anybody can
     produce. 26 of 195 controls carry a sentence where an artefact name belongs. The WB-103
     completeness pass matches declared artefacts against scanned documents, so for those 26 it
     is matching against sentences no file will ever be named after.

  C. **Generated material in the authoritative path.** `data/` holds
     `…_requirement_elements_audited.xlsx` — an exported workbook. `write_back` overwrites the
     "Evidence / artifact" column with evidence text, which is almost certainly how (B) happened.
     A file the tool produced became the file the tool reads.

The design decision that matters here is the verdict, not the checks.

    warning → continue        an assessment runs against a contract known to be wrong, and its
                              output looks exactly like an assessment against a good one

    CONTRACT_INVALID          the assessment does not execute

The second is the only one consistent with how the rest of this system already behaves: a failed
assessor call is not a rating of `none`, a bundle below the document floor is NOT_TESTABLE rather
than all-gaps, and a blocked challenge run is not a clean one. "I could not test this" is a
result here. An unassessable contract is the same shape of fact.

Severity is two-valued on purpose. `error` blocks; `warning` does not and never escalates on
volume. A count of warnings that eventually blocks is a threshold nobody chose.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "ge110a.contract-integrity.1"

VALID = "VALID"
INVALID = "CONTRACT_INVALID"

#: Filename shapes this tool is known to write. A contract loaded from one of these is reading
#: its own output back as authority.
GENERATED_PATTERNS = (
    re.compile(r"playbook_assessed", re.I),
    re.compile(r"_assessed[_.]", re.I),
    re.compile(r"assessments.*\.json$", re.I),
)

#: Shapes that *might* be generated. A filename cannot tell "a person audited this" from "the
#: tool wrote this" — the live workbook is `…_requirement_elements_audited.xlsx`, and `audited`
#: reads both ways. Treating that as an error blocked all 195 controls on a guess, which is a
#: checker asserting something it does not know.
#:
#: These warn. The durable fix is not a better regex: it is a provenance marker written into the
#: workbook by whatever produces it, so the question stops being answered by inference.
AMBIGUOUS_PATTERNS = (
    re.compile(r"_audited[_.]", re.I),
    re.compile(r"_export(ed)?[_.]", re.I),
)

#: A verb that turns a noun phrase into a claim. An artefact is a thing you can hand to an
#: auditor; the moment it asserts something it is a requirement.
_PREDICATE = re.compile(
    r"\b(are|is|was|were|must|should|shall|has been|have been|requires?|ensures?|defines?|"
    r"links?|demonstrates?|covers?)\b", re.I)

_PLACEHOLDER = {"", "-", "--", "n/a", "na", "none", "tbd", "tbc", "todo", "see above",
                "as applicable", "as required", "various", "refer to policy"}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).split())


def _finding(code: str, severity: str, message: str, **extra) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, **extra}


# ---------------------------------------------------------------- individual checks

def check_duplicate_element_ids(contract: dict) -> list[dict]:
    seen: dict[str, int] = defaultdict(int)
    for e in contract.get("elements") or []:
        seen[str(e.get("id") or "")] += 1
    dupes = sorted(k for k, n in seen.items() if n > 1 and k)
    if not dupes:
        return []
    return [_finding("DUPLICATE_ELEMENT_ID", "error",
                     f"element id(s) {', '.join(dupes)} appear more than once — an element id is "
                     f"the join key for every stored verdict, so a duplicate makes those "
                     f"judgements unattributable", ids=dupes)]


def check_cross_control_contamination(contract: dict,
                                      others: Iterable[dict]) -> list[dict]:
    """An element set identical to another control's.

    Compares the whole set rather than single elements: two controls legitimately sharing one
    obligation is normal, and flagging that would make this check noise. Carrying another
    control's entire decomposition is not normal.
    """
    mine = [_norm(e.get("text")) for e in (contract.get("elements") or []) if e.get("text")]
    if len(mine) < 1:
        return []
    key = tuple(sorted(mine))
    out = []
    for other in others:
        if other is contract:
            continue
        oid = str(other.get("control_id") or other.get("id") or "")
        if oid == str(contract.get("control_id") or contract.get("id") or ""):
            continue
        theirs = tuple(sorted(_norm(e.get("text")) for e in (other.get("elements") or [])
                              if e.get("text")))
        if theirs and theirs == key:
            out.append(_finding(
                "CROSS_CONTROL_ELEMENT_CONTAMINATION", "error",
                f"element set is identical to {oid} — one of the two controls is carrying the "
                f"other's decomposition, and an assessment against it tests the wrong "
                f"requirement", other_control=oid, element_count=len(mine)))
    return out


def check_requirement_used_as_artefact(artefacts: Iterable[str]) -> list[dict]:
    """An artefact name that asserts something is a requirement wearing the wrong label."""
    out = []
    for a in artefacts or []:
        text = str(a).strip()
        if len(text) < 20:
            continue
        if _PREDICATE.search(text):
            out.append(_finding(
                "REQUIREMENT_AS_ARTEFACT", "error",
                f"declared artefact asserts a requirement rather than naming a document: "
                f"{text[:90]!r} — the completeness pass matches artefact names against scanned "
                f"files, and nothing will ever be named this", artefact=text))
    return out


def check_generated_source(source_path: str | Path | None) -> list[dict]:
    if not source_path:
        return []
    name = Path(str(source_path)).name
    for pat in GENERATED_PATTERNS:
        if pat.search(name):
            return [_finding(
                "GENERATED_SOURCE_IN_AUTHORITATIVE_PATH", "error",
                f"{name!r} is a filename this tool writes. `write_back` overwrites the "
                f"evidence/artefact column with evidence text, so reading it back as the "
                f"contract launders the tool's own output into authority",
                source=str(source_path), matched=pat.pattern)]
    for pat in AMBIGUOUS_PATTERNS:
        if pat.search(name):
            return [_finding(
                "SOURCE_PROVENANCE_UNDECLARED", "warning",
                f"{name!r} may be a generated file — the name does not say whether a person or "
                f"this tool produced it. Write a provenance marker into the workbook rather than "
                f"leaving it to the filename",
                source=str(source_path), matched=pat.pattern)]
    return []


def check_placeholder_evidence(artefacts: Iterable[str], contract: dict) -> list[dict]:
    arts = [str(a).strip() for a in (artefacts or []) if str(a).strip()]
    real = [a for a in arts if _norm(a) not in _PLACEHOLDER]
    if not arts:
        return [_finding("NO_DECLARED_EVIDENCE", "warning",
                         "the control declares no expected artefacts — completeness cannot be "
                         "checked, and a `partial` cannot be gated on missing evidence")]
    if not real:
        return [_finding("PLACEHOLDER_EVIDENCE_ONLY", "error",
                         f"every declared artefact is a placeholder ({', '.join(arts[:3])}) — "
                         f"a placeholder cannot be found or not found, so the control reads as "
                         f"complete whatever the bundle holds", artefacts=arts)]
    return []


def check_write_back_provenance(contract: dict) -> list[dict]:
    """The contract's own provenance statement versus what it actually contains.

    `test_provenance` on the audited workbook reads: "requirement elements derived from the
    source requirement/outcome only. ToD/ToE, evidence floors, challenge banks and internet
    knowledge do not create requirement obligations." Where an element is verbatim a ToD or ToE
    step, the file contradicts its own declaration.
    """
    prov = str(contract.get("test_provenance") or "")
    steps = [_norm(x.get("text")) for x in
             ((contract.get("test_of_design") or []) +
              (contract.get("test_of_operating_effectiveness") or []))
             if x.get("text")]
    if not steps:
        return []
    bad = []
    for e in contract.get("elements") or []:
        t = _norm(e.get("text"))
        if len(t) < 25:
            continue
        if any(t == s or t in s or s in t for s in steps):
            bad.append(str(e.get("id")))
    if not bad:
        return []
    return [_finding(
        "WRITE_BACK_PROVENANCE_MISMATCH", "error",
        f"element(s) {', '.join(bad)} are verbatim test steps, which this contract's own "
        f"test_provenance forbids" + (f" ({prov[:60]}…)" if prov else "") +
        " — a procedure is an instruction to the tester, not an obligation on the organisation",
        elements=bad)]


# ---------------------------------------------------------------- the gate

class ContractInvalid(RuntimeError):
    """Raised instead of assessing. Carries the report so the caller can show it."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        errs = [f for f in report["findings"] if f["severity"] == "error"]
        super().__init__(
            f"CONTRACT_INVALID — {report.get('control_id')}: {len(errs)} integrity error(s). "
            + "; ".join(f["code"] for f in errs))


def validate_contract(contract: dict, *, artefacts: Iterable[str] | None = None,
                      others: Iterable[dict] | None = None,
                      source_path: str | Path | None = None) -> dict[str, Any]:
    """Full integrity report for one control contract.

    `artefacts` is passed separately because the declared-artefact list lives on the workbook row
    (`Control.artefacts`) rather than in the contract YAML — the two sources are exactly what
    drift apart, so the checker is given both rather than trusting either.
    """
    findings: list[dict] = []
    findings += check_duplicate_element_ids(contract)
    findings += check_cross_control_contamination(contract, others or [])
    findings += check_requirement_used_as_artefact(artefacts or [])
    findings += check_generated_source(source_path)
    findings += check_placeholder_evidence(artefacts or [], contract)
    findings += check_write_back_provenance(contract)

    errors = [f for f in findings if f["severity"] == "error"]
    return {
        "schema": SCHEMA,
        "control_id": contract.get("control_id") or contract.get("id") or "",
        "framework": contract.get("framework") or "",
        "status": INVALID if errors else VALID,
        "executable": not errors,
        "error_count": len(errors),
        "warning_count": len(findings) - len(errors),
        "findings": findings,
        "source_path": str(source_path) if source_path else None,
    }


def assert_executable(contract: dict, **kw) -> dict[str, Any]:
    """Validate and raise `ContractInvalid` rather than returning a status nobody checks.

    Returning a report is easy to ignore; every caller has to remember to look at it, and one
    that forgets produces an assessment indistinguishable from a sound one. Raising moves the
    decision from every call site to this one.
    """
    report = validate_contract(contract, **kw)
    if not report["executable"]:
        raise ContractInvalid(report)
    return report


def summarise(report: dict[str, Any]) -> str:
    if report["executable"]:
        n = report["warning_count"]
        return f"Contract valid{f' — {n} warning(s)' if n else ''}."
    lines = [f"CONTRACT_INVALID — assessment not executable for "
             f"{report.get('control_id') or 'this control'}."]
    for f in report["findings"]:
        if f["severity"] == "error":
            lines.append(f"  · {f['code']}: {f['message']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- service seam

def status_for_control(control, *, source_path: str | Path | None = None) -> dict[str, Any]:
    """Integrity status for a live `playbook.Control`.

    The assembly lives here rather than in the caller. A contract is scattered across three
    places — the YAML block, the workbook's artefact column, and the rest of the library for the
    contamination comparison — and any caller that gathers them itself becomes a second
    implementation of what a contract is. `app.py` asks for a status and gets one.

    Never raises. An integrity check that can itself fail closed would take the application down
    over a malformed row in a library the check exists to find fault with; a load failure is
    reported as a finding like any other.
    """
    cid = str(getattr(control, "id", "") or "")
    lib = str(getattr(control, "lib", "") or "")
    try:
        from governance.control_contract import get_control_contract, load_contracts, _framework_path
        contract = get_control_contract(cid, lib) or {"control_id": cid, "framework": lib}
        others = load_contracts(_framework_path(lib)).get("controls") or []
    except Exception as exc:
        return {"schema": SCHEMA, "control_id": cid, "framework": lib, "status": INVALID,
                "executable": False, "error_count": 1, "warning_count": 0,
                "findings": [_finding("CONTRACT_UNREADABLE", "error",
                                      f"the control contract could not be loaded: {exc}")],
                "source_path": str(source_path) if source_path else None}

    raw = str(getattr(control, "artefacts", "") or "").replace("\n", ";")
    artefacts = [a.strip() for a in raw.split(";") if a.strip()]
    return validate_contract(contract, artefacts=artefacts, others=others,
                             source_path=source_path)


def blocking_summary(report: dict[str, Any]) -> dict[str, int]:
    """Error codes and their counts — what the UI shows instead of a wall of sentences."""
    out: dict[str, int] = {}
    for f in report.get("findings") or []:
        if f.get("severity") == "error":
            out[f["code"]] = out.get(f["code"], 0) + 1
    return out


def warning_summary(report: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in report.get("findings") or []:
        if f.get("severity") == "warning":
            out[f["code"]] = out.get(f["code"], 0) + 1
    return out
