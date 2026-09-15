from __future__ import annotations

from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class TaskSignals:
    role: str
    control_id: str = ""
    evidence_chars: int = 0
    element_count: int = 0
    ambiguity: float = 0.0
    prior_failures: int = 0
    reviewer_disagreement: bool = False
    high_risk: bool = False
    regulatory_freshness: bool = False


@dataclass(frozen=True)
class InferencePlan:
    tier: str
    model: str
    max_attempts: int = 1
    num_ctx: int = 16384
    num_predict: int = 1200
    parallel_read_only: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _role_env(role: str) -> str | None:
    direct = os.environ.get(f"WB_MODEL_{role.upper()}")
    if direct:
        return direct
    if role.startswith("challenge_") or role == "challenge":
        return os.environ.get("WB_MODEL_CHALLENGE")
    return None


def _model_for_tier(tier: str, role: str) -> str:
    # Interactive challenger runs get an explicit fast fallback after a transport/validation
    # failure. A locally hosted 14B model can otherwise consume the full HTTP timeout twice
    # while the UI has no governed result to show. The fallback changes only the challenger
    # transport; it never changes a governance verdict.
    if role.startswith("challenge") and os.environ.get("WB_INFERENCE_FALLBACK") == "1":
        return (os.environ.get("WB_MODEL_CHALLENGE_FALLBACK")
                or os.environ.get("WB_MODEL_FAST")
                or "llama3.1:8b")
    role_model = _role_env(role)
    if tier == "critical":
        return os.environ.get("WB_MODEL_CRITICAL") or os.environ.get("WB_MODEL_STRONG") or role_model or os.environ.get("OLLAMA_MODEL") or "llama3.1:8b"
    if tier == "strong":
        return os.environ.get("WB_MODEL_STRONG") or role_model or os.environ.get("OLLAMA_MODEL") or "llama3.1:8b"
    return os.environ.get("WB_MODEL_FAST") or role_model or os.environ.get("OLLAMA_MODEL") or "llama3.1:8b"


def build_plan(signals: TaskSignals) -> InferencePlan:
    reasons: list[str] = []
    score = 0
    if signals.evidence_chars > 24000:
        score += 1; reasons.append("large_evidence")
    if signals.element_count > 8:
        score += 1; reasons.append("many_elements")
    if signals.ambiguity >= 0.5:
        score += 1; reasons.append("ambiguous_task")
    if signals.prior_failures:
        score += min(2, signals.prior_failures); reasons.append("prior_validation_failure")
    if signals.reviewer_disagreement:
        score += 2; reasons.append("reviewer_assessor_disagreement")
    if signals.high_risk:
        score += 2; reasons.append("high_risk_control")
    if signals.regulatory_freshness:
        score += 1; reasons.append("regulatory_freshness")

    if score >= 3:
        tier = "critical"
    elif score >= 1:
        tier = "strong"
    else:
        tier = "routine"

    env_predict = {"routine": "1200", "strong": "1800", "critical": "2400"}[tier]
    env_ctx = {"routine": "16384", "strong": "24576", "critical": "32768"}[tier]
    return InferencePlan(
        tier=tier,
        model=_model_for_tier(tier, signals.role),
        max_attempts=2 if signals.role.startswith("challenge") else (1 if tier == "routine" else 2),
        num_ctx=int(os.environ.get(f"WB_NUM_CTX_{tier.upper()}", env_ctx)),
        num_predict=int(os.environ.get(f"WB_NUM_PREDICT_{tier.upper()}", env_predict)),
        parallel_read_only=signals.role in {"assess", "challenge", "elements"},
        reasons=tuple(reasons),
    )
