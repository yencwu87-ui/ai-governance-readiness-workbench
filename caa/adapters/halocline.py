"""
Adapters: uc_components, uc_case_coverage, caid_step_oversight, oaid_step_coverage

Wraps halocline_adapters.py (workbench module at repo root), the same way
corpus.py wraps eval_adapters.py. The row builders keep their job (parsing the
component register, summarising the decision log); this adds provenance and
judges nothing.

uc_components      — one row per declared component              (HAL-02, HAL-05)
   fields: use_case, component_id, declared_domain, stale, has_errors,
           override_breach, advisory_flags, advisory_flag_count, + the register columns
uc_case_coverage   — one row per use case                                    (HAL-01)
   fields: use_case, components, components_usable, no_components,
           no_usable_components
caid_step_oversight — one row per (CAID component, evidencing step)          (HAL-03)
   fields: use_case, component_id, step, decisions_n, substantive_n, blind_n,
           rubber_stamp_n, no_decision, blind_absent, unevidenced
oaid_step_coverage  — one row per (OAID component, evidencing step)          (HAL-04)
   fields: use_case, component_id, step, controls, controls_with_real_verdict,
           no_control, uncovered

The checks are generic counters, so a cross-source join cannot happen in a check. The two
joined sources do it in the row builder and emit a precomputed boolean, the same way
corpus_cases emits incomplete_set.

Every source is returned separately on purpose: a control counts rows, so mixing
two row kinds in one source means a bare `max:` counts the wrong population.

These sources describe the workbench's own governed use cases, which live in
governance/ in this repo, so they resolve against REPO_ROOT regardless of
--target — the same choice corpus.py makes for the evaluation apparatus. Pass
governance_root in cfg to point them elsewhere.
"""
from __future__ import annotations

from pathlib import Path

from . import AdapterResult, _hash_file, adapter

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOVERNANCE_ROOT = "."          # halocline_adapters resolves governance/ beneath this
COMPONENT_CSV = "governance/uc_components.csv"
DECISION_LOG = "governance/step_decisions.jsonl"


def _rows_module():
    """halocline_adapters at the repo root. Imported lazily so a missing module is an
    adapter error rather than an import-time failure of the whole registry."""
    import halocline_adapters  # noqa: PLC0415
    return halocline_adapters


def _root(cfg: dict) -> Path:
    root = Path(cfg.get("governance_root", DEFAULT_GOVERNANCE_ROOT))
    return root if root.is_absolute() else REPO_ROOT / root


@adapter("uc_components")
def uc_components(target: Path, cfg: dict) -> AdapterResult:
    """cfg: {governance_root: '.'}

    Malformed rows are returned, not dropped, carrying their defects in `errors`.
    Dropping them would hide them from the evidence floor, letting a register full
    of junk report a small clean population and pass.
    """
    try:
        ha = _rows_module()
    except ImportError as e:
        return AdapterResult("error", message=f"halocline_adapters.py not importable: {e}")

    root = _root(cfg)
    csv_path = root / COMPONENT_CSV
    if not csv_path.exists():
        return AdapterResult("missing", message=f"{COMPONENT_CSV} not found")

    try:
        rows = ha.uc_components(root)
    except Exception as e:  # noqa: BLE001
        return AdapterResult("error", message=str(e))

    # An empty register is a real population of zero, not a broken feed. HAL-01 is
    # what decides whether zero is acceptable, and it decides it against the use
    # cases that exist — that judgement does not belong in the adapter.
    return AdapterResult("ok", rows, [_hash_file(csv_path)])


@adapter("uc_case_coverage")
def uc_case_coverage(target: Path, cfg: dict) -> AdapterResult:
    """cfg: {governance_root: '.'}

    The population is the use-case register, so a use case with nothing classified is a
    row rather than an absence of rows. Absence is what the evidence floor reads as
    NOT_TESTABLE, and "nobody classified anything" must not read as "there are no use
    cases".
    """
    try:
        ha = _rows_module()
    except ImportError as e:
        return AdapterResult("error", message=f"halocline_adapters.py not importable: {e}")

    root = _root(cfg)
    try:
        rows = ha.uc_case_coverage(root)
    except Exception as e:  # noqa: BLE001
        return AdapterResult("error", message=str(e))

    if not rows:
        return AdapterResult("missing", message="no use cases registered")
    csv_path = root / COMPONENT_CSV
    return AdapterResult("ok", rows, [_hash_file(csv_path)] if csv_path.exists() else [])


@adapter("caid_step_oversight")
def caid_step_oversight(target: Path, cfg: dict) -> AdapterResult:
    """cfg: {governance_root: '.'}

    A missing log and an empty log are different states. No file means the lane has never
    been used; an empty file is a population of zero decisions, which reads as no evidence
    of human judgement on every CAID step.
    """
    try:
        ha = _rows_module()
    except ImportError as e:
        return AdapterResult("error", message=f"halocline_adapters.py not importable: {e}")

    root = _root(cfg)
    log = root / DECISION_LOG
    if not log.exists():
        return AdapterResult("missing", message=f"{DECISION_LOG} not found")

    try:
        rows = ha.caid_step_oversight(root, log)
    except Exception as e:  # noqa: BLE001
        return AdapterResult("error", message=str(e))

    artefacts = [_hash_file(log)]
    csv_path = root / COMPONENT_CSV
    if csv_path.exists():
        artefacts.append(_hash_file(csv_path))
    # No CAID components is a real population of zero. Whether that is acceptable is
    # HAL-01's question, not this one's.
    return AdapterResult("ok", rows, artefacts)


@adapter("oaid_step_coverage")
def oaid_step_coverage(target: Path, cfg: dict) -> AdapterResult:
    """cfg: {governance_root: '.'}

    No Lane B results at all is `missing`, not an empty ok: "no tests have ever run" is an
    absent feed, not a finding of no coverage.
    """
    try:
        ha = _rows_module()
        import pipeline  # noqa: PLC0415
    except ImportError as e:
        return AdapterResult("error", message=f"workbench module not importable: {e}")

    try:
        latest = pipeline.latest_lane_b()
    except Exception as e:  # noqa: BLE001
        return AdapterResult("error", message=f"latest_lane_b() failed: {e}")

    if not latest:
        return AdapterResult("missing", message="no Lane B results available")

    root = _root(cfg)
    try:
        rows = ha.oaid_step_coverage(root, latest)
    except Exception as e:  # noqa: BLE001
        return AdapterResult("error", message=str(e))

    # The bundles carry their own hashes; hashing a derived view here would record a
    # digest of something no reviewer can open.
    csv_path = root / COMPONENT_CSV
    return AdapterResult("ok", rows, [_hash_file(csv_path)] if csv_path.exists() else [])
