from __future__ import annotations

from runtime.aggregation import (
    AGGREGATION_PROFILE_CV,
    AGGREGATION_PROFILE_GENERIC,
    aggregate_run_outputs,
)


def test_shared_cv_profile_aggregation_matches_expected_shape() -> None:
    outputs = [
        {"overall_score": 70.0, "must_haves": [{"met": True}], "decision": "approve"},
        {"overall_score": 80.0, "must_haves": [{"met": True}], "decision": "approve"},
        {"overall_score": 75.0, "must_haves": [{"met": False}], "decision": "reject"},
    ]

    aggregated = aggregate_run_outputs(
        outputs,
        profile=AGGREGATION_PROFILE_CV,
        source_artifacts=[{"name": "output.json", "blob_uri": "https://x"}],
    )

    assert aggregated is not None
    assert aggregated["finalScore"] == 75.0
    assert aggregated["runsCount"] == 3
    assert aggregated["finalDecision"] in {"Approve", "Reject"}
    assert aggregated["mustHaveResult"] is False
    assert aggregated["sourceArtifacts"]


def test_shared_generic_profile_aggregation_returns_field_aggregations() -> None:
    outputs = [
        {"overall_score": 10.0, "nested": {"x": 1.0}},
        {"overall_score": 20.0, "nested": {"x": 3.0}},
        {"overall_score": 30.0, "nested": {"x": 5.0}},
    ]

    aggregated = aggregate_run_outputs(
        outputs,
        profile=AGGREGATION_PROFILE_GENERIC,
        method="median",
    )

    assert aggregated is not None
    assert aggregated["profile"] == AGGREGATION_PROFILE_GENERIC
    assert aggregated["runCount"] == 3
    assert aggregated["fieldAggregations"]["overall_score"] == 20.0
    assert aggregated["fieldAggregations"]["nested.x"] == 3.0
