"""
AI COMPONENT: Reply-intent classification.
Why AI here, not rules: customers express payment intent in varied natural
language, including short Hinglish replies that keyword rules miss.
"""

import os
import time
from pydantic import BaseModel, Field
from observability.langfuse_setup import log_ai_call


class ReplyIntent(BaseModel):
    """Constrained intent used to schedule follow-up, never to bypass policy."""
    intent: str = Field(pattern="^(paid|will_pay|need_help|stop|unknown)$")
    confidence: float = Field(ge=0, le=1)


def classify_reply_intent(reply: str) -> tuple[ReplyIntent, dict]:
    """Classify a customer reply for follow-up routing with measured model usage."""
    started = time.perf_counter()
    fallback = ReplyIntent(intent="stop" if reply.lower().strip() in {"stop", "unsubscribe"} else "unknown", confidence=0.4)
    if not os.getenv("ANTHROPIC_API_KEY"):
        return fallback, _metadata(0, started, "fallback")
    try:
        import anthropic
        import instructor
        client = instructor.from_anthropic(anthropic.Anthropic())
        result = client.messages.create(model="claude-haiku-4-5", max_tokens=80, response_model=ReplyIntent, messages=[{"role": "user", "content": f"Classify this recovery reply: {reply}"}])
        usage = getattr(result, "usage", None)
        return result, _metadata(getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0), started, "claude-haiku-4-5")
    except Exception:
        return fallback, _metadata(0, started, "fallback")


def _metadata(tokens, started, model):
    """Expose reply classification cost and timing for operational review."""
    return log_ai_call({"ai_calls": 1, "tokens_used": tokens, "ai_latency_ms": round((time.perf_counter() - started) * 1000, 2), "ai_model": model, "ai_component": "ai_reply_intent"})
