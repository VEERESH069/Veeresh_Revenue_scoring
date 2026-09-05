"""Validated contracts shared by the recovery graph and integrations."""

from datetime import datetime, date
from enum import Enum
from typing import Any, Optional, TypedDict

from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    PAYMENT_FAILURE = "payment_failure"
    SUBSCRIPTION_FAILURE = "subscription_failure"
    MANDATE_FAILURE = "mandate_failure"


class RevenueEvent(BaseModel):
    """Describe one recoverable revenue event in a single generalized shape."""

    event_id: str
    event_type: EventType
    customer_id: str
    merchant_id: str
    order_id: str
    amount: int = Field(gt=0, description="Amount in paise")
    currency: str = "INR"
    payment_method: str
    failure_reason_raw: str
    failure_code: str
    timestamp: datetime
    retry_count: int = Field(default=0, ge=0)
    customer_tier: str = "regular"
    checkout_stage: str = "payment"
    subscription_cycle_number: Optional[int] = Field(default=None, ge=1, le=4)
    mandate_attempt_number: Optional[int] = Field(default=None, ge=1)
    locale: str = "en-IN"
    true_root_cause: Optional[str] = None

    @field_validator("customer_tier")
    @classmethod
    def valid_tier(cls, value: str) -> str:
        if value not in {"regular", "high_value"}:
            raise ValueError("customer_tier must be regular or high_value")
        return value


class Classification(BaseModel):
    """Structured LLM judgment kept separate from deterministic policy logic."""

    root_cause: str
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    tokens_used: int = Field(default=0, ge=0)


class ActionResult(BaseModel):
    """Represent an integration attempt without hiding an external failure."""

    success: bool
    status: str
    provider_id: Optional[str] = None
    error: Optional[str] = None


class AuditRecord(BaseModel):
    """Immutable evidence of a decision, action, and its cost."""

    event_id: str
    event_type: EventType
    root_cause: str
    confidence: float
    policy_decision: str
    policy_reason: str
    action_taken: str
    action_result: str
    outcome: str
    timestamp: datetime
    tokens_used: int = 0


class PromiseRecord(BaseModel):
    """Track a customer promise so later cycles do not immediately re-nudge."""

    customer_id: str
    event_id: str
    promise_date: date
    follow_up_date: date
    kept: Optional[bool] = None
    created_at: datetime


class RecoveryState(TypedDict, total=False):
    event: RevenueEvent
    customer_history: dict[str, Any]
    root_cause: str
    confidence: float
    policy_decision: str
    policy_reason: str
    action_result: ActionResult
    nudge_content: str
    promise_date: Optional[date]
    channel: str
    tokens_used: int
    outcome: str
