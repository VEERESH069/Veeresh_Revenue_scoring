"""Evaluate policy correctness independently of whether money is recovered."""


def evaluate(records: list[dict]) -> dict:
    """Make stop-condition and retry-bound adherence the primary quality metric."""
    checks = [record.get("policy_decision") != "retry" or record.get("retry_count", 0) < 3 for record in records]
    return {"decision_quality": sum(checks) / max(1, len(checks)), "primary_metric": "decision_quality", "sample_size": len(records)}
