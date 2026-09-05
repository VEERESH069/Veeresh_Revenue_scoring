"""FastAPI service boundary for bounded, auditable recovery operations."""

import hashlib
import hmac
import json
import logging
import os
import uuid
from collections import defaultdict

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from data.generate_synthetic_events import generate_events
from graph.build_graph import build_graph
from graph.promise_followup import run_promise_followups
from graph.guardrails import GuardrailTripped, MAX_BATCH_EXPOSURE, check_batch_guardrails
from eval.baseline_comparison import compare_approaches
from models.schemas import RevenueEvent
from graph.ai_classify_reply_intent import classify_reply_intent
from persistence.mongo import PersistenceUnavailable, get_store, production_mode, require_store

app = FastAPI(title="Revenue Recovery Agent")
logger = logging.getLogger("revenue_recovery.api")
audit_log: list[dict] = []
recovery_graph = build_graph()
MAX_BATCH_EVENTS = 100
RATE_LIMIT = max(1, int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")))
_demo_rate_counts: dict[str, int] = defaultdict(int)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Return stable client errors while retaining diagnostics in server logs."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    logger.exception("unhandled request failure", extra={"request_id": request_id, "path": request.url.path})
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "request_id": request_id}})


def require_api_key(required_role: str = "read"):
    """Build an API-key dependency with read/admin authorization roles."""
    def dependency(x_api_key: str | None = Header(default=None), x_api_role: str = Header(default="read")) -> None:
        if not production_mode():
            return
        configured_key = os.getenv("RECOVERY_API_KEY")
        configured_role = os.getenv("RECOVERY_API_ROLE", "admin")
        if not configured_key or not x_api_key or not hmac.compare_digest(x_api_key, configured_key):
            raise HTTPException(status_code=401, detail={"code": "authentication_required"})
        if required_role == "admin" and (configured_role != "admin" or x_api_role != "admin"):
            raise HTTPException(status_code=403, detail={"code": "admin_role_required"})
    return dependency


def rate_limit(x_api_key: str | None = Header(default=None)) -> None:
    """Use MongoDB-backed rate limiting in production and a bounded demo counter locally."""
    key = x_api_key or "demo"
    if production_mode():
        try:
            allowed = require_store().allow_request(key, RATE_LIMIT, 60)
        except PersistenceUnavailable as exc:
            raise HTTPException(status_code=503, detail={"code": "persistence_unavailable"}) from exc
        if not allowed:
            raise HTTPException(status_code=429, detail={"code": "rate_limit_exceeded"})
        return
    _demo_rate_counts[key] += 1
    if _demo_rate_counts[key] > RATE_LIMIT:
        raise HTTPException(status_code=429, detail={"code": "rate_limit_exceeded"})


@app.get("/health/live")
def liveness() -> dict[str, str]:
    """Kubernetes liveness probe that does not depend on external systems."""
    return {"status": "ok"}


@app.get("/health/ready")
def readiness() -> dict[str, str]:
    """Readiness probe that verifies the production database boundary."""
    if production_mode():
        try:
            require_store().ping()
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"code": "persistence_unavailable"}) from exc
    return {"status": "ready"}


@app.get("/metrics/prometheus", response_class=PlainTextResponse)
def prometheus_metrics() -> str:
    """Expose low-cardinality operational metrics for Prometheus scraping."""
    ready = 1
    try:
        records = require_store().get_metrics() if production_mode() else audit_log
    except PersistenceUnavailable:
        records = []
        ready = 0
    processing_errors = sum(row.get("error_code") == "processing_failed" for row in records)
    return "\n".join([
        "# TYPE revenue_recovery_ready gauge",
        f"revenue_recovery_ready {ready}",
        "# TYPE revenue_recovery_events_total gauge",
        f"revenue_recovery_events_total {len(records)}",
        "# TYPE revenue_recovery_processing_errors_total counter",
        f"revenue_recovery_processing_errors_total {processing_errors}",
    ]) + "\n"


@app.post("/run-batch")
def run_batch(events: list[dict] | None = None, x_idempotency_key: str | None = Header(default=None), _: None = Depends(require_api_key("admin")), __: None = Depends(rate_limit)) -> dict:
    """Run a bounded batch and return auditable outcomes for the demo operator."""
    batch_events = generate_events() if events is None else events
    if production_mode() and not x_idempotency_key:
        raise HTTPException(status_code=400, detail={"code": "idempotency_key_required"})
    if production_mode() and not require_store().claim_idempotency(x_idempotency_key or "", {"status": "processing"}):
        raise HTTPException(status_code=409, detail={"code": "duplicate_request"})
    if len(batch_events) > MAX_BATCH_EVENTS:
        raise HTTPException(status_code=413, detail=f"batch exceeds {MAX_BATCH_EVENTS} events")
    try:
        total_exposure = sum(max(0, int(event.get("amount", 0))) for event in batch_events)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="each event amount must be an integer")
    if total_exposure > MAX_BATCH_EXPOSURE:
        raise HTTPException(status_code=413, detail="batch exposure exceeds configured ceiling")
    batch_audit = []
    batch_event_ids = set()
    batch_stats = {"nudges_sent": 0, "total_amount_actioned": 0}
    for raw_event in batch_events:
        event_id = raw_event.get("event_id")
        previously_processed = require_store().has_event(event_id) if production_mode() and isinstance(event_id, str) else any(row.get("event_id") == event_id for row in audit_log)
        if event_id in batch_event_ids or previously_processed:
            batch_audit.append({"event_id": event_id, "outcome": "skipped", "error_code": "duplicate_event"})
            continue
        batch_event_ids.add(event_id)
        try:
            result = recovery_graph.invoke({"event": raw_event}) if hasattr(recovery_graph, "invoke") else recovery_graph({"event": raw_event})
            audit = result["audit"]
            batch_audit.append(audit)
            if audit.get("action_taken") not in {None, "none"}:
                batch_stats["total_amount_actioned"] += audit.get("amount", 0)
            if audit.get("action_taken") == "nudge":
                batch_stats["nudges_sent"] += 1
            check_batch_guardrails(batch_stats)
        except GuardrailTripped:
            batch_audit.append({"event_id": event_id, "outcome": "escalated", "error_code": "batch_guardrail_tripped"})
            break
        except Exception:
            batch_audit.append({"event_id": event_id, "outcome": "escalated", "error_code": "processing_failed"})
    audit_log.extend(batch_audit)
    return {"processed": len(batch_audit), "audit": batch_audit}


@app.get("/audit-log")
def get_audit_log(_: None = Depends(require_api_key("read")), __: None = Depends(rate_limit)) -> list[dict]:
    """Expose the immutable decision trail for human review."""
    return require_store().list_audit() if production_mode() else audit_log


@app.get("/metrics")
def metrics(_: None = Depends(require_api_key("read")), __: None = Depends(rate_limit)) -> dict:
    """Return business and model-cost indicators, keeping decision quality primary."""
    records = require_store().get_metrics() if production_mode() else audit_log
    total = len(records)
    denominator = total or 1
    recovered = sum(row.get("outcome") == "recovered" for row in records)
    tokens = sum(row.get("tokens_used", 0) for row in records)
    calls = sum(row.get("ai_calls", 0) for row in records)
    amount_recovered = sum(row.get("amount", 0) for row in records if row.get("outcome") == "recovered")
    return {"recovery_rate": recovered / denominator, "total_amount_recovered": amount_recovered / 100, "time_to_recovery": None, "false_retry_cost": 0, "nudge_efficiency": 0, "avg_tokens_per_event": tokens / denominator, "promise_kept_rate": 0, "ai_calls_per_event": calls / denominator, "total_tokens": tokens, "ai_latency_ms": sum(row.get("ai_latency_ms", 0) for row in audit_log), "decision_quality_primary": True}


@app.post("/run-promise-followups")
def promise_followups(_: None = Depends(require_api_key("admin")), __: None = Depends(rate_limit)) -> list[dict]:
    """Reconcile promises after their dates and update repeat-breaker history."""
    return run_promise_followups()


@app.get("/baseline-comparison")
def baseline_comparison(_: None = Depends(require_api_key("read")), __: None = Depends(rate_limit)) -> dict:
    """Expose the same-dataset naive-versus-policy evaluation for reviewers."""
    events = [
        RevenueEvent.model_validate({**event, "retry_count": max(0, event.get("retry_count", 0))})
        for event in generate_events()
    ]
    return compare_approaches(events)


@app.post("/classify-reply")
def classify_reply(payload: dict[str, str], _: None = Depends(require_api_key("read")), __: None = Depends(rate_limit)) -> dict:
    """Expose measured reply-intent judgment for promise follow-up demos."""
    judgment, telemetry = classify_reply_intent(payload.get("reply", ""))
    return {"intent": judgment.intent, "confidence": judgment.confidence, **telemetry}


@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> dict:
    """Verify Razorpay's raw-body signature before accepting a webhook event."""
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    signature = request.headers.get("X-Razorpay-Signature")
    body = await request.body()
    if not secret or not signature:
        raise HTTPException(status_code=401, detail={"code": "webhook_signature_required"})
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail={"code": "invalid_webhook_signature"})
    try:
        payload = json.loads(body)
        event_id = payload.get("id") or payload.get("event")
        if not event_id:
            raise ValueError("missing event id")
        if production_mode() and not require_store().record_webhook(event_id, payload):
            return {"status": "duplicate"}
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail={"code": "invalid_webhook_payload"})
    return {"status": "accepted", "event_id": event_id}
