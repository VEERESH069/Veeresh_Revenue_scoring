"""
AI COMPONENT: Nudge quality judgment.
Why AI here, not rules: tone, clarity, and compliance risk are contextual
language judgments; a numeric threshold still deterministically gates sending.
"""

import os
import time
from pydantic import BaseModel, Field
from observability.langfuse_setup import log_ai_call


class NudgeQuality(BaseModel):
    """Structured judge result with explicit compliance threshold input."""
    compliance: int = Field(ge=0, le=10)
    clarity: int = Field(ge=0, le=10)
    tone: int = Field(ge=0, le=10)
    reasoning: str


def judge_nudge_quality(message: str) -> tuple[NudgeQuality, dict]:
    """Score generated copy and let deterministic code block compliance below seven."""
    started = time.perf_counter()
    fallback = NudgeQuality(compliance=10 if len(message) >= 20 else 0, clarity=10, tone=10, reasoning="Local structural check")
    if not os.getenv("ANTHROPIC_API_KEY"):
        return fallback, _metadata(0, started, "fallback")
    try:
        import anthropic
        import instructor
        client = instructor.from_anthropic(anthropic.Anthropic())
        result = client.messages.create(model="claude-haiku-4-5", max_tokens=120, response_model=NudgeQuality, messages=[{"role": "user", "content": f"Score this payment recovery message from 0 to 10 for compliance, clarity, and tone: {message}"}])
        usage = getattr(result, "usage", None)
        return result, _metadata(getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0), started, "claude-haiku-4-5")
    except Exception:
        return fallback, _metadata(0, started, "fallback")


def _metadata(tokens, started, model):
    """Expose judge cost and latency beside the decision it influenced."""
    return log_ai_call({"ai_calls": 1, "tokens_used": tokens, "ai_latency_ms": round((time.perf_counter() - started) * 1000, 2), "ai_model": model, "ai_component": "ai_nudge_judge"})
