"""Input coercion and simplex projection shared by inference routines."""
from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]


class ConvergenceError(RuntimeError):
    """An iterative numerical procedure did not meet its stopping criterion."""


def nonnegative_array(value: ArrayLike, name: str, dimensions: int) -> FloatArray:
    """Coerce numerical input without silently accepting NaNs or negative mass."""
    result = np.asarray(value, dtype=float)
    if result.ndim != dimensions or any(size == 0 for size in result.shape):
        raise ValueError(f"{name} must be a nonempty {dimensions}-dimensional array")
    if not np.isfinite(result).all() or (result < 0).any():
        raise ValueError(f"{name} must contain finite nonnegative values")
    return result


def probabilities(value: ArrayLike, shape: tuple[int, int], name: str) -> FloatArray:
    result = nonnegative_array(value, name, 2)
    if result.shape != shape or not np.allclose(result.sum(axis=1), 1, rtol=0, atol=1e-10):
        raise ValueError(f"{name} must have shape {shape} and rows summing to one")
    return result.copy()


def project_simplex(values: ArrayLike) -> FloatArray:
    """Euclidean projection of each row (last axis) onto the unit simplex."""
    vector = np.asarray(values, dtype=float)
    if vector.ndim == 0 or vector.shape[-1] == 0 or not np.isfinite(vector).all():
        raise ValueError("values must be nonempty and finite")
    ordered = -np.sort(-vector, axis=-1)
    thresholds = (np.cumsum(ordered, axis=-1) - 1.0) / np.arange(1, vector.shape[-1] + 1)
    support = np.sum(ordered > thresholds, axis=-1, keepdims=True)
    threshold = np.take_along_axis(thresholds, support - 1, axis=-1)
    return np.maximum(vector - threshold, 0.0)
