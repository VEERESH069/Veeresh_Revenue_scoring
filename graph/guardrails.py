"""Fail-closed controls around all event intake, customer messaging, and batches."""

import re
from typing import Any

from models.schemas import RevenueEvent

AUTO_ACTION_CEILING = 100_000
MAX_NUDGES_PER_BATCH = 100
MAX_BATCH_EXPOSURE = 10_000_000
SUPPRESSION_LIST: set[str] = set()


class GuardrailTripped(RuntimeError):
    """Signal that processing must stop before another customer is contacted."""


def validate_event(event: RevenueEvent, customer_history: dict[str, Any] | None = None) -> None:
    """Reject unsafe inputs before they enter orchestration or call a payment API."""
    if event.amount <= 0 or event.customer_id in SUPPRESSION_LIST:
        raise ValueError("event rejected by input guardrail")
    if event.retry_count >= 3:
        raise ValueError("event retry ceiling exceeded")
    if customer_history and customer_history.get("opted_out"):
        raise ValueError("customer is opted out")


def validate_action_output(policy_decision: str, event: RevenueEvent, nudge_content: str = "") -> None:
    """Prevent model text or policy drift from authorizing unsafe customer-facing action."""
    if event.amount > AUTO_ACTION_CEILING and policy_decision not in {"escalate", "close", "await_promise"}:
        raise ValueError("amount exceeds automatic action ceiling")
    if nudge_content:
        amounts = re.findall(r"(?:₹|Rs\.?\s*)([\d,]+)", nudge_content, flags=re.IGNORECASE)
        if amounts and any(int(value.replace(",", "")) * 100 != event.amount for value in amounts):
            raise ValueError("nudge amount does not match event amount")


def check_batch_guardrails(batch_stats: dict[str, int]) -> None:
    """Trip the circuit breaker when aggregate outreach or exposure becomes abnormal."""
    if batch_stats.get("nudges_sent", 0) > MAX_NUDGES_PER_BATCH or batch_stats.get("total_amount_actioned", 0) > MAX_BATCH_EXPOSURE:
        raise GuardrailTripped("batch guardrail tripped")
