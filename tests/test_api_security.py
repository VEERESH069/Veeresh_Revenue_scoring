import hashlib
import hmac
import json

from fastapi.testclient import TestClient


def test_health_and_demo_metrics(monkeypatch):
    monkeypatch.setenv("RAZORPAY_DEMO_MODE", "true")
    from api.main import app

    client = TestClient(app)
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").status_code == 200
    assert client.get("/metrics").status_code == 200


def test_production_requires_api_key(monkeypatch):
    monkeypatch.setenv("RAZORPAY_DEMO_MODE", "false")
    monkeypatch.setenv("RECOVERY_API_KEY", "test-key")
    from api.main import app

    client = TestClient(app)
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"X-API-Key": "test-key"}).status_code in {200, 503}


def test_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("RAZORPAY_DEMO_MODE", "true")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "secret")
    from api.main import app

    client = TestClient(app)
    payload = json.dumps({"id": "evt_1", "event": "payment.captured"}).encode()
    assert client.post("/webhooks/razorpay", content=payload, headers={"X-Razorpay-Signature": "bad"}).status_code == 401
    signature = hmac.new(b"secret", payload, hashlib.sha256).hexdigest()
    assert client.post("/webhooks/razorpay", content=payload, headers={"X-Razorpay-Signature": signature}).status_code == 200


def test_demo_batch_runs_end_to_end(monkeypatch):
    monkeypatch.setenv("RAZORPAY_DEMO_MODE", "true")
    from api.main import app

    client = TestClient(app)
    event = {
        "event_id": "integration_evt_1", "event_type": "payment_failure", "customer_id": "integration_c1",
        "merchant_id": "merchant_1", "order_id": "order_1", "amount": 5000, "payment_method": "card",
        "failure_reason_raw": "temporary network issue", "failure_code": "network_error",
        "timestamp": "2026-01-01T00:00:00Z", "retry_count": 0,
    }
    response = client.post("/run-batch", json=[event])
    assert response.status_code == 200
    assert response.json()["audit"][0]["event_id"] == "integration_evt_1"