"""Promise-to-pay reconciliation loop."""

from datetime import date

from memory.mem0_client import _promises, mark_promise_outcome


def run_promise_followups(payment_received=None) -> list[dict]:
    """Verify overdue promises and make broken promises visible to future policy."""
    payment_received = payment_received or (lambda record: False)
    results = []
    for customer_id, record in list(_promises.items()):
        if record["promise_date"] <= date.today() and record.get("kept") is None:
            kept = bool(payment_received(record))
            mark_promise_outcome(customer_id, kept)
            results.append({"customer_id": customer_id, "kept": kept})
    return results
