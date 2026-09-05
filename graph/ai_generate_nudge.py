"""
AI COMPONENT: Recovery-message generation.
Why AI here, not rules: the same safe recovery request needs a natural,
locale-aware register without letting a model control amount or action policy.
"""

import os
import time
from pydantic import BaseModel, Field
from observability.langfuse_setup import log_ai_call


class NudgeCopy(BaseModel):
    """Validated customer copy; policy remains the authority on amount and action."""
    message: str = Field(min_length=20, max_length=500)


def generate_nudge(event, locale: str) -> tuple[NudgeCopy, dict]:
    """Generate one measured nudge, or use a safe local copy without credentials."""
    started = time.perf_counter()
    language = "Hinglish" if locale == "hi-IN" else "English"
    fallback = NudgeCopy(message=f"Hi, your {event.currency} {event.amount / 100:.2f} payment needs one more step. Please complete it securely.")
    if not os.getenv("ANTHROPIC_API_KEY"):
        return fallback, _metadata(0, started, "fallback")
    try:
        import anthropic
        import instructor
        client = instructor.from_anthropic(anthropic.Anthropic())
        result = client.messages.create(model="claude-haiku-4-5", max_tokens=160, response_model=NudgeCopy, messages=[{"role": "user", "content": f"Write a concise {language} payment recovery message. It must include exactly Rs. {event.amount / 100:.2f}, contain no other amount, and not promise a result."}])
        usage = getattr(result, "usage", None)
        return result, _metadata(getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0), started, "claude-haiku-4-5")
    except Exception:
        return fallback, _metadata(0, started, "fallback")


def _metadata(tokens, started, model):
    """Expose generation cost as a first-class event measurement."""
    return log_ai_call({"ai_calls": 1, "tokens_used": tokens, "ai_latency_ms": round((time.perf_counter() - started) * 1000, 2), "ai_model": model, "ai_component": "ai_nudge_generation"})
