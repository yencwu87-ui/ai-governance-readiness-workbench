"""Hotspot 1 — hallucination & factual fabrication. Engine: garak (NVIDIA), probes 'snowball' and 'misleading'.

Requires:  pip install garak      and a target garak can reach (Ollama via the 'ollama' generator, or an
OpenAI-compatible endpoint via 'openai' generator with OPENAI_API_BASE / OPENAI_API_KEY).
This runner shells out, then reads garak's JSONL report. garak's report format has changed across
versions; the parser below reads the 'eval' entries (probe, detector, passed, total) and falls back to
counting 'attempt' entries with a 'status' field. Verify against your installed version once.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import HotspotResult, hotspot, now, rate

PROBES = ["snowball", "misleading"]


def _garak_target(target) -> tuple[str, str]:
    if target.name.startswith("ollama:"):
        return "ollama", target.model
    if target.name.startswith("http"):
        return "openai", target.model
    if target.name == "workbench":
        return "ollama", target.model.split("/", 1)[1] if "/" in target.model else target.model
    raise ValueError("garak cannot address this target")


def parse_garak_report(path: Path) -> list[dict]:
    detail = []
    for line in path.read_text().splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("entry_type") == "eval":
            total, passed = int(e.get("total", 0)), int(e.get("passed", 0))
            detail.append({"probe": e.get("probe"), "detector": e.get("detector"), "cases": total, "passed": passed,
                           "failed": total - passed, "fail": total - passed > 0})
    if not detail:  # older format: per-attempt status (2 = complete); score in 'outputs' not exposed — count attempts only
        n = sum(1 for l in path.read_text().splitlines() if '"entry_type": "attempt"' in l)
        detail.append({"probe": "all", "detector": "?", "cases": n, "passed": None, "failed": None, "fail": None,
                       "note": "eval entries not found; inspect report manually"})
    return detail


@hotspot(1, "Generative AI hallucination & factual fabrication")
def run(target, cfg: dict) -> HotspotResult:
    if not shutil.which("garak") and not shutil.which("python"):
        return HotspotResult(1, "Hallucination", target.name, now(), "garak", 0, 0, "Not run", "High", note="garak not installed")
    gen, model = _garak_target(target)
    out_dir = Path(cfg.get("results_dir", "stress/results")) / "garak"
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / f"h01_{now()[:10]}"
    cmd = ["python", "-m", "garak", "--model_type", gen, "--model_name", model,
           "--probes", ",".join(PROBES), "--report_prefix", str(prefix)]
    if cfg.get("generations"):
        cmd += ["--generations", str(cfg["generations"])]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=cfg.get("timeout", 3600))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        return HotspotResult(1, "Hallucination", target.name, now(), "garak", 0, 0, "Not run", "High",
                             note=f"garak failed: {getattr(e, 'stderr', '') or e}"[:300])
    reports = sorted(out_dir.glob(f"{prefix.name}*.report.jsonl"))
    if not reports:
        return HotspotResult(1, "Hallucination", target.name, now(), "garak", 0, 0, "Not run", "High", note="no report produced")
    detail = parse_garak_report(reports[-1])
    cases = sum(d["cases"] or 0 for d in detail)
    failed = sum(d["failed"] or 0 for d in detail)
    result, risk = rate(failed, cases)
    return HotspotResult(1, "Generative AI hallucination & factual fabrication", target.name, now(), "garak",
                         cases, failed, result, risk, detail, raw_report=str(reports[-1]), note=f"probes: {', '.join(PROBES)}")
