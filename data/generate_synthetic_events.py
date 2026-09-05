"""Create a balanced, inspectable event set for demos and classifier evaluation."""

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


def generate_events(seed: int = 7) -> list[dict]:
    """Generate 70 labelled failures so recovery behavior can be evaluated offline."""
    random.seed(seed)
    causes = ["insufficient_funds"] * 14 + ["bank_timeout"] * 8 + ["3ds_dropoff"] * 8 + ["card_declined"] * 6 + ["network_error"] * 4
    random.shuffle(causes)
    events = []
    now = datetime.now(timezone.utc)
    for index, cause in enumerate(causes):
        events.append(_event(index, "payment_failure", cause, now, index))
    for index in range(20):
        cause = random.choice(["insufficient_funds", "bank_timeout", "card_declined"])
        events.append(_event(40 + index, "subscription_failure", cause, now, index % 4 + 1))
    for index in range(10):
        cause = random.choice(["balance_insufficient", "approval_pending", "revoked", "technical_decline"])
        events.append(_event(60 + index, "mandate_failure", cause, now, index % 3 + 1))
    return events


def _event(index: int, event_type: str, cause: str, now: datetime, stage: int) -> dict:
    """Build one synthetic event while keeping ground truth outside classifier input."""
    return {"event_id": f"evt_{index:03}", "event_type": event_type, "customer_id": f"cust_{index % 25:03}", "merchant_id": "razorpay_demo", "order_id": f"order_{index:03}", "amount": random.choice([49900, 129900, 249900]), "currency": "INR", "payment_method": random.choice(["card", "upi", "netbanking"]), "failure_reason_raw": cause.replace("_", " "), "failure_code": cause, "timestamp": (now - timedelta(hours=index)).isoformat(), "retry_count": min(stage - 1, 2), "customer_tier": "high_value" if index % 7 == 0 else "regular", "checkout_stage": "checkout" if cause == "3ds_dropoff" else "payment", "subscription_cycle_number": stage if event_type == "subscription_failure" else None, "mandate_attempt_number": stage if event_type == "mandate_failure" else None, "locale": "hi-IN" if index % 3 == 0 else "en-IN", "true_root_cause": cause}


if __name__ == "__main__":
    output = Path(__file__).with_name("synthetic_events.json")
    output.write_text(json.dumps(generate_events(), indent=2), encoding="utf-8")
    print(f"wrote {output}")
