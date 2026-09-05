"""Mem0 adapter with a conservative local fallback for service outages."""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from persistence.mongo import get_store, production_mode

_history: dict[str, dict[str, Any]] = {}
_promises: dict[str, dict[str, Any]] = {}


def get_customer_history(customer_id: str) -> dict[str, Any]:
    """Retrieve cross-cycle context so repeat failures receive safer treatment."""
    if production_mode():
        store = get_store()
        return store.get_customer(customer_id)
    try:
        return _history.get(customer_id, {"opted_out": False, "broken_promises": 0})
    except Exception:
        return {"opted_out": False, "retry_count": 99, "broken_promises": 99}


def update_customer_history(customer_id: str, values: dict[str, Any]) -> None:
    """Persist outcome context that improves future bounded decisions."""
    if production_mode():
        get_store().update_customer(customer_id, values)
        return
    try:
        _history.setdefault(customer_id, {}).update(values)
    except Exception:
        return None


def get_active_promise(customer_id: str) -> dict[str, Any] | None:
    """Find an unexpired promise so the system does not harass a paying customer."""
    try:
        promise = _promises.get(customer_id)
        return promise if promise and promise["promise_date"] >= date.today() else None
    except Exception:
        return {"promise_date": date.max, "conservative": True}


def record_promise(customer_id: str, event_id: str, promise_date: date) -> dict[str, Any]:
    """Record a promise-to-pay for later verification and auditability."""
    record = {"customer_id": customer_id, "event_id": event_id, "promise_date": promise_date, "follow_up_date": promise_date + timedelta(days=1), "created_at": datetime.now(timezone.utc)}
    try:
        _promises[customer_id] = record
    except Exception:
        pass
    return record


def mark_promise_outcome(customer_id: str, kept: bool) -> None:
    """Feed promise outcomes into future recovery conservatism."""
    promise = _promises.get(customer_id)
    if promise:
        promise["kept"] = kept
    if not kept:
        update_customer_history(customer_id, {"broken_promises": get_customer_history(customer_id).get("broken_promises", 0) + 1})
