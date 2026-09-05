from datetime import date

import pytest

from graph.guardrails import GuardrailTripped, check_batch_guardrails, validate_action_output, validate_event
from graph.policy import PolicyContext, PolicyFactory, decide_action, select_channel
from eval.classification_eval import evaluate
from models.schemas import EventType, RevenueEvent


def event(event_type=EventType.PAYMENT_FAILURE, amount=5000, retry_count=0):
    return RevenueEvent(event_id="e1", event_type=event_type, customer_id="c1", merchant_id="m1", order_id="o1", amount=amount, payment_method="card", failure_reason_raw="declined", failure_code="x", timestamp="2026-01-01T00:00:00Z", retry_count=retry_count)


@pytest.mark.parametrize("cause, expected", [("3ds_dropoff", "nudge"), ("card_declined", "switch_method"), ("insufficient_funds", "retry"), ("unknown", "escalate")])
def test_payment_policy(cause, expected):
    assert decide_action("payment_failure", cause, 0, {}, "regular")[0] == expected


def test_stop_conditions():
    assert decide_action("payment_failure", "3ds_dropoff", 0, {"opted_out": True}, "regular")[0] == "close"
    assert decide_action("mandate_failure", "revoked", 0, {}, "regular")[0] == "escalate"
    assert decide_action("payment_failure", "network_error", 3, {}, "regular")[0] == "escalate"
    assert decide_action("payment_failure", "network_error", 0, {"active_promise": date.today()}, "regular")[0] == "await_promise"


def test_subscription_dunning_and_mandate_bound():
    assert decide_action("subscription_failure", "insufficient_funds", 0, {}, "regular", 3)[0] == "nudge"
    assert decide_action("mandate_failure", "balance_insufficient", 3, {}, "regular")[0] == "escalate"


def test_channel_selection():
    assert select_channel(1000, "regular") == "sms"
    assert select_channel(11_000, "regular") == "whatsapp"
    assert select_channel(1000, "high_value") == "voice"


def test_guardrails():
    validate_event(event())
    with pytest.raises(ValueError):
        validate_event(event(retry_count=3))
    with pytest.raises(ValueError):
        validate_action_output("retry", event(amount=100_001), "")
    with pytest.raises(ValueError):
        validate_action_output("nudge", event(amount=5000), "Please pay Rs. 99")
    with pytest.raises(GuardrailTripped):
        check_batch_guardrails({"nudges_sent": 101, "total_amount_actioned": 0})


def test_classification_metrics_report_macro_quality():
    result = evaluate([
        {"root_cause": "network_error", "true_root_cause": "network_error", "confidence": 0.9},
        {"root_cause": "card_declined", "true_root_cause": "network_error", "confidence": 0.4},
    ])
    assert result["match_rate"] == 0.5
    assert result["precision"] == pytest.approx(0.5)
    assert result["recall"] == pytest.approx(0.25)
    assert result["f1"] == pytest.approx(1 / 3)


def test_policy_factory_supports_new_strategy_without_graph_changes():
    class ReviewOnlyPolicy:
        def decide(self, context: PolicyContext) -> tuple[str, str]:
            return "escalate", f"manual review for {context.root_cause}"

    PolicyFactory.register("review_only", ReviewOnlyPolicy())
    assert decide_action("payment_failure", "network_error", 0, {}, "regular", strategy="review_only") == (
        "escalate", "manual review for network_error"
    )
