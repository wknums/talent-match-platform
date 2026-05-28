"""Profile-aware shared aggregation logic (pure compute).

The library accepts already-loaded per-run outputs and aggregates them by
profile so multiple callers can reuse the same behavior.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

AGGREGATION_PROFILE_GENERIC = "generic_passthrough"
AGGREGATION_PROFILE_CV = "cv_scoring_v1"

_ALLOWED_PROFILES = {
    AGGREGATION_PROFILE_GENERIC,
    AGGREGATION_PROFILE_CV,
}


def normalize_profile(profile: str | None) -> str:
    """Normalize and validate aggregation profile."""
    normalized = (profile or AGGREGATION_PROFILE_GENERIC).strip().lower()
    if normalized not in _ALLOWED_PROFILES:
        allowed = ", ".join(sorted(_ALLOWED_PROFILES))
        raise ValueError(f"Unsupported aggregation profile '{profile}'. Supported profiles: {allowed}")
    return normalized


def aggregate_run_outputs(
    outputs: list[dict[str, Any]],
    *,
    profile: str,
    method: str = "median",
    source_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Aggregate parsed run outputs for the selected profile."""
    normalized = normalize_profile(profile)
    if normalized == AGGREGATION_PROFILE_CV:
        return _aggregate_cv_scoring(outputs, source_artifacts=source_artifacts)
    return _aggregate_generic(outputs, method=method, source_artifacts=source_artifacts)


def _aggregate_cv_scoring(
    outputs: list[dict[str, Any]],
    *,
    source_artifacts: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not outputs:
        return None

    parsed: list[dict[str, Any]] = []
    for output in outputs:
        signal = _extract_cv_signal(output)
        if signal is not None:
            parsed.append(signal)

    if not parsed:
        return None

    scores = [p["score"] for p in parsed if isinstance(p["score"], (int, float))]
    final_score = statistics.median(scores) if scores else None
    variance = statistics.pvariance(scores) if len(scores) > 1 else 0.0
    decisions = [p["decision"] for p in parsed]
    decision = max(set(decisions), key=decisions.count) if decisions else None
    must_have = all(p["must_all_met"] for p in parsed)

    return {
        "finalScore": final_score,
        "variance": variance,
        "finalDecision": decision,
        "mustHaveResult": must_have,
        "sourceArtifacts": source_artifacts or [],
        "runsCount": len(parsed),
    }


def _extract_cv_signal(output: dict[str, Any]) -> dict[str, Any] | None:
    positive_decisions = {
        "approve",
        "approved",
        "accept",
        "accepted",
        "pass",
        "passed",
        "recommend",
        "recommended",
        "strong_match",
    }
    negative_decisions = {
        "reject",
        "rejected",
        "cannot_assess",
        "insufficient_information",
        "fail",
        "failed",
    }
    negative_statuses = {
        "insufficient_data",
        "insufficient_information",
    }

    composite_score = output.get("composite_score") if isinstance(output.get("composite_score"), dict) else {}
    eligibility = output.get("eligibility") if isinstance(output.get("eligibility"), dict) else {}

    score = output.get("overall_score", output.get("score"))
    if score is None:
        score = composite_score.get("value")

    decision_raw = str(output.get("decision") or output.get("final_decision") or "").strip().lower()
    if not decision_raw:
        decision_raw = str(eligibility.get("status") or "").strip().lower()
    status_raw = str(output.get("status") or "").strip().lower()

    must_haves = output.get("must_haves", output.get("must_have_results", []) or [])
    if not must_haves and isinstance(eligibility.get("requirements_checklist"), dict):
        must_haves = [
            value
            for value in eligibility["requirements_checklist"].values()
            if isinstance(value, dict)
        ]

    if must_haves:
        must_all_met = all(bool(m.get("met")) for m in must_haves)
    elif decision_raw:
        must_all_met = decision_raw in positive_decisions
    else:
        must_all_met = False

    if score is None and status_raw in negative_statuses:
        score = 0.0

    if score is None and not must_haves and not decision_raw and not status_raw:
        return None

    if decision_raw in positive_decisions:
        decision = "Approve"
    elif decision_raw in negative_decisions:
        decision = "Reject"
    else:
        decision = "Approve" if must_all_met else "Reject"

    return {
        "score": float(score) if isinstance(score, (int, float)) else None,
        "must_all_met": must_all_met,
        "decision": decision,
    }


def _aggregate_generic(
    outputs: list[dict[str, Any]],
    *,
    method: str,
    source_artifacts: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not outputs:
        return None

    numeric_by_path: dict[str, list[float]] = defaultdict(list)
    for output in outputs:
        for path, value in _extract_numeric_paths(output).items():
            numeric_by_path[path].append(value)

    field_aggregations: dict[str, float] = {}
    for path, values in numeric_by_path.items():
        field_aggregations[path] = _aggregate_values(values, method)

    return {
        "profile": AGGREGATION_PROFILE_GENERIC,
        "method": method,
        "runCount": len(outputs),
        "fieldAggregations": field_aggregations,
        "sourceArtifacts": source_artifacts or [],
    }


def _extract_numeric_paths(output: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                next_path = f"{path}.{key}" if path else str(key)
                visit(value, next_path)
            return
        if isinstance(node, list):
            for index, value in enumerate(node):
                next_path = f"{path}[{index}]"
                visit(value, next_path)
            return
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            result[path] = float(node)

    visit(output, "")
    return result


def _aggregate_values(values: list[float], method: str) -> float:
    if not values:
        return 0.0
    if method == "mean":
        return float(statistics.mean(values))
    if method == "trimmed_mean":
        sorted_values = sorted(values)
        trim_count = max(1, int(len(sorted_values) * 0.1)) if len(sorted_values) > 2 else 0
        trimmed = sorted_values[trim_count : len(sorted_values) - trim_count] if trim_count else sorted_values
        return float(statistics.mean(trimmed or values))
    if method == "interquartile_mean":
        if len(values) < 4:
            return float(statistics.mean(values))
        sorted_values = sorted(values)
        q1_index = len(sorted_values) // 4
        q3_index = 3 * len(sorted_values) // 4
        middle = sorted_values[q1_index : q3_index + 1]
        return float(statistics.mean(middle or values))
    return float(statistics.median(values))
