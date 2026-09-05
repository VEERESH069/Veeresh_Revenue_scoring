"""Small Razorpay test-mode boundary with an explicit offline demo simulator."""

import os

from models.schemas import ActionResult, RevenueEvent


def retry_payment(event: RevenueEvent) -> ActionResult:
    """Create a provider-supported recovery link; never claim payment success prematurely."""
    if os.getenv("RAZORPAY_DEMO_MODE", "true").lower() == "true":
        if event.failure_code in {"insufficient_funds", "bank_timeout", "network_error", "balance_insufficient", "technical_decline"}:
            return ActionResult(success=True, status="recovered", provider_id=f"demo_pay_{event.event_id}")
        return ActionResult(success=False, status="escalate", error="demo provider declined recovery")
    try:
        import razorpay
        client = razorpay.Client(auth=(os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"]))
        response = client.payment_link.create({"amount": event.amount, "currency": event.currency, "description": "Revenue recovery", "reference_id": event.event_id})
        provider_id = response.get("id")
        if not provider_id or response.get("status") not in {None, "created", "issued"}:
            return ActionResult(success=False, status="escalate", error="provider returned an invalid recovery link")
        return ActionResult(success=True, status="recovery_link_created", provider_id=provider_id)
    except Exception as exc:
        return ActionResult(success=False, status="escalate", error=str(exc))


def send_recovery_nudge(event: RevenueEvent, message: str, channel: str) -> ActionResult:
    """Create a test-mode payment link so outreach never silently disappears."""
    if os.getenv("RAZORPAY_DEMO_MODE", "true").lower() == "true":
        return ActionResult(success=True, status=f"{channel}_queued", provider_id=f"demo_link_{event.event_id}")
    try:
        import razorpay
        client = razorpay.Client(auth=(os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"]))
        response = client.payment_link.create({"amount": event.amount, "currency": event.currency, "description": "Revenue recovery", "reference_id": event.event_id})
        provider_id = response.get("id")
        if not provider_id or response.get("status") not in {None, "created", "issued"}:
            return ActionResult(success=False, status="escalate", error="provider returned an invalid payment link")
        return ActionResult(success=True, status=f"{channel}_queued", provider_id=provider_id)
    except Exception as exc:
        return ActionResult(success=False, status="escalate", error=str(exc))
