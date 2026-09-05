"""
NOT AN AI COMPONENT. Zero LLM calls in this file, by design.
All retry limits, cooldowns, and final actions are deterministic; money
decisions must never depend on model discretion. See the graph/ai_*.py files
for where judgment enters the pipeline instead.
"""

from dataclasses import dataclass
from typing import Any, Protocol

MAX_RETRIES = {
    "insufficient_funds": 2,
    "bank_timeout": 3,
    "network_error": 3,
    "3ds_dropoff": 1,
    "card_declined": 1,
    "balance_insufficient": 2,
    "approval_pending": 1,
    "technical_decline": 2,
    "revoked": 0,
}
MANDATE_MAX_RETRIES = 3  # Models real NPCI-style retry constraints within one billing cycle.
CHANNEL_VOICE_THRESHOLD = 100_000
CHANNEL_WHATSAPP_THRESHOLD = 10_000


@dataclass(frozen=True)
class PolicyContext:
    event_type: str
    root_cause: str
    retry_count: int
    customer_history: dict[str, Any]
    customer_tier: str
    subscription_cycle_number: int | None = None


class PolicyStrategy(Protocol):
    """Extension point for event-specific recovery policy."""

    def decide(self, context: PolicyContext) -> tuple[str, str]: ...


class DeterministicPolicy:
    """Default fail-closed policy; strategies never receive model output."""

    def decide(self, context: PolicyContext) -> tuple[str, str]:
        event_type = context.event_type
        root_cause = context.root_cause
        retry_count = context.retry_count
        customer_history = context.customer_history
        subscription_cycle_number = context.subscription_cycle_number
        if customer_history.get("opted_out"):
            return "close", "compliance stop"
        if event_type == "mandate_failure" and root_cause == "revoked":
            return "escalate", "mandate revoked, requires re-consent, cannot auto-retry"
        if event_type == "mandate_failure" and retry_count >= MANDATE_MAX_RETRIES:
            return "escalate", "mandate retry ceiling reached"
        if retry_count >= MAX_RETRIES.get(root_cause, 0):
            return "escalate", "max retries reached"
        if customer_history.get("active_promise"):
            return "await_promise", "waiting on existing promise-to-pay date"
        if root_cause == "3ds_dropoff":
            return "nudge", "remind to complete"
        if root_cause == "card_declined":
            return "switch_method", "offer UPI alternative"
        if event_type == "subscription_failure" and (subscription_cycle_number or 0) >= 3:
            return "nudge", "offer cheaper tier before churn"
        if root_cause in {"insufficient_funds", "balance_insufficient", "bank_timeout", "network_error", "approval_pending", "technical_decline"}:
            return "retry", "retry within deterministic recovery window"
        return "escalate", "unrecoverable"


class PolicyFactory:
    """Central registry for adding a policy without changing orchestration."""

    _strategies: dict[str, PolicyStrategy] = {"default": DeterministicPolicy()}

    @classmethod
    def register(cls, name: str, strategy: PolicyStrategy) -> None:
        if not name.strip():
            raise ValueError("policy name cannot be empty")
        cls._strategies[name] = strategy

    @classmethod
    def get(cls, name: str = "default") -> PolicyStrategy:
        try:
            return cls._strategies[name]
        except KeyError as exc:
            raise ValueError(f"unknown policy strategy: {name}") from exc


def decide_action(event_type: str, root_cause: str, retry_count: int,
                  customer_history: dict[str, Any], customer_tier: str,
                  subscription_cycle_number: int | None = None,
                  strategy: str = "default") -> tuple[str, str]:
    """Choose a bounded recovery step through the selected deterministic strategy."""
    context = PolicyContext(event_type, root_cause, retry_count, customer_history, customer_tier, subscription_cycle_number)
    return PolicyFactory.get(strategy).decide(context)


def select_channel(amount: int, customer_tier: str) -> str:
    """Reserve expensive human-like outreach for cases where it can justify friction."""
    # Voice is reserved for high-value cases, not blasted at every failure: a deliberate cost/friction tradeoff.
    if amount > CHANNEL_VOICE_THRESHOLD or customer_tier == "high_value":
        return "voice"
    if amount > CHANNEL_WHATSAPP_THRESHOLD:
        return "whatsapp"
    return "sms"
