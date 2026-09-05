"""
AI COMPONENT: Root-cause classification.
Why AI here, not rules: gateway failure_reason_raw is free text and varies by
provider, so semantic understanding is useful when a new error string appears.
"""

import os
import time
from pydantic import BaseModel, Field
from observability.langfuse_setup import log_ai_call


class RootCauseJudgment(BaseModel):
    """Schema that must validate before a cause reaches deterministic policy."""
    root_cause: str
    confidence: float = Field(ge=0, le=1)
    reasoning: str


def classify_root_cause(event) -> tuple[RootCauseJudgment, dict]:
    """Ask Claude for semantic classification and return observable call metadata."""
    started = time.perf_counter()
    fallback = RootCauseJudgment(root_cause=event.failure_code or "unknown", confidence=0.4, reasoning="Provider code fallback")
    if not os.getenv("ANTHROPIC_API_KEY"):
        return fallback, _metadata(0, started, "fallback")
    try:
        import anthropic
        import instructor
        client = instructor.from_anthropic(anthropic.Anthropic())
        result = client.messages.create(model="claude-haiku-4-5", max_tokens=180, response_model=RootCauseJudgment, messages=[{"role": "user", "content": f"Classify this payment failure. Raw reason: {event.failure_reason_raw}. Code: {event.failure_code}. Return only the requested schema."}])
        usage = getattr(result, "usage", None)
        tokens = getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)
        return result, _metadata(tokens, started, "claude-haiku-4-5")
    except Exception:
        return fallback, _metadata(0, started, "fallback")


def _metadata(tokens: int, started: float, model: str) -> dict:
    """Keep AI cost and latency visible even when a provider call fails."""
    return log_ai_call({"ai_calls": 1, "tokens_used": tokens, "ai_latency_ms": round((time.perf_counter() - started) * 1000, 2), "ai_model": model, "ai_component": "ai_classification"})
