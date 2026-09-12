"""Targets: anything that answers a prompt. The runner and hotspots never care which.

    target.ask(system, user) -> str            raw text
    target.assess(control, evidence) -> dict   only the workbench target has this; hotspots that need
                                               structured ratings check hasattr(target, "assess")

Choose with --target: workbench | ollama:<model> | http:<url>
"""
from __future__ import annotations

import os
from types import SimpleNamespace


class Workbench:
    """The readiness-assessor via pipeline.propose(). Structured output (sufficiency, maturity, gaps…)."""
    name = "workbench"

    def __init__(self):
        from pipeline import propose
        from assessor import model_name
        self._propose, self.model = propose, model_name()

    def assess(self, control: dict, evidence: str) -> dict:
        return self._propose(SimpleNamespace(**control), {"text": evidence, "file_name": "", "auto": False, "sources": []})

    def ask(self, system: str, user: str) -> str:
        from assessor import _ollama, _anthropic, PROVIDER
        return _ollama(system, user) if PROVIDER == "ollama" else _anthropic(system, user, None)


class Ollama:
    """Any local Ollama model, raw chat. For scanning models other than the assessor."""
    def __init__(self, model: str, url: str | None = None):
        self.name, self.model, self.url = f"ollama:{model}", model, url or os.environ.get("OLLAMA_URL", "http://localhost:11434")

    def ask(self, system: str, user: str) -> str:
        import requests
        r = requests.post(f"{self.url}/api/chat", timeout=300, json={
            "model": self.model, "stream": False, "options": {"temperature": 0, "seed": 7},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["message"]["content"]


class Http:
    """Generic OpenAI-style chat endpoint. Set TARGET_API_KEY for auth."""
    def __init__(self, url: str, model: str = "default"):
        self.name, self.url, self.model = f"http:{url}", url, model

    def ask(self, system: str, user: str) -> str:
        import requests
        headers = {"Content-Type": "application/json"}
        if os.environ.get("TARGET_API_KEY"):
            headers["Authorization"] = f"Bearer {os.environ['TARGET_API_KEY']}"
        r = requests.post(self.url, timeout=300, headers=headers, json={
            "model": self.model, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        j = r.json()
        return j["choices"][0]["message"]["content"] if "choices" in j else j.get("message", {}).get("content", str(j))


def make(spec: str):
    if spec == "workbench":
        return Workbench()
    if spec.startswith("ollama:"):
        return Ollama(spec.split(":", 1)[1])
    if spec.startswith("http:") or spec.startswith("https:"):
        return Http(spec)
    raise ValueError(f"unknown target {spec!r}")
