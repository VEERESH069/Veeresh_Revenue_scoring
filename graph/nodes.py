"""Graph nodes: LLMs judge language and cause; code controls financial action."""

import json
import re
from datetime import date, timedelta
from pathlib import Path

from graph.guardrails import validate_action_output, validate_event
from graph.ai_classify_root_cause import classify_root_cause as ai_classify_root_cause
from graph.ai_generate_nudge import generate_nudge as ai_generate_nudge
from graph.ai_judge_nudge_quality import judge_nudge_quality as ai_judge_nudge_quality
from graph.policy import decide_action, select_channel
from integrations.razorpay_client import retry_payment, send_recovery_nudge
from memory.mem0_client import get_customer_history, record_promise, update_customer_history
from models.schemas import ActionResult, RevenueEvent
from persistence.mongo import get_store, production_mode


def ingest_event(state: dict) -> dict:
    """Validate an event and load customer context before any judgment is made."""
    event = RevenueEvent.model_validate(state["event"])
    history = get_customer_history(event.customer_id)
    validate_event(event, history)
    return {**state, "event": event, "customer_history": history}


def classify_root_cause(state: dict) -> dict:
    """Call the isolated AI classifier while preserving measurable call metadata."""
    event = state["event"]
    judgment, telemetry = ai_classify_root_cause(event)
    return {**state, "root_cause": judgment.root_cause, "confidence": judgment.confidence, "tokens_used": telemetry["tokens_used"], "ai_calls": telemetry["ai_calls"], "ai_latency_ms": telemetry["ai_latency_ms"], "ai_models": [telemetry["ai_model"]], "ai_components": [telemetry["ai_component"]]}


def check_policy_gate(state: dict) -> dict:
    """Apply deterministic bounds and choose the least costly suitable channel."""
    event = state["event"]
    decision, reason = decide_action(event.event_type.value, state["root_cause"], event.retry_count, state.get("customer_history", {}), event.customer_tier, event.subscription_cycle_number)
    return {**state, "policy_decision": decision, "policy_reason": reason, "channel": select_channel(event.amount, event.customer_tier)}


def validate_output(state: dict) -> dict:
    """Run the last fail-closed check before any provider call or customer message."""
    validate_action_output(state["policy_decision"], state["event"], state.get("nudge_content", ""))
    return state


def execute_action(state: dict) -> dict:
    """Execute only the policy-approved action and preserve provider errors."""
    decision = state["policy_decision"]
    event = state["event"]
    if decision == "retry":
        result = retry_payment(event)
    elif decision == "nudge":
        result = send_recovery_nudge(event, state.get("nudge_content", ""), state["channel"])
    elif decision == "await_promise":
        promise_date = date.today() + timedelta(days=3)
        record_promise(event.customer_id, event.event_id, promise_date)
        result = ActionResult(success=True, status="promise_recorded")
    else:
        result = ActionResult(success=True, status="no_auto_action")
    outcome = "recovered" if result.status == "recovered" else "pending" if result.success else "escalated"
    return {**state, "action_result": result, "outcome": outcome}


def generate_nudge(state: dict) -> dict:
    """Call the isolated AI copywriter only for policy-approved nudges."""
    if state["policy_decision"] != "nudge":
        return state
    event = state["event"]
    copy, telemetry = ai_generate_nudge(event, event.locale)
    return {**state, "nudge_content": copy.message, "tokens_used": state.get("tokens_used", 0) + telemetry["tokens_used"], "ai_calls": state.get("ai_calls", 0) + telemetry["ai_calls"], "ai_latency_ms": state.get("ai_latency_ms", 0) + telemetry["ai_latency_ms"], "ai_models": state.get("ai_models", []) + [telemetry["ai_model"]], "ai_components": state.get("ai_components", []) + [telemetry["ai_component"]]}


def judge_nudge_quality(state: dict) -> dict:
    """Call the isolated AI judge and deterministically block compliance scores below seven."""
    if state.get("policy_decision") == "nudge":
        score, telemetry = ai_judge_nudge_quality(state.get("nudge_content", ""))
        state = {**state, "tokens_used": state.get("tokens_used", 0) + telemetry["tokens_used"], "ai_calls": state.get("ai_calls", 0) + telemetry["ai_calls"], "ai_latency_ms": state.get("ai_latency_ms", 0) + telemetry["ai_latency_ms"], "ai_models": state.get("ai_models", []) + [telemetry["ai_model"]], "ai_components": state.get("ai_components", []) + [telemetry["ai_component"]]}
        if score.compliance < 7:
            return {**state, "policy_decision": "escalate", "policy_reason": "nudge quality below compliance threshold"}
    if state.get("policy_decision") == "nudge" and len(state.get("nudge_content", "")) < 20:
        return {**state, "policy_decision": "escalate", "policy_reason": "nudge quality below compliance threshold"}
    return state


def update_memory(state: dict) -> dict:
    """Persist the outcome so future cycles learn from recovery and failure."""
    event = state["event"]
    update_customer_history(event.customer_id, {"last_outcome": state.get("outcome", "pending"), "last_root_cause": state["root_cause"]})
    return state


def log_audit(state: dict) -> dict:
    """Write durable evidence; production never falls back to a local file."""
    result = state.get("action_result", ActionResult(success=False, status="not_executed"))
    record = {"event_id": state["event"].event_id, "event_type": state["event"].event_type.value, "amount": state["event"].amount, "failure_reason_raw": state["event"].failure_reason_raw, "root_cause": state["root_cause"], "classification_reasoning": state.get("classification_reasoning", ""), "confidence": state["confidence"], "policy_decision": state["policy_decision"], "policy_reason": state["policy_reason"], "action_taken": state["policy_decision"] if state["policy_decision"] not in {"escalate", "close"} else "none", "action_result": result.status, "outcome": state.get("outcome", "pending"), "nudge_content": state.get("nudge_content", ""), "timestamp": state["event"].timestamp.isoformat(), "tokens_used": state.get("tokens_used", 0), "ai_calls": state.get("ai_calls", 0), "ai_latency_ms": state.get("ai_latency_ms", 0), "ai_models": state.get("ai_models", []), "ai_components": state.get("ai_components", [])}
    if production_mode():
        if not get_store().save_audit(record):
            return {**state, "audit": record, "duplicate": True}
    else:
        with Path("audit_fallback.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    return {**state, "audit": record}
