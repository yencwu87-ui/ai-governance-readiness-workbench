"""
Generic, deterministic control checks.

Every check has the signature:
    check(ctx: dict[str, list[dict]], params: dict) -> CheckResult

`ctx` maps logical source name -> list of normalised records (from adapters).
Checks never read files, call APIs or use models. They only compare records.

Two states that used to be conflated are now kept apart:

  * A source the adapter did not provide at all is NOT_TESTABLE. The feed is
    broken and nothing can be concluded from its silence.
  * A source the adapter provided as an empty list is a population of zero.
    That is a real answer. The check reports examined=0 and returns its
    ordinary verdict.

Whether a population of zero is allowed to pass is a POLICY question, not a
check question. Checks report honest counts; the runner applies the evidence
floor from policy/ai-lifecycle.yaml and downgrades any PASS that stands on
too small a population.

Every CheckResult therefore carries two counts:

    examined  - records in the source population, before any scope filter
    in_scope  - records after the scope filter (equal to examined when there
                is no scope filter)

This is what makes a vacuous pass visible. A control that examined nothing
and found nothing wrong is not the same as a control that examined forty
things and found nothing wrong, and a bundle must be able to tell them apart
months later.

NOTE: a check may still emit PASS with examined=0. That verdict is never
final — the runner's floor turns it into NOT_TESTABLE. Do not call these
functions directly and treat their verdict as a gate outcome.
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
    examined: int = 0                  # source population size
    in_scope: int = 0                  # after scope filter


REGISTRY: dict[str, Callable[[dict, dict], CheckResult]] = {}


def register(name: str):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco


# ---------- helpers ----------

_MISSING = object()


def _source(ctx: dict, name: str) -> list[dict] | None:
    """Records for a source, or None if the adapter did not provide it at all.

    An empty list is returned as [] — a population of zero is a real answer and
    must not be confused with a broken feed.
    """
    recs = ctx.get(name, _MISSING)
    if recs is _MISSING or recs is None:
        return None
    return list(recs)


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


def _not_provided(*sources: str) -> CheckResult:
    """The adapter did not supply these sources. Distinct from supplying them empty."""
    return CheckResult(
        "NOT_TESTABLE",
        f"Source(s) not provided by adapter: {', '.join(sources)}",
        examined=0,
        in_scope=0,
    )


# ---------- checks ----------

@register("field_present")
def field_present(ctx, p):
    """All records (optionally filtered by `where`) have non-empty values for every field in `fields`."""
    recs = _source(ctx, p["source"])
    if recs is None:
        return _not_provided(p["source"])
    scope = _apply_where(recs, p.get("where"))
    n, N = len(scope), len(recs)
    findings = [r for r in scope if any(r.get(f) in (None, "") for f in p["fields"])]
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {n} in-scope records missing {p['fields']}",
                           findings, examined=N, in_scope=n)
    return CheckResult("PASS", f"{n} of {N} records in scope, all have {p['fields']}",
                       examined=N, in_scope=n)


@register("field_equals")
def field_equals(ctx, p):
    """Join left to right on keys; left.field must equal right.field for every left record."""
    L, R = _source(ctx, p["left"]["source"]), _source(ctx, p["right"]["source"])
    missing = [s for s, v in ((p["left"]["source"], L), (p["right"]["source"], R)) if v is None]
    if missing:
        return _not_provided(*missing)
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
        return CheckResult("FAIL", f"{len(findings)} of {len(L)} records mismatch",
                           findings, examined=len(L), in_scope=len(L))
    return CheckResult("PASS", f"All {len(L)} records match",
                       examined=len(L), in_scope=len(L))


@register("values_subset")
def values_subset(ctx, p):
    """Every value of subset.field appears somewhere in superset.field.

    An empty-but-present superset is a real failure state (nothing to match
    against), not an untestable one — every subset value becomes a finding.
    """
    S, P = _source(ctx, p["subset"]["source"]), _source(ctx, p["superset"]["source"])
    missing = [s for s, v in ((p["subset"]["source"], S), (p["superset"]["source"], P)) if v is None]
    if missing:
        return _not_provided(*missing)
    have = {_norm(r.get(p["superset"]["field"])) for r in P} - {None}
    findings = [r for r in S if _norm(r.get(p["subset"]["field"])) not in have]
    if findings:
        return CheckResult("FAIL",
                           f"{len(findings)} of {len(S)} values have no counterpart "
                           f"in {p['superset']['source']} ({len(have)} distinct values)",
                           findings, examined=len(S), in_scope=len(S))
    return CheckResult("PASS", f"All {len(S)} values present in {p['superset']['source']}",
                       examined=len(S), in_scope=len(S))


@register("timestamp_before")
def timestamp_before(ctx, p):
    """For each `later` record, a joined `earlier` record must exist with a strictly earlier timestamp."""
    E, Lt = _source(ctx, p["earlier"]["source"]), _source(ctx, p["later"]["source"])
    missing = [s for s, v in ((p["earlier"]["source"], E), (p["later"]["source"], Lt)) if v is None]
    if missing:
        return _not_provided(*missing)
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
        return CheckResult("FAIL", f"{len(findings)} of {len(Lt)} records lack prior evidence",
                           findings, examined=len(Lt), in_scope=len(Lt))
    return CheckResult("PASS", f"All {len(Lt)} records have prior evidence",
                       examined=len(Lt), in_scope=len(Lt))


@register("within_tolerance")
def within_tolerance(ctx, p):
    """Compare latest record to the previous one (ordered by order_by) per metric tolerance."""
    recs = _source(ctx, p["source"])
    if recs is None:
        return _not_provided(p["source"])
    recs = sorted(recs, key=lambda r: _parse_dt(r.get(p["order_by"])) or datetime.min.replace(tzinfo=timezone.utc))
    N = len(recs)
    if N < 2:
        return CheckResult("NOT_TESTABLE", f"{N} record(s); a regression check needs a baseline and a current run",
                           examined=N, in_scope=N)
    prev, cur = recs[-2], recs[-1]
    findings = []
    missing = []
    for m, tol in p["metrics"].items():
        if prev.get(m) is None or cur.get(m) is None:
            missing.append(m)
            continue
        try:
            a, b = float(prev.get(m)), float(cur.get(m))
        except (TypeError, ValueError):
            missing.append(m)
            continue
        if "max_drop" in tol and (a - b) > tol["max_drop"]:
            findings.append({"metric": m, "prev": a, "cur": b, "drop": a - b, "limit": tol["max_drop"]})
        if "max_rise" in tol and (b - a) > tol["max_rise"]:
            findings.append({"metric": m, "prev": a, "cur": b, "rise": b - a, "limit": tol["max_rise"]})
    if missing and not findings:
        return CheckResult("NOT_TESTABLE",
                           f"No numeric values for {', '.join(missing)} in the two most recent records",
                           examined=N, in_scope=2)
    if findings:
        return CheckResult("FAIL", f"{len(findings)} metric(s) out of tolerance",
                           findings, examined=N, in_scope=2)
    return CheckResult("PASS", f"All {len(p['metrics'])} metrics within tolerance",
                       examined=N, in_scope=2)


@register("identity_disjoint")
def identity_disjoint(ctx, p):
    """Join left to right; left.field must never equal right.field."""
    L, R = _source(ctx, p["left"]["source"]), _source(ctx, p["right"]["source"])
    missing = [s for s, v in ((p["left"]["source"], L), (p["right"]["source"], R)) if v is None]
    if missing:
        return _not_provided(*missing)
    ridx = _index(R, p["join"]["right_key"])
    findings, compared = [], 0
    for r in L:
        k = _norm(r.get(p["join"]["left_key"]))
        for m in ridx.get(k, []):
            compared += 1
            if _norm(r.get(p["left"]["field"])) == _norm(m.get(p["right"]["field"])):
                findings.append({**r, "_conflict_with": m})
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {compared} pairs share an identity",
                           findings, examined=len(L), in_scope=compared)
    return CheckResult("PASS", f"{compared} joinable pairs from {len(L)} records, no identity overlap",
                       examined=len(L), in_scope=compared)


@register("date_not_passed")
def date_not_passed(ctx, p):
    """Filtered records must have field date >= today and all require_fields populated."""
    recs = _source(ctx, p["source"])
    if recs is None:
        return _not_provided(p["source"])
    scope = _apply_where(recs, p.get("where"))
    n, N = len(scope), len(recs)
    today = datetime.now(timezone.utc)
    findings = []
    for r in scope:
        dt = _parse_dt(r.get(p["field"]))
        missing = [f for f in p.get("require_fields", []) if r.get(f) in (None, "")]
        if dt is None:
            findings.append({**r, "_reason": "missing or unparseable date"})
        elif dt < today:
            findings.append({**r, "_reason": "expired"})
        elif missing:
            findings.append({**r, "_reason": f"missing {missing}"})
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {n} in-scope records expired or incomplete",
                           findings, examined=N, in_scope=n)
    return CheckResult("PASS", f"{n} of {N} records in scope, all current and complete",
                       examined=N, in_scope=n)


@register("all_pinned")
def all_pinned(ctx, p):
    """Every record has pinned == True."""
    recs = _source(ctx, p["source"])
    if recs is None:
        return _not_provided(p["source"])
    N = len(recs)
    findings = [r for r in recs if not _norm(r.get("pinned"))]
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {N} dependencies unpinned",
                           findings, examined=N, in_scope=N)
    return CheckResult("PASS", f"All {N} dependencies pinned", examined=N, in_scope=N)


@register("elapsed_within")
def elapsed_within(ctx, p):
    """
    mode=most_recent: newest `field` value must be within max_days of now.
    mode=each: for each filtered record, end_field - start_field <= max_days
    (missing end_field counts as breach).
    """
    recs = _source(ctx, p["source"])
    if recs is None:
        return _not_provided(p["source"])
    N = len(recs)
    now = datetime.now(timezone.utc)
    if p.get("mode", "most_recent") == "most_recent":
        dts = [d for d in (_parse_dt(r.get(p["field"])) for r in recs) if d]
        if not dts:
            return CheckResult("NOT_TESTABLE", f"No parseable dates in {N} record(s)",
                               examined=N, in_scope=0)
        age = max(0, (now - max(dts)).days)
        if age > p["max_days"]:
            return CheckResult("FAIL", f"Most recent of {len(dts)} is {age} days old (limit {p['max_days']})",
                               [{"most_recent": max(dts).isoformat()}], examined=N, in_scope=len(dts))
        return CheckResult("PASS", f"Most recent of {len(dts)} is {age} days old",
                           examined=N, in_scope=len(dts))
    scope = _apply_where(recs, p.get("where"))
    n = len(scope)
    findings = []
    for r in scope:
        s, e = _parse_dt(r.get(p["start_field"])), _parse_dt(r.get(p["end_field"]))
        if s is None:
            findings.append({**r, "_reason": "missing start"})
        elif e is None:
            if (now - s).days > p["max_days"]:
                findings.append({**r, "_reason": "still open past limit"})
        elif (e - s).days > p["max_days"]:
            findings.append({**r, "_reason": f"took {(e - s).days} days"})
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {n} in-scope records exceeded {p['max_days']} days",
                           findings, examined=N, in_scope=n)
    return CheckResult("PASS", f"{n} of {N} records in scope, all within {p['max_days']} days",
                       examined=N, in_scope=n)


@register("threshold_met")
def threshold_met(ctx, p):
    """Latest record's `field` >= min (or <= max)."""
    recs = _source(ctx, p["source"])
    if recs is None:
        return _not_provided(p["source"])
    N = len(recs)
    if not recs:
        return CheckResult("PASS", "No records to threshold", examined=0, in_scope=0)
    recs = sorted(recs, key=lambda r: _parse_dt(r.get(p["order_by"])) or datetime.min.replace(tzinfo=timezone.utc))
    try:
        v = float(recs[-1].get(p["field"]))
    except (TypeError, ValueError):
        return CheckResult("NOT_TESTABLE", f"{p['field']} missing or non-numeric in latest of {N}",
                           examined=N, in_scope=1)
    if "min" in p and v < p["min"]:
        return CheckResult("FAIL", f"{p['field']}={v} below {p['min']}", [recs[-1]], examined=N, in_scope=1)
    if "max" in p and v > p["max"]:
        return CheckResult("FAIL", f"{p['field']}={v} above {p['max']}", [recs[-1]], examined=N, in_scope=1)
    return CheckResult("PASS", f"{p['field']}={v} within bounds", examined=N, in_scope=1)


@register("record_count")
def record_count(ctx, p):
    """Number of records matching `where` must satisfy min/max.

    Here `where` selects FINDINGS, not scope: the population is the whole
    source. `examined` is therefore the pre-filter count, which is what makes
    "0 gaps across 12 artefacts" distinguishable from "0 gaps across nothing".
    """
    recs = _source(ctx, p["source"])
    if recs is None:
        return _not_provided(p["source"])
    N = len(recs)
    hits = _apply_where(recs, p.get("where"))
    n = len(hits)
    if "max" in p and n > p["max"]:
        return CheckResult("FAIL", f"{n} of {N} records matched (max {p['max']})",
                           hits, examined=N, in_scope=N)
    if "min" in p and n < p["min"]:
        return CheckResult("FAIL", f"{n} of {N} records matched (min {p['min']})",
                           examined=N, in_scope=N)
    return CheckResult("PASS", f"{n} of {N} records matched", examined=N, in_scope=N)


@register("recency_each")
def recency_each(ctx, p):
    """Each filtered record's `field` date must be within max_days of now. max_days can be a
    number or the name of a per-record field (`max_days_field`). Missing date = FAIL."""
    recs = _source(ctx, p["source"])
    if recs is None:
        return _not_provided(p["source"])
    scope = _apply_where(recs, p.get("where"))
    n, N = len(scope), len(recs)
    now = datetime.now(timezone.utc)
    findings = []
    for r in scope:
        limit = r.get(p["max_days_field"]) if p.get("max_days_field") else p.get("max_days")
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            findings.append({**r, "_reason": "no cadence limit"})
            continue
        dt = _parse_dt(r.get(p["field"]))
        if dt is None:
            findings.append({**r, "_reason": "never run / no date"})
        elif (now - dt).days > limit:
            findings.append({**r, "_reason": f"{(now - dt).days} days old, limit {limit}"})
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {n} in-scope records overdue or never run",
                           findings, examined=N, in_scope=n)
    return CheckResult("PASS", f"{n} of {N} records in scope, all within cadence",
                       examined=N, in_scope=n)


@register("preceded_within")
def preceded_within(ctx, p):
    """For each `later` record, some `earlier` record must be dated within max_days before it. No join key.

    An empty-but-present `earlier` source means every later record is unpreceded —
    a FAIL, not an untestable state. A deploy with no stress-test run behind it is
    exactly the finding this control exists to make.
    """
    E, Lt = _source(ctx, p["earlier"]["source"]), _source(ctx, p["later"]["source"])
    missing = [s for s, v in ((p["earlier"]["source"], E), (p["later"]["source"], Lt)) if v is None]
    if missing:
        return _not_provided(*missing)
    edts = [d for d in (_parse_dt(e.get(p["earlier"]["field"])) for e in E) if d]
    findings = []
    for r in Lt:
        ld = _parse_dt(r.get(p["later"]["field"]))
        if ld is None:
            findings.append({**r, "_reason": "unparseable date"})
            continue
        if not any(0 <= (ld - ed).days <= p["max_days"] for ed in edts):
            findings.append({**r, "_reason": f"no {p['earlier']['source']} run in the {p['max_days']} days before"})
    if findings:
        return CheckResult("FAIL", f"{len(findings)} of {len(Lt)} records not preceded by a run",
                           findings, examined=len(Lt), in_scope=len(Lt))
    return CheckResult("PASS",
                       f"All {len(Lt)} records preceded by one of {len(edts)} runs within {p['max_days']} days",
                       examined=len(Lt), in_scope=len(Lt))


@register("rate_within")
def rate_within(ctx, p):
    """Share of records (optionally within since_days by date_field) where `field` is truthy must lie in [min, max].

    `min_records` is retained here because the floor is intrinsic to a rate: a
    percentage over three decisions is noise regardless of policy. The runner's
    evidence floor applies on top and may be stricter.
    """
    recs = _source(ctx, p["source"])
    if recs is None:
        return _not_provided(p["source"])
    N = len(recs)
    if p.get("since_days"):
        cutoff = datetime.now(timezone.utc).timestamp() - p["since_days"] * 86400
        recs = [r for r in recs
                if (_parse_dt(r.get(p["date_field"])) or datetime.min.replace(tzinfo=timezone.utc)).timestamp() >= cutoff]
    n = len(recs)
    floor = p.get("min_records", 5)
    if n < floor:
        return CheckResult("NOT_TESTABLE", f"Only {n} of {N} records in window (need {floor})",
                           examined=N, in_scope=n)
    k = sum(1 for r in recs if _norm(r.get(p["field"])) is True)
    rate = k / n
    if rate < p.get("min", 0) or rate > p.get("max", 1):
        return CheckResult("FAIL", f"Rate {rate:.0%} ({k}/{n}) outside [{p.get('min', 0):.0%}, {p.get('max', 1):.0%}]",
                           [{"rate": rate, "n": n}], examined=N, in_scope=n)
    return CheckResult("PASS", f"Rate {rate:.0%} ({k}/{n}) within band", examined=N, in_scope=n)
