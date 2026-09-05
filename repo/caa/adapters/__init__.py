"""
Evidence source adapters.

Every adapter has the signature:
    adapter(target: Path, cfg: dict) -> AdapterResult

Adapters read raw artefacts (files, git, exports) and return normalised records.
They do not judge anything. They also return a hash of every artefact they read
so the evidence bundle can prove what was examined.

To add a source: write a function, decorate with @adapter("name"),
reference "name" in audit.yaml.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml


@dataclass
class Artefact:
    ref: str
    sha256: str
    bytes: int = 0


@dataclass
class AdapterResult:
    status: str                      # ok | missing | error
    records: list[dict] = field(default_factory=list)
    artefacts: list[Artefact] = field(default_factory=list)
    message: str = ""


REGISTRY: dict[str, Callable[[Path, dict], AdapterResult]] = {}


def adapter(name: str):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco


def _hash_file(p: Path) -> Artefact:
    data = p.read_bytes()
    return Artefact(str(p), hashlib.sha256(data).hexdigest(), len(data))


def _hash_text(ref: str, text: str) -> Artefact:
    b = text.encode()
    return Artefact(ref, hashlib.sha256(b).hexdigest(), len(b))


def _resolve(target: Path, rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else target / p


def _read_table(p: Path) -> list[dict]:
    if p.suffix.lower() == ".csv":
        with p.open(newline="", encoding="utf-8-sig") as f:   # utf-8-sig strips an Excel BOM
            return [{(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()} for row in csv.DictReader(f)]
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else data.get("records", [data])
    if p.suffix.lower() in (".yml", ".yaml"):
        data = yaml.safe_load(p.read_text())
        return data if isinstance(data, list) else [data]
    raise ValueError(f"Unsupported table format: {p}")


# ---------- generic table adapters (CSV / JSON / YAML exports) ----------

def _table_adapter(target: Path, cfg: dict) -> AdapterResult:
    """cfg: {path: str}. Reads a CSV/JSON/YAML export as-is."""
    p = _resolve(target, cfg["path"])
    if not p.exists():
        return AdapterResult("missing", message=f"{p} not found")
    try:
        return AdapterResult("ok", _read_table(p), [_hash_file(p)])
    except Exception as e:  # noqa: BLE001
        return AdapterResult("error", message=str(e))


for _name in ("ticket_export", "model_registry", "eval_results", "rollback_log", "exception_register"):
    REGISTRY[_name] = _table_adapter


# ---------- git ----------

@adapter("git_log")
def git_log(target: Path, cfg: dict) -> AdapterResult:
    """
    cfg: {max_commits: int, ticket_pattern: regex, governed_paths: [path prefixes relative to target]}
    Records: commit, author, email, date, message, ticket_ref, paths, touches_governed_paths
    Works when target is a subfolder of the git repo: paths are made relative to target and
    commits touching nothing under target still appear (with empty paths).
    """
    def git(*args):
        return subprocess.run(["git", "-C", str(target), *args], capture_output=True, text=True, check=True).stdout
    try:
        git("rev-parse", "--is-inside-work-tree")
        prefix = git("rev-parse", "--show-prefix").strip()   # "" at root, "repo/" in a subfolder
    except (subprocess.CalledProcessError, FileNotFoundError):
        return AdapterResult("missing", message="not inside a git repository")
    n = cfg.get("max_commits", 200)
    pat = re.compile(cfg.get("ticket_pattern", r"\b([A-Z]{2,10}-\d+)\b"))
    governed = cfg.get("governed_paths", [])
    fmt = "%H%x1f%an%x1f%ae%x1f%aI%x1f%s"
    try:
        out = git("log", f"-n{n}", f"--format={fmt}", "--name-only")
    except subprocess.CalledProcessError as e:
        return AdapterResult("error", message=e.stderr)
    records, cur = [], None
    for line in out.splitlines():
        if "\x1f" in line:
            h, an, ae, d, msg = line.split("\x1f", 4)
            m = pat.search(msg)
            cur = {"commit": h, "author": an, "email": ae, "date": d, "message": msg,
                   "ticket_ref": m.group(1) if m else None, "paths": [], "touches_governed_paths": False}
            records.append(cur)
        elif line.strip() and cur is not None:
            rel = line.strip()
            if prefix and rel.startswith(prefix):
                rel = rel[len(prefix):]
            elif prefix:
                continue  # file outside target subfolder
            cur["paths"].append(rel)
            if any(rel.startswith(g) for g in governed):
                cur["touches_governed_paths"] = True
    return AdapterResult("ok", records, [_hash_text(f"git log -n{n} @ {target}", out)])


# ---------- lock / requirements files ----------

@adapter("lock_file")
def lock_file(target: Path, cfg: dict) -> AdapterResult:
    """
    cfg: {path: str}. Supports requirements.txt style. Records: package, version, pinned, raw
    """
    p = _resolve(target, cfg.get("path", "requirements.txt"))
    if not p.exists():
        return AdapterResult("missing", message=f"{p} not found")
    records = []
    for raw in p.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)\s*(==|>=|<=|~=|>|<|!=)?\s*([^\s;]+)?", line)
        if not m:
            continue
        name, op, ver = m.group(1), m.group(2), m.group(3)
        records.append({"package": name, "version": ver, "pinned": op == "==", "raw": raw})
    return AdapterResult("ok", records, [_hash_file(p)])


# ---------- deploy manifest ----------

@adapter("deploy_manifest")
def deploy_manifest(target: Path, cfg: dict) -> AdapterResult:
    """
    cfg: {path: str, records_key: str|None, fields: {record_field: dotted.path}}
    Reads a YAML/JSON manifest. If records_key names a list, one record per item;
    otherwise the whole document is one record. `fields` maps output field names to
    dotted paths inside each item, so the control YAML can stay generic.
    """
    p = _resolve(target, cfg["path"])
    if not p.exists():
        return AdapterResult("missing", message=f"{p} not found")
    doc = yaml.safe_load(p.read_text())
    items = doc.get(cfg["records_key"], []) if cfg.get("records_key") else [doc]
    mapping = cfg.get("fields", {})

    def dig(obj, dotted):
        for part in dotted.split("."):
            if not isinstance(obj, dict):
                return None
            obj = obj.get(part)
        return obj

    records = []
    for it in items:
        rec = {k: dig(it, v) for k, v in mapping.items()} if mapping else dict(it)
        rec["_manifest"] = str(p)
        records.append(rec)
    return AdapterResult("ok", records, [_hash_file(p)])


# ---------- workbench adapters (registered on import) ----------
from . import environment_scan, lifecycle  # noqa: E402,F401
