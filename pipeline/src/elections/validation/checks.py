"""Finite-count, probability, and partition conservation checks.

Successful accounting validation does not establish individual-flow accuracy.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike

from elections.taxonomy import DESTINATION_IDS as DESTINATIONS


def _tolerance(value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError("tolerance must be finite and positive")


def _count(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return float(value)


def validate_probability_matrix(matrix: ArrayLike, tolerance: float = 1e-10) -> None:
    """Require a finite nonnegative matrix with unit row sums."""
    _tolerance(tolerance)
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or min(values.shape, default=0) == 0 or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("probabilities must form a finite nonnegative nonempty matrix")
    if not np.allclose(values.sum(axis=1), 1, rtol=0, atol=tolerance):
        raise ValueError("probability rows must sum to one")


def validate_flow_row(row: Mapping, tolerance: float = 0.001) -> None:
    """Validate five-destination accounting without interpreting ranges as CIs."""
    _tolerance(tolerance)
    if not isinstance(row.get("originId"), str) or not row["originId"]:
        raise ValueError("originId must be a nonempty string")
    observed = _count(row.get("observed"), "observed")
    estimates = row.get("estimated")
    if not isinstance(estimates, Mapping) or set(estimates) != set(DESTINATIONS):
        raise ValueError("estimated must contain exactly the five destinations")
    counts = {key: _count(estimates[key], f"estimated.{key}") for key in DESTINATIONS}
    if abs(math.fsum(counts.values()) - observed) > tolerance:
        raise ValueError("estimated destination counts do not preserve the observed origin")
    if observed == 0 and any(counts.values()):
        raise ValueError("zero-origin rows cannot contain positive estimated flows")
    for field in ["sensitivity", "identificationBounds"]:
        ranges = row.get(field)
        if ranges is None:
            continue
        if not isinstance(ranges, Mapping) or set(ranges) != {"lula", "flavio"}:
            raise ValueError(f"{field} must contain both finalist ranges")
        for destination, interval in ranges.items():
            if not isinstance(interval, Mapping) or set(interval) != {"min", "max"}:
                raise ValueError(f"{field}.{destination} must have min and max")
            lower = _count(interval["min"], f"{field}.min")
            upper = _count(interval["max"], f"{field}.max")
            if lower > upper or upper > observed + tolerance:
                raise ValueError(f"{field} range is outside its origin base")
            if field == "sensitivity" and not lower - tolerance <= counts[destination] <= upper + tolerance:
                raise ValueError("point estimate is outside sensitivity scenarios")


def _row_map(rows: Sequence[Mapping], tolerance: float) -> dict[str, Mapping]:
    result = {}
    for row in rows:
        validate_flow_row(row, tolerance)
        if row["originId"] in result:
            raise ValueError("origin IDs must be unique within a place")
        result[row["originId"]] = row
    if not result:
        raise ValueError("a place must include origin rows")
    return result


def validate_partition(parent_rows: Sequence[Mapping], child_rows: Sequence[Sequence[Mapping]], tolerance: float = 0.001) -> None:
    """Check one geographic partition, including its explicit residual.

    The caller must select one layer. Different geographical layers must never
    be concatenated. Sensitivity endpoints are intentionally not summed.
    """
    _tolerance(tolerance)
    parent = _row_map(parent_rows, tolerance)
    children = [_row_map(rows, tolerance) for rows in child_rows]
    if not children:
        raise ValueError("a partition must contain at least one child")
    if any(set(child) != set(parent) for child in children):
        raise ValueError("partition members must contain the same raw origin IDs")
    for origin_id, row in parent.items():
        observed = math.fsum(child[origin_id]["observed"] for child in children)
        if abs(observed - row["observed"]) > tolerance:
            raise ValueError(f"partition loses observed origin mass: {origin_id}")
        for destination in DESTINATIONS:
            estimated = math.fsum(child[origin_id]["estimated"][destination] for child in children)
            if abs(estimated - row["estimated"][destination]) > tolerance:
                raise ValueError(f"partition loses estimated mass: {origin_id}/{destination}")
