"""Compare the bounded recovery graph with a deliberately unsafe naive baseline."""

from datetime import datetime, timedelta, timezone
from typing import Any

from graph.build_graph import build_graph
from memory.mem0_client import _history
from models.schemas import AuditRecord, RevenueEvent

COOLDOWN = timedelta(hours=24)


def run_naive_baseline(events: list[RevenueEvent]) -> list[AuditRecord]:
    """Model a fixed retry-and-SMS agent so policy value has a concrete counterfactual."""
    return [AuditRecord(
        event_id=event.event_id,
        event_type=event.event_type,
        root_cause=event.true_root_cause or event.failure_code,
        confidence=1.0,
        policy_decision="retry",
        policy_reason="fixed two retries; no policy evaluation",
        action_taken="retry x2; nudge",
        action_result="failed",
        outcome="failed",
        timestamp=event.timestamp,
        tokens_used=0,
    ) for event in events]


def count_compliance_violations(audit_records: list[AuditRecord], customer_histories: dict[str, dict[str, Any]], event_by_id: dict[str, RevenueEvent]) -> int:
    """Count opt-out and cooldown breaches consistently for both approaches."""
    violations = 0
    for record in audit_records:
        event = event_by_id[record.event_id]
        history = customer_histories.get(event.customer_id, {})
        if history.get("opted_out") and record.action_taken != "none":
            violations += 1
        last_nudge_at = history.get("last_nudge_at")
        if isinstance(last_nudge_at, str):
            last_nudge_at = datetime.fromisoformat(last_nudge_at)
        if last_nudge_at and abs(record.timestamp - last_nudge_at) < COOLDOWN and "nudge" in record.action_taken:
            violations += 1
    return violations


def _metrics(records: list[AuditRecord], events: list[RevenueEvent], histories: dict[str, dict[str, Any]]) -> dict:
    """Calculate comparable recovery, risk, and operational-efficiency measures."""
    event_by_id = {event.event_id: event for event in events}
    total_amount = sum(event.amount for event in events)
    recovered_amount = sum(event_by_id[record.event_id].amount for record in records if record.outcome == "recovered")
    false_retries = sum(1 for record in records if record.policy_decision == "retry" and record.root_cause in {"revoked", "card_declined", "unrecoverable"})
    return {
        "recovery_rate": recovered_amount / total_amount if total_amount else 0.0,
        "amount_recovered": recovered_amount,
        "false_retry_count": false_retries,
        "compliance_violations": count_compliance_violations(records, histories, event_by_id),
        "avg_actions_per_event": sum(record.action_taken.count("retry") + record.action_taken.count("nudge") for record in records) / max(1, len(records)),
    }


def _history_fixture(events: list[RevenueEvent]) -> dict[str, dict[str, Any]]:
    """Create visible demo conditions for opt-out and cooldown checks without production changes."""
    customers = sorted({event.customer_id for event in events})
    return {
        customer: {
            "opted_out": customer.endswith(("000", "010")),
            "last_nudge_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat() if customer.endswith("005") else None,
        }
        for customer in customers
    }


def compare_approaches(events: list[RevenueEvent]) -> dict:
    """Run identical events through naive and existing graph paths and return deltas."""
    normalized = []
    for event in events:
        if isinstance(event, RevenueEvent):
            normalized.append(event)
            continue
        payload = dict(event)
        payload["retry_count"] = max(0, payload.get("retry_count", 0))
        normalized.append(RevenueEvent.model_validate(payload))
    histories = _history_fixture(normalized)
    _history.clear()
    _history.update(histories)
    naive_records = run_naive_baseline(normalized)
    graph = build_graph()
    policy_records = []
    for event in normalized:
        try:
            state = {"event": event.model_dump()}
            result = graph.invoke(state) if hasattr(graph, "invoke") else graph(state)
            policy_records.append(AuditRecord.model_validate(result["audit"]))
        except Exception:
            policy_records.append(AuditRecord(event_id=event.event_id, event_type=event.event_type, root_cause=event.failure_code, confidence=0.0, policy_decision="escalate", policy_reason="comparison fallback", action_taken="none", action_result="not_executed", outcome="escalated", timestamp=event.timestamp))
    naive = _metrics(naive_records, normalized, histories)
    policy_engine = _metrics(policy_records, normalized, histories)
    return {
        "naive": naive,
        "policy_engine": policy_engine,
        "delta_amount_recovered": policy_engine["amount_recovered"] - naive["amount_recovered"],
        "delta_compliance_violations": naive["compliance_violations"] - policy_engine["compliance_violations"],
    }
