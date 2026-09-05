"""Hotspot 3 — autonomous agent behaviour & unintended actions. Engine: promptfoo red-team.

Requires:  npx promptfoo   (Node) and a promptfoo config at stress/corpora/h03_promptfoo.yaml describing the
target and the plugins to run (e.g. 'excessive-agency', 'overreliance', 'hijacking', 'rbac').
This runner executes `promptfoo eval -c <config> -o <json>` and reads the JSON output's results.
promptfoo's output schema: results.results[] each with 'success' (bool) and 'vars'/'prompt'. Verify once
against your installed version.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import HotspotResult, hotspot, now, rate

CONFIG = Path(__file__).parent.parent / "corpora" / "h03_promptfoo.yaml"


def parse_promptfoo(path: Path) -> list[dict]:
    j = json.loads(path.read_text())
    rows = j.get("results", {}).get("results", []) if isinstance(j.get("results"), dict) else j.get("results", [])
    out = []
    for r in rows:
        ok = bool(r.get("success"))
        out.append({"id": r.get("id") or r.get("testCase", {}).get("description") or "case", "plugin": (r.get("metadata") or {}).get("pluginId"),
                    "success": ok, "fail": not ok, "reason": (r.get("gradingResult") or {}).get("reason", "")[:160]})
    return out


@hotspot(3, "Autonomous agent behaviour & unintended actions")
def run(target, cfg: dict) -> HotspotResult:
    if not shutil.which("npx"):
        return HotspotResult(3, "Agent behaviour", target.name, now(), "promptfoo", 0, 0, "Not run", "High", note="npx (Node) not installed")
    if not CONFIG.exists():
        return HotspotResult(3, "Agent behaviour", target.name, now(), "promptfoo", 0, 0, "Not run", "High",
                             note=f"missing {CONFIG.name}; see promptfoo red-team docs")
    out = Path(cfg.get("results_dir", "stress/results")) / f"h03_{now()[:10]}.promptfoo.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["npx", "promptfoo", "eval", "-c", str(CONFIG), "-o", str(out), "--no-cache"],
                       check=False, capture_output=True, text=True, timeout=cfg.get("timeout", 3600))
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return HotspotResult(3, "Agent behaviour", target.name, now(), "promptfoo", 0, 0, "Not run", "High", note=str(e)[:300])
    if not out.exists():
        return HotspotResult(3, "Agent behaviour", target.name, now(), "promptfoo", 0, 0, "Not run", "High", note="no output produced")
    detail = parse_promptfoo(out)
    failed = sum(1 for d in detail if d["fail"])
    result, risk = rate(failed, len(detail))
    return HotspotResult(3, "Autonomous agent behaviour & unintended actions", target.name, now(), "promptfoo",
                         len(detail), failed, result, risk, detail, raw_report=str(out))
