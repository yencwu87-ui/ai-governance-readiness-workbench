"""Minimal GitHub observation plugin for Lane A.

The plugin collects read-only repository branch-protection state and emits canonical Observations.
No governance interpretation is performed here.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

from governance.observation import Observation


class GitHubPlugin:
    id = "github"
    version = "0.1.0"
    target_types = ["github_repo"]
    capabilities = ["observe.branch_protection"]
    side_effects = ["read_only"]

    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")

    def _get(self, endpoint: str) -> dict:
        url = "https://api.github.com" + endpoint
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ai-governance-engine/0.9"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(url, headers=headers, method="GET")
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"GitHub API {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"GitHub API unavailable: {exc.reason}") from exc

    def capabilities_for_element(self, element_id: str, control_id: str = "") -> list[str]:
        # Provider capabilities are advisory execution hints; the contract remains authoritative.
        return list(self.capabilities)

    def collect(self, target: dict) -> list[Observation]:
        repo = str(target.get("id") or "").strip()
        branch = str(target.get("branch") or "main").strip()
        if "/" not in repo:
            raise ValueError("GitHub target id must be ORG/REPO")
        if not branch:
            raise ValueError("GitHub branch must be non-empty")
        endpoint = f"/repos/{repo}/branches/{branch}/protection"
        data = self._get(endpoint)
        observed_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        attrs = {
            "required_pull_request_reviews": bool(data.get("required_pull_request_reviews")),
            "required_approving_review_count": ((data.get("required_pull_request_reviews") or {}).get("required_approving_review_count")),
            "dismiss_stale_reviews": ((data.get("required_pull_request_reviews") or {}).get("dismiss_stale_reviews")),
            "require_code_owner_reviews": ((data.get("required_pull_request_reviews") or {}).get("require_code_owner_reviews")),
            "enforce_admins": bool(data.get("enforce_admins", {}).get("enabled")) if isinstance(data.get("enforce_admins"), dict) else data.get("enforce_admins"),
            "required_status_checks": bool(data.get("required_status_checks")),
        }
        provenance = {
            "method": "github_api",
            "endpoint": f"GET {endpoint}",
            "locator": f"github_api:GET {endpoint}",
            "branch": branch,
        }
        return [Observation.create(
            observation_id=f"github-{uuid.uuid4().hex[:12]}",
            provider=self.id,
            target={"type": "github_repo", "id": repo, "branch": branch},
            resource="branch_protection",
            observed_at=observed_at,
            attributes=attrs,
            provenance=provenance,
        )]
