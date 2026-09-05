"""Optional Langfuse setup: tracing must never become a payment dependency."""


def get_langfuse_handler():
    """Return a callback handler when configured, otherwise a harmless no-op."""
    try:
        from langfuse.callback import CallbackHandler
        return CallbackHandler()
    except Exception:
        return None


def log_ai_call(metadata: dict) -> dict:
    """Record AI cost and latency without allowing observability failure to affect recovery."""
    try:
        handler = get_langfuse_handler()
        if handler and hasattr(handler, "trace"):
            handler.trace(name=metadata["ai_component"], metadata=metadata)
    except Exception:
        pass
    return metadata
