from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


LLM_GENERATION_EVIDENCE_KEY = "llm_generation_evidence"

INTELLIGENCE_REQUIRED_STAGES = {
    "harness_generation",
    "workforce_generation",
    "agent_generation",
    "skill_generation",
    "skill_fusion",
    "evolution_review",
    "evolution_proposal",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def llm_assist_policy(stage: str, *, provider_used: bool = False, error: str | None = None) -> dict[str, Any]:
    stage_name = str(stage or "unknown")
    requires_intelligence = stage_name in INTELLIGENCE_REQUIRED_STAGES
    quality_status = "llm_assisted" if provider_used else (
        "bootstrap_draft" if requires_intelligence else "deterministic"
    )
    return {
        "stage": stage_name,
        "product_model": "Cambrian is a harness layer over LLM intelligence.",
        "requires_intelligence": requires_intelligence,
        "llm_expected": requires_intelligence,
        "provider_used": provider_used,
        "quality_status": quality_status,
        "llm_enrichment_required": bool(requires_intelligence and not provider_used),
        "deterministic_fallback_allowed": True,
        "deterministic_fallback_boundary": "fallback may create bootstrap structure only; it must not claim final intelligent generation",
        "evidence_key": LLM_GENERATION_EVIDENCE_KEY,
        "accepted_modes": ["provider_api", "external_ai_worker", "local_model"],
        "error": error,
    }


def bootstrap_llm_generation_evidence(stage: str) -> dict[str, Any]:
    return {
        "called": False,
        "mode": "deterministic_bootstrap",
        "provider": None,
        "stage": str(stage or "unknown"),
        "quality_status": "bootstrap_draft",
        "summary": "No LLM provider was invoked; Cambrian created only a bootstrap draft that needs LLM enrichment for intelligent generation.",
    }


def call_llm_for_generation(
    provider: Any | None,
    *,
    stage: str,
    system: str,
    user: str,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    if provider is None:
        return {
            "policy": llm_assist_policy(stage, provider_used=False),
            LLM_GENERATION_EVIDENCE_KEY: bootstrap_llm_generation_evidence(stage),
            "llm_notes": None,
        }
    try:
        text = str(provider.complete(system, user, max_tokens=max_tokens) or "").strip()
        provider_name = str(provider.provider_name()) if hasattr(provider, "provider_name") else "unknown"
        return {
            "policy": llm_assist_policy(stage, provider_used=True),
            LLM_GENERATION_EVIDENCE_KEY: {
                "called": True,
                "mode": "provider_api",
                "provider": provider_name,
                "stage": str(stage or "unknown"),
                "generated_at": _now(),
                "summary": "LLM provider was invoked for Cambrian intelligent generation assistance.",
                "response_excerpt": text[:1200],
            },
            "llm_notes": text,
        }
    except Exception as exc:  # pragma: no cover - defensive boundary for provider failures
        return {
            "policy": llm_assist_policy(stage, provider_used=False, error=str(exc)),
            LLM_GENERATION_EVIDENCE_KEY: {
                "called": False,
                "mode": "provider_api_failed",
                "provider": str(provider.provider_name()) if hasattr(provider, "provider_name") else "unknown",
                "stage": str(stage or "unknown"),
                "quality_status": "bootstrap_draft",
                "error": str(exc),
                "summary": "LLM provider call failed; Cambrian kept only a bootstrap draft.",
            },
            "llm_notes": None,
        }
