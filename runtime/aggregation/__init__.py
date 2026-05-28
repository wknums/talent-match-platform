"""Shared pure aggregation library.

This module intentionally contains no Azure I/O. Callers are responsible for
loading per-run payloads (for example from blob artifacts) and passing them in.
"""

from runtime.aggregation.shared import (
    AGGREGATION_PROFILE_CV,
    AGGREGATION_PROFILE_GENERIC,
    aggregate_run_outputs,
    normalize_profile,
)

__all__ = [
    "AGGREGATION_PROFILE_CV",
    "AGGREGATION_PROFILE_GENERIC",
    "aggregate_run_outputs",
    "normalize_profile",
]
