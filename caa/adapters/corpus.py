"""
Adapters: overlay_candidates, overlay_coverage, corpus_cases, corpus_elements

Wraps eval_adapters.py (workbench module at repo root), the same way
environment_scan wraps scanner.py. The row builders keep their job (deriving
labels from the element matrix); this adds provenance and judges nothing.

overlay_candidates — one row per requirement-overlay file on disk    (EVL-03)
   fields: path, is_loaded
overlay_coverage   — one row per control in the overlay's library    (EVL-04)
   fields: library, control_id, has_requirement
corpus_cases       — one row per corpus document              (EVL-01, EVL-02)
   fields: control_id, case_id, level, incomplete_set, levels_covered,
           elements_applicable, elements_yes, elements_undecided, label_unsound,
           requirement_sha, requirement_sha_live, requirement_sha_mismatch,
           requirement_binding_broken
corpus_elements    — one row per document x element                  (EVL-06)
   fields: control_id, case_id, element_id, value, lane_b, decided_by,
           undecided, has_citation

Every source is returned separately on purpose: a control counts rows, so mixing
two row kinds in one source means a bare `max:` counts the wrong population.
"""
from __future__ import annotations

from pathlib import Path

from . import AdapterResult, _hash_file, adapter

DEFAULT_CORPUS_ROOT = "eval/corpus"
# The corpus and the workbook belong to the assessor, not to the audited target.
# EVL-* controls test the evaluation apparatus itself, so these resolve against the
# workbench repo regardless of --target, the same way overlay_candidates does.
REPO_ROOT = Path(__file__).resolve().parents[2]

def _rows_module():
    """eval_adapters at the repo root. Imported lazily so a missing module is an
    adapter error rather than an import-time failure of the whole registry."""
    import eval_adapters  # noqa: PLC0415
    return eval_adapters


def _corpus_root(target: Path, cfg: dict) -> Path:
    root = Path(cfg.get("corpus_root", DEFAULT_CORPUS_ROOT))
    return root if root.is_absolute() else REPO_ROOT / root


def _matrix_artefacts(root: Path) -> list:
    return [_hash_file(p) for p in sorted(root.glob("*/elements.yaml"))]


@adapter("overlay_candidates")
def overlay_candidates(target: Path, cfg: dict) -> AdapterResult:
    """cfg: {} — candidates are found relative to playbook.py, not to target."""
    try:
        ea = _rows_module()
    except ImportError as e:
        return AdapterResult("error", message=f"eval_adapters.py not importable: {e}")
    rows = ea.overlay_candidate_rows()
    if not rows:
        return AdapterResult("missing", message="no requirement overlay found on disk")
    artefacts = []
    for r in rows:
        p = Path(r["path"])
        if p.exists():
            artefacts.append(_hash_file(p))
    return AdapterResult("ok", rows, artefacts)


@adapter("overlay_coverage")
def overlay_coverage(target: Path, cfg: dict) -> AdapterResult:
    """cfg: {playbook: 'data/*.xlsx'} — a glob is allowed, since the workbook is git-ignored."""
    try:
        ea = _rows_module()
        import playbook  # noqa: PLC0415
    except ImportError as e:
        return AdapterResult("error", message=f"workbench module not importable: {e}")

    pattern = cfg.get("playbook", "data/*.xlsx")
    p = REPO_ROOT / pattern
    if not p.exists():
        matches = [m for m in sorted(REPO_ROOT.glob(pattern))
                   if not m.name.startswith("playbook_assessed_")]
        if not matches:
            return AdapterResult("missing", message=f"{pattern} not found")
        p = matches[0]

    try:
        controls = playbook.load_controls(str(p))
    except Exception as e:  # noqa: BLE001
        return AdapterResult("error", message=f"could not load {p.name}: {e}")

    rows = ea.overlay_coverage_rows(controls)
    if not rows:
        return AdapterResult("missing", message="the overlay declares no library, or it is absent from the workbook")
    return AdapterResult("ok", rows, [_hash_file(p)])


@adapter("corpus_cases")
def corpus_cases(target: Path, cfg: dict) -> AdapterResult:
    """cfg: {corpus_root: 'eval/corpus'}"""
    try:
        ea = _rows_module()
    except ImportError as e:
        return AdapterResult("error", message=f"eval_adapters.py not importable: {e}")
    root = _corpus_root(target, cfg)
    if not root.is_dir():
        return AdapterResult("missing", message=f"{root} not found")
    try:
        rows = ea.corpus_case_rows(root)
    except Exception as e:  # noqa: BLE001
        return AdapterResult("error", message=str(e))
    # An empty corpus is a real population of zero, not a broken feed, so this
    # returns ok with no records rather than missing.
    return AdapterResult("ok", rows, _matrix_artefacts(root))


@adapter("corpus_elements")
def corpus_elements(target: Path, cfg: dict) -> AdapterResult:
    """cfg: {corpus_root: 'eval/corpus'}"""
    try:
        ea = _rows_module()
    except ImportError as e:
        return AdapterResult("error", message=f"eval_adapters.py not importable: {e}")
    root = _corpus_root(target, cfg)
    if not root.is_dir():
        return AdapterResult("missing", message=f"{root} not found")
    try:
        rows = ea.corpus_element_rows(root)
    except Exception as e:  # noqa: BLE001
        return AdapterResult("error", message=str(e))
    return AdapterResult("ok", rows, _matrix_artefacts(root))
