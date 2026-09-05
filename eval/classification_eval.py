"""Offline evaluation of classification accuracy and confidence calibration."""


def evaluate(records: list[dict]) -> dict:
    """Report accuracy, macro precision/recall/F1, and confidence calibration."""
    buckets = {"low": [], "medium": [], "high": []}
    labels = {record.get("true_root_cause") for record in records} - {None}
    labels.update(record.get("root_cause") for record in records)
    true_positive = {label: 0 for label in labels}
    predicted = {label: 0 for label in labels}
    actual = {label: 0 for label in labels}
    for record in records:
        confidence = record.get("confidence", 0)
        bucket = "low" if confidence < 0.5 else "medium" if confidence < 0.8 else "high"
        buckets[bucket].append(record["root_cause"] == record.get("true_root_cause"))
        prediction = record.get("root_cause")
        expected = record.get("true_root_cause")
        if prediction in predicted:
            predicted[prediction] += 1
        if expected in actual:
            actual[expected] += 1
        if prediction == expected and expected in true_positive:
            true_positive[expected] += 1
    per_label = {}
    for label in sorted(labels):
        precision = true_positive[label] / max(1, predicted[label])
        recall = true_positive[label] / max(1, actual[label])
        per_label[label] = {"precision": precision, "recall": recall, "f1": 2 * precision * recall / max(1e-12, precision + recall)}
    macro = {metric: sum(values[metric] for values in per_label.values()) / max(1, len(per_label)) for metric in ("precision", "recall", "f1")}
    accuracy = sum(value for values in buckets.values() for value in values) / max(1, len(records))
    return {"accuracy": accuracy, "match_rate": accuracy, "precision": macro["precision"], "recall": macro["recall"], "f1": macro["f1"], "per_label": per_label, "accuracy_by_confidence": {key: sum(values) / max(1, len(values)) for key, values in buckets.items()}}
