"""
Generic, deterministic control checks.

Every check has the signature:
    check(ctx: dict[str, list[dict]], params: dict) -> CheckResult

`ctx` maps logical source name -> list of normalised records (from adapters).
Checks never read files, call APIs or use models. They only compare records.
A check returns NOT_TESTABLE when a required source is absent or empty,
so a missing evidence feed is surfaced rather than silently passing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from typing import Any, Callable


@dataclass
class CheckResult:
    verdict: str                       # PASS | FAIL | NOT_TESTABLE
    detail: str
    findings: list[dict] = field(default_factory=list)


REGISTRY: dict[str, Callable[[dict, dict], CheckResult]] = {}


def register(name: str):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco


# ---------- helpers ----------

def _records(ctx: dict, source: str) -> list[dict] | None:
    recs = ctx.get(source)
    return recs if recs else None


def _apply_where(recs: list[dict], where: dict | None) -> list[dict]:
    if not where:
        return recs
    f, v = where["field"], where["equals"]
    return [r for r in recs if _norm(r.get(f)) == _norm(v)]


def _norm(v: Any) -> Any:
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes", "y", "1"):
            return True
        if s in ("false", "no", "n", "0"):
            return False
        return s
    return v


def _parse_dt(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _index(recs: list[dict], key: str) -> dict[Any, list[dict]]:
    out: dict[Any, list[dict]] = {}
    for r in recs:
        k = _norm(r.get(key))
        if k is None:
            continue
        out.setdefault(k, []).append(r)
    return out


def _not_testable(*sources: str) -> CheckResult:
    return CheckResult("NOT_TESTABLE", f"Required source(s) missing or empty: {', '.join(sources)}")


# ---------- checks ----------

@register("field_present")
def field_present(ctx, p):
    """All records (optionally filtered by `where`) have non-empty values for every field in `fields`."""
    recs = _records(ctx, p["source"])
    if recs is None:
        return _not_testable(p["source"])
    recs = _apply_where(recs, p.get("where"))
    if not recs:
        return CheckResult("PASS", "No records in scope after filter")
    findings = [r for r in recs if any(r.get(f) in (None, "") for f in p["fields"])]
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {len(recs)} records missing {p['fields']}", findings)
    return CheckResult("PASS", f"All {len(recs)} records have {p['fields']}")


@register("field_equals")
def field_equals(ctx, p):
    """Join left to right on keys; left.field must equal right.field for every left record."""
    L, R = _records(ctx, p["left"]["source"]), _records(ctx, p["right"]["source"])
    if L is None or R is None:
        return _not_testable(p["left"]["source"], p["right"]["source"])
    ridx = _index(R, p["join"]["right_key"])
    findings = []
    for r in L:
        k = _norm(r.get(p["join"]["left_key"]))
        matches = ridx.get(k)
        if not matches:
            findings.append({**r, "_reason": "no matching right record"})
            continue
        expected = _norm(matches[0].get(p["right"]["field"]))
        if _norm(r.get(p["left"]["field"])) != expected:
            findings.append({**r, "_expected": matches[0].get(p["right"]["field"])})
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {len(L)} records mismatch", findings)
    return CheckResult("PASS", f"All {len(L)} records match")


@register("values_subset")
def values_subset(ctx, p):
    """Every value of subset.field appears somewhere in superset.field."""
    S, P = _records(ctx, p["subset"]["source"]), _records(ctx, p["superset"]["source"])
    if S is None or P is None:
        return _not_testable(p["subset"]["source"], p["superset"]["source"])
    have = {_norm(r.get(p["superset"]["field"])) for r in P} - {None}
    findings = [r for r in S if _norm(r.get(p["subset"]["field"])) not in have]
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {len(S)} values have no counterpart", findings)
    return CheckResult("PASS", f"All {len(S)} values present in {p['superset']['source']}")


@register("timestamp_before")
def timestamp_before(ctx, p):
    """For each `later` record, a joined `earlier` record must exist with a strictly earlier timestamp."""
    E, Lt = _records(ctx, p["earlier"]["source"]), _records(ctx, p["later"]["source"])
    if E is None or Lt is None:
        return _not_testable(p["earlier"]["source"], p["later"]["source"])
    eidx = _index(E, p["join"]["left_key"])
    findings = []
    for r in Lt:
        k = _norm(r.get(p["join"]["right_key"]))
        later_dt = _parse_dt(r.get(p["later"]["field"]))
        cands = [_parse_dt(e.get(p["earlier"]["field"])) for e in eidx.get(k, [])]
        cands = [c for c in cands if c]
        if later_dt is None:
            findings.append({**r, "_reason": "unparseable later timestamp"})
        elif not cands:
            findings.append({**r, "_reason": "no earlier record"})
        elif min(cands) >= later_dt:
            findings.append({**r, "_reason": "earlier record not before later"})
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {len(Lt)} records lack prior evidence", findings)
    return CheckResult("PASS", f"All {len(Lt)} records have prior evidence")


@register("within_tolerance")
def within_tolerance(ctx, p):
    """Compare latest record to the previous one (ordered by order_by) per metric tolerance."""
    recs = _records(ctx, p["source"])
    if recs is None:
        return _not_testable(p["source"])
    recs = sorted(recs, key=lambda r: _parse_dt(r.get(p["order_by"])) or datetime.min.replace(tzinfo=timezone.utc))
    if len(recs) < 2:
        return CheckResult("NOT_TESTABLE", "Fewer than two records; no baseline to compare")
    prev, cur = recs[-2], recs[-1]
    findings = []
    for m, tol in p["metrics"].items():
        try:
            a, b = float(prev.get(m)), float(cur.get(m))
        except (TypeError, ValueError):
            findings.append({"metric": m, "_reason": "missing or non-numeric"})
            continue
        if "max_drop" in tol and (a - b) > tol["max_drop"]:
            findings.append({"metric": m, "prev": a, "cur": b, "drop": a - b, "limit": tol["max_drop"]})
        if "max_rise" in tol and (b - a) > tol["max_rise"]:
            findings.append({"metric": m, "prev": a, "cur": b, "rise": b - a, "limit": tol["max_rise"]})
    if findings:
        return CheckResult("FAIL", f"{len(findings)} metric(s) out of tolerance", findings)
    return CheckResult("PASS", f"All {len(p['metrics'])} metrics within tolerance")


@register("identity_disjoint")
def identity_disjoint(ctx, p):
    """Join left to right; left.field must never equal right.field."""
    L, R = _records(ctx, p["left"]["source"]), _records(ctx, p["right"]["source"])
    if L is None or R is None:
        return _not_testable(p["left"]["source"], p["right"]["source"])
    ridx = _index(R, p["join"]["right_key"])
    findings, compared = [], 0
    for r in L:
        k = _norm(r.get(p["join"]["left_key"]))
        for m in ridx.get(k, []):
            compared += 1
            if _norm(r.get(p["left"]["field"])) == _norm(m.get(p["right"]["field"])):
                findings.append({**r, "_conflict_with": m})
    if compared == 0:
        return CheckResult("NOT_TESTABLE", "No joinable pairs between sources")
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {compared} pairs share an identity", findings)
    return CheckResult("PASS", f"{compared} pairs, no identity overlap")


@register("date_not_passed")
def date_not_passed(ctx, p):
    """Filtered records must have field date >= today and all require_fields populated."""
    recs = _records(ctx, p["source"])
    if recs is None:
        return _not_testable(p["source"])
    recs = _apply_where(recs, p.get("where"))
    if not recs:
        return CheckResult("PASS", "No records in scope after filter")
    today = datetime.now(timezone.utc)
    findings = []
    for r in recs:
        dt = _parse_dt(r.get(p["field"]))
        missing = [f for f in p.get("require_fields", []) if r.get(f) in (None, "")]
        if dt is None:
            findings.append({**r, "_reason": "missing or unparseable date"})
        elif dt < today:
            findings.append({**r, "_reason": "expired"})
        elif missing:
            findings.append({**r, "_reason": f"missing {missing}"})
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {len(recs)} records expired or incomplete", findings)
    return CheckResult("PASS", f"All {len(recs)} records current and complete")


@register("all_pinned")
def all_pinned(ctx, p):
    """Every record has pinned == True."""
    recs = _records(ctx, p["source"])
    if recs is None:
        return _not_testable(p["source"])
    findings = [r for r in recs if not _norm(r.get("pinned"))]
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {len(recs)} dependencies unpinned", findings)
    return CheckResult("PASS", f"All {len(recs)} dependencies pinned")


@register("elapsed_within")
def elapsed_within(ctx, p):
    """
    mode=most_recent: newest `field` value must be within max_days of now.
    mode=each: for each filtered record, end_field - start_field <= max_days (missing end_field counts as breach).
    """
    recs = _records(ctx, p["source"])
    if recs is None:
        return _not_testable(p["source"])
    now = datetime.now(timezone.utc)
    if p.get("mode", "most_recent") == "most_recent":
        dts = [_parse_dt(r.get(p["field"])) for r in recs]
        dts = [d for d in dts if d]
        if not dts:
            return CheckResult("NOT_TESTABLE", "No parseable dates")
        age = max(0, (now - max(dts)).days)
        if age > p["max_days"]:
            return CheckResult("FAIL", f"Most recent is {age} days old (limit {p['max_days']})", [{"most_recent": max(dts).isoformat()}])
        return CheckResult("PASS", f"Most recent is {age} days old")
    recs = _apply_where(recs, p.get("where"))
    if not recs:
        return CheckResult("PASS", "No records in scope after filter")
    findings = []
    for r in recs:
        s, e = _parse_dt(r.get(p["start_field"])), _parse_dt(r.get(p["end_field"]))
        if s is None:
            findings.append({**r, "_reason": "missing start"})
        elif e is None:
            if (now - s).days > p["max_days"]:
                findings.append({**r, "_reason": "still open past limit"})
        elif (e - s).days > p["max_days"]:
            findings.append({**r, "_reason": f"took {(e - s).days} days"})
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {len(recs)} records exceeded {p['max_days']} days", findings)
    return CheckResult("PASS", f"All {len(recs)} records within {p['max_days']} days")


@register("threshold_met")
def threshold_met(ctx, p):
    """Latest record's `field` >= min (or <= max)."""
    recs = _records(ctx, p["source"])
    if recs is None:
        return _not_testable(p["source"])
    recs = sorted(recs, key=lambda r: _parse_dt(r.get(p["order_by"])) or datetime.min.replace(tzinfo=timezone.utc))
    try:
        v = float(recs[-1].get(p["field"]))
    except (TypeError, ValueError):
        return CheckResult("NOT_TESTABLE", f"{p['field']} missing or non-numeric")
    if "min" in p and v < p["min"]:
        return CheckResult("FAIL", f"{p['field']}={v} below {p['min']}", [recs[-1]])
    if "max" in p and v > p["max"]:
        return CheckResult("FAIL", f"{p['field']}={v} above {p['max']}", [recs[-1]])
    return CheckResult("PASS", f"{p['field']}={v} within bounds")


@register("record_count")
def record_count(ctx, p):
    """Number of records (after optional `where`) must satisfy min/max. Use for presence/absence controls."""
    recs = _records(ctx, p["source"])
    if recs is None:
        return _not_testable(p["source"])
    recs = _apply_where(recs, p.get("where"))
    n = len(recs)
    if "max" in p and n > p["max"]:
        return CheckResult("FAIL", f"{n} records found (max {p['max']})", recs)
    if "min" in p and n < p["min"]:
        return CheckResult("FAIL", f"{n} records found (min {p['min']})")
    return CheckResult("PASS", f"{n} records found")
