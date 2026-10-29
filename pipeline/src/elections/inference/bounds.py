"""Accounting bounds under explicit fixed-cohort and mobility assumptions."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike
from scipy.optimize import linprog

from .arrays import FloatArray, nonnegative_array


@dataclass(frozen=True)
class ContrastBounds:
    minimum: float
    maximum: float
    minimum_table: FloatArray
    maximum_table: FloatArray


def national_bounds(origins: ArrayLike, destinations: ArrayLike) -> tuple[FloatArray, FloatArray]:
    """Exact cellwise Frechet bounds for one closed cohort, not simultaneous extremes."""
    x = nonnegative_array(origins, "origins", 1)
    y = nonnegative_array(destinations, "destinations", 1)
    if not np.isclose(x.sum(), y.sum(), rtol=0, atol=1e-6):
        raise ValueError("fixed-cohort margins must have equal mass")
    return np.maximum(0, x[:, None] + y[None, :] - x.sum()), np.minimum(x[:, None], y[None, :])


def section_bounds(origins: ArrayLike, destinations: ArrayLike) -> tuple[FloatArray, FloatArray]:
    """Cellwise aggregate bounds assuming no movement between paired sections."""
    x = nonnegative_array(origins, "origins", 2)
    y = nonnegative_array(destinations, "destinations", 2)
    if len(x) != len(y) or not np.allclose(x.sum(axis=1), y.sum(axis=1), rtol=0, atol=1e-6):
        raise ValueError("closed section cohorts must have equal mass in both rounds")
    lower = np.maximum(0, x[:, :, None] + y[:, None, :] - x.sum(axis=1)[:, None, None]).sum(axis=0)
    upper = np.minimum(x[:, :, None], y[:, None, :]).sum(axis=0)
    return lower, upper


def mobility_bounds(origins: ArrayLike, destinations: ArrayLike, incoming: ArrayLike, outgoing: ArrayLike) -> tuple[FloatArray, FloatArray]:
    """Conservative outer cell bounds for a supplied balanced mobility scenario.

    These bounds need not be jointly attainable or sharp. They do not describe
    probability coverage, and the mobility counts are assumptions rather than
    identified individuals or routes.
    """
    x = nonnegative_array(origins, "origins", 2)
    y = nonnegative_array(destinations, "destinations", 2)
    entrants = nonnegative_array(incoming, "incoming", 1)
    leavers = nonnegative_array(outgoing, "outgoing", 1)
    if len(x) != len(y) or entrants.shape != (len(x),) or leavers.shape != entrants.shape:
        raise ValueError("mobility inputs must align by section")
    n1, n2 = x.sum(axis=1), y.sum(axis=1)
    if np.any(leavers > n1) or np.any(entrants > n2):
        raise ValueError("mobility cannot exceed cohort size")
    if not np.allclose(n1 + entrants, n2 + leavers, rtol=0, atol=1e-6) or not np.isclose(entrants.sum(), leavers.sum(), rtol=0, atol=1e-6):
        raise ValueError("local and national mobility margins must balance")
    lower = np.maximum(0, x[:, :, None] + y[:, None, :] - (n1 + entrants)[:, None, None]).sum(axis=0)
    upper = np.minimum(np.minimum(x[:, :, None], y[:, None, :]), (n1 - leavers)[:, None, None]).sum(axis=0) + leavers.sum()
    global_lower, global_upper = national_bounds(x.sum(axis=0), y.sum(axis=0))
    return np.maximum(lower, global_lower), np.minimum(upper, global_upper)


def linear_contrast_bounds(origins: ArrayLike, destinations: ArrayLike, contrast: ArrayLike, *, support: ArrayLike | None = None) -> ContrastBounds:
    """Optimize one joint linear contrast and return complete witness tables.

    The feasible set consists solely of the supplied closed-cohort margins and
    optional structural support. No ecological regression coefficients enter.
    """
    x = nonnegative_array(origins, "origins", 1)
    y = nonnegative_array(destinations, "destinations", 1)
    national_bounds(x, y)
    coefficients = np.asarray(contrast, dtype=float)
    shape = (len(x), len(y))
    if coefficients.shape != shape or not np.isfinite(coefficients).all():
        raise ValueError("contrast must be a finite matrix matching the margins")
    permitted = np.ones(shape, dtype=bool) if support is None else np.asarray(support, dtype=bool)
    if permitted.shape != shape:
        raise ValueError("support must match the margins")
    equality = np.zeros((sum(shape), np.prod(shape)))
    for i in range(shape[0]):
        equality[i, i * shape[1]:(i + 1) * shape[1]] = 1
    for j in range(shape[1]):
        equality[shape[0] + j, j::shape[1]] = 1
    variable_bounds = [(0, None) if allowed else (0, 0) for allowed in permitted.ravel()]
    solutions = []
    for direction in [1, -1]:
        solution = linprog(direction * coefficients.ravel(), A_eq=equality, b_eq=np.concatenate([x, y]), bounds=variable_bounds, method="highs")
        if not solution.success:
            raise ValueError(f"transportation constraints are infeasible: {solution.message}")
        solutions.append(solution.x.reshape(shape))
    return ContrastBounds(float(np.sum(coefficients * solutions[0])), float(np.sum(coefficients * solutions[1])), solutions[0], solutions[1])


@dataclass(frozen=True)
class GroupBounds:
    """Cellwise accounting bounds for flows attributed to each group's sections."""

    lower: FloatArray  # (groups, origins, destinations)
    upper: FloatArray  # (groups, origins, destinations)


def grouped_section_bounds(x: FloatArray, y: FloatArray, incoming: FloatArray, outgoing: FloatArray,
                           groups: np.ndarray, n_groups: int) -> GroupBounds:
    """Outer bounds per group under a fixed cohort and the supplied section mobility.

    In section s, voters who stay number n1 - outgoing. Stayers from origin i
    who vote j are at least x_i + y_j - n1 - incoming and at most
    min(x_i, y_j, n1 - outgoing). Each leaver can reach any destination, so the
    group's leavers are added to the upper bound, which is also capped by the
    group's origin count. Bounds are marginal per cell, not jointly attainable.
    """
    n1 = x.sum(axis=1)
    stay = n1 - outgoing
    origins, destinations = x.shape[1], y.shape[1]
    lower = np.empty((n_groups, origins, destinations))
    upper = np.empty((n_groups, origins, destinations))
    leavers = np.bincount(groups, outgoing, n_groups)
    observed = np.stack([np.bincount(groups, x[:, i], n_groups) for i in range(origins)], axis=1)
    for i in range(origins):
        for j in range(destinations):
            low = np.maximum(0, x[:, i] + y[:, j] - n1 - incoming)
            high = np.minimum(np.minimum(x[:, i], y[:, j]), stay)
            lower[:, i, j] = np.bincount(groups, low, n_groups)
            upper[:, i, j] = np.minimum(np.bincount(groups, high, n_groups) + leavers, observed[:, i])
    return GroupBounds(lower, upper)
