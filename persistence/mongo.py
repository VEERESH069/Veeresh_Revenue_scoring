"""MongoDB repositories with indexes, idempotency, and bounded query helpers."""

import os
from datetime import datetime, timedelta, timezone
from typing import Any

class PersistenceUnavailable(RuntimeError):
    """Raised when production persistence is not configured or reachable."""


class MongoStore:
    """Small synchronous repository used by FastAPI's synchronous handlers."""

    def __init__(self) -> None:
        try:
            from pymongo import MongoClient
            from pymongo.errors import DuplicateKeyError
        except ImportError as exc:
            raise PersistenceUnavailable("pymongo is required for production persistence") from exc
        uri = os.getenv("MONGODB_URI")
        if not uri:
            raise PersistenceUnavailable("MONGODB_URI is required")
        self.client = MongoClient(uri, serverSelectionTimeoutMS=2000)
        database_name = os.getenv("MONGODB_DATABASE", "revenue_recovery")
        self.db = self.client[database_name]
        self.audit = self.db["audit_records"]
        self.customers = self.db["customer_history"]
        self.idempotency = self.db["idempotency_keys"]
        self.rate_limits = self.db["rate_limits"]
        self.webhooks = self.db["webhook_events"]
        self._duplicate_key_error = DuplicateKeyError
        self._return_document_after = 1
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self.audit.create_index([("event_id", ASCENDING)], unique=True)
        self.audit.create_index([("timestamp", DESCENDING)])
        self.customers.create_index([("customer_id", ASCENDING)], unique=True)
        self.idempotency.create_index([("key", ASCENDING)], unique=True)
        self.idempotency.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
        self.rate_limits.create_index([("key", ASCENDING)], unique=True)
        self.rate_limits.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
        self.webhooks.create_index([("event_id", ASCENDING)], unique=True)

    def ping(self) -> None:
        try:
            self.client.admin.command("ping")
        except Exception as exc:
            raise PersistenceUnavailable("MongoDB is unavailable") from exc

    def has_event(self, event_id: str) -> bool:
        return self.audit.find_one({"event_id": event_id}, {"_id": 1}) is not None

    def save_audit(self, record: dict[str, Any]) -> bool:
        try:
            self.audit.insert_one({**record, "stored_at": datetime.now(timezone.utc)})
            return True
        except self._duplicate_key_error:
            return False

    def list_audit(self, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self.audit.find({}, {"_id": 0}).sort("timestamp", DESCENDING).limit(limit)
        return list(rows)

    def get_metrics(self) -> list[dict[str, Any]]:
        return list(self.audit.find({}, {"_id": 0}))

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        row = self.customers.find_one({"customer_id": customer_id}, {"_id": 0})
        return row or {"customer_id": customer_id, "opted_out": False, "broken_promises": 0}

    def update_customer(self, customer_id: str, values: dict[str, Any]) -> None:
        self.customers.update_one({"customer_id": customer_id}, {"$set": {**values, "customer_id": customer_id}}, upsert=True)

    def claim_idempotency(self, key: str, response: dict[str, Any]) -> bool:
        try:
            self.idempotency.insert_one({"key": key, "response": response, "created_at": datetime.now(timezone.utc), "expires_at": datetime.now(timezone.utc) + timedelta(days=7)})
            return True
        except self._duplicate_key_error:
            return False

    def record_webhook(self, event_id: str, payload: dict[str, Any]) -> bool:
        try:
            self.webhooks.insert_one({"event_id": event_id, "payload": payload, "received_at": datetime.now(timezone.utc)})
            return True
        except DuplicateKeyError:
            return False

    def allow_request(self, key: str, limit: int, window_seconds: int) -> bool:
        now = datetime.now(timezone.utc)
        expires = datetime.fromtimestamp(now.timestamp() + window_seconds, timezone.utc)
        row = self.rate_limits.find_one_and_update(
            {"key": key, "expires_at": {"$gt": now}},
            {"$inc": {"count": 1}},
            return_document=self._return_document_after,
        )
        if row:
            return row.get("count", 0) <= limit
        try:
            self.rate_limits.insert_one({"key": key, "count": 1, "expires_at": expires})
            return True
        except self._duplicate_key_error:
            return False


def production_mode() -> bool:
    return os.getenv("RAZORPAY_DEMO_MODE", "true").lower() != "true"


_store: MongoStore | None = None


def get_store() -> MongoStore | None:
    global _store
    if not production_mode():
        return None
    if _store is None:
        _store = MongoStore()
        _store.ping()
    return _store


def require_store() -> MongoStore:
    """Return the production store or fail explicitly when persistence is disabled."""
    store = get_store()
    if store is None:
        raise PersistenceUnavailable("MongoDB store is not enabled")
    return store