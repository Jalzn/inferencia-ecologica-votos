"""Constrained ecological regression with hierarchical geographic shrinkage.

For a group g, the transition matrix P (origins x destinations, rows on the unit
simplex) minimizes

    sum_s w_s n2_s || p_s P - q_s ||^2 + sum_i lambda_i || P_i - parent_i ||^2,

where p_s and q_s are first- and second-round section shares. The objective is
a convex quadratic, so each group's solution is unique whenever every row has
positive curvature. A good aggregate fit does not identify individual
transitions; these matrices are conditional model estimates.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from .arrays import ConvergenceError, FloatArray, project_simplex

DEGENERATE_CURVATURE = 1e-14
PREVALENCE_FLOOR = 1e-7
STATE_PREVALENCE_FRACTION = 0.01


@dataclass(frozen=True)
class Moments:
    """Sufficient statistics of the weighted least-squares objective per group."""

    gram: FloatArray   # (groups, origins, origins)
    cross: FloatArray  # (groups, origins, destinations)
    counts: FloatArray  # (groups, origins): weighted first-round origin counts

    def combine(self, parent: ArrayLike, groups: int) -> "Moments":
        """Add group statistics into coarser groups given each group's parent index."""
        index = np.asarray(parent)
        gram = np.zeros((groups,) + self.gram.shape[1:])
        cross = np.zeros((groups,) + self.cross.shape[1:])
        counts = np.zeros((groups, self.counts.shape[1]))
        np.add.at(gram, index, self.gram)
        np.add.at(cross, index, self.cross)
        np.add.at(counts, index, self.counts)
        return Moments(gram, cross, counts)


def section_moments(x: FloatArray, y: FloatArray, n1: FloatArray, n2: FloatArray, groups: ArrayLike,
                    n_groups: int, weights: FloatArray | None = None) -> Moments:
    """Group statistics with section weight w_s * n2_s on share residuals."""
    groups = np.asarray(groups)
    base = np.ones(len(x)) if weights is None else np.asarray(weights, dtype=float)
    weight = base * n2
    p = x / n1[:, None]
    q = y / n2[:, None]
    origins, destinations = x.shape[1], y.shape[1]
    gram = np.empty((n_groups, origins, origins))
    cross = np.empty((n_groups, origins, destinations))
    for i in range(origins):
        weighted = weight * p[:, i]
        for j in range(i, origins):
            gram[:, i, j] = gram[:, j, i] = np.bincount(groups, weighted * p[:, j], n_groups)
        for d in range(destinations):
            cross[:, i, d] = np.bincount(groups, weighted * q[:, d], n_groups)
    counts = np.stack([np.bincount(groups, base * x[:, i], n_groups) for i in range(origins)], axis=1)
    return Moments(gram, cross, counts)


def fit_rows(gram: FloatArray, cross: FloatArray, parent: FloatArray, penalty: FloatArray, *,
             tolerance: float = 1e-12, max_iterations: int = 200_000) -> tuple[FloatArray, np.ndarray]:
    """Exact block-coordinate descent over origin rows, vectorized across groups.

    Each row update minimizes an isotropic quadratic over the simplex, which is
    the Euclidean projection of its unconstrained minimizer. Iteration stops for
    a group when no probability changes by more than `tolerance` in a full
    sweep; that change equals the projected-gradient step, so a converged group
    satisfies the optimality conditions to the same tolerance. A row with no
    curvature (absent origin and zero penalty) takes its parent row.
    """
    n_groups, origins, _ = cross.shape
    result = parent.copy()
    iterations = np.zeros(n_groups, dtype=np.int64)
    curvature = np.einsum("gii->gi", gram) + penalty
    active = np.arange(n_groups)
    for iteration in range(1, max_iterations + 1):
        change = np.zeros(len(active))
        for i in range(origins):
            den = curvature[active, i]
            ok = den > DEGENERATE_CURVATURE
            current = result[active, i]
            interaction = np.einsum("gj,gjd->gd", gram[active, i], result[active]) - gram[active, i, i, None] * current
            target = cross[active, i] + penalty[active, i, None] * parent[active, i] - interaction
            row = parent[active, i].copy()
            if ok.any():
                row[ok] = project_simplex(target[ok] / den[ok, None])
            change = np.maximum(change, np.abs(row - current).max(axis=1))
            result[active, i] = row
        done = change <= tolerance
        iterations[active[done]] = iteration
        active = active[~done]
        if not len(active):
            return result, iterations
    raise ConvergenceError(f"{len(active)} groups did not converge in {max_iterations} sweeps")


@dataclass(frozen=True)
class HierarchyFit:
    national: FloatArray        # (origins, destinations)
    states: FloatArray          # (states, origins, destinations)
    municipalities: FloatArray  # (municipalities, origins, destinations)
    sweeps: dict[str, int]


def _prevalence(counts: FloatArray) -> FloatArray:
    return counts / np.maximum(counts.sum(axis=-1, keepdims=True), 1)


def fit_hierarchy(moments: Moments, municipality_state: ArrayLike, *, level: str,
                  state_penalty: float = 10_000.0, municipal_penalty: float | None = None,
                  tolerance: float = 1e-12) -> HierarchyFit:
    """National, state, and municipal matrices with prevalence-weighted shrinkage.

    `moments` are per municipality. The national matrix is unpenalized. State
    rows shrink toward it with penalty `state_penalty * q_i`, where q_i is the
    national prevalence of origin i (floored at 1e-7). Municipal rows shrink
    toward their state with `municipal_penalty * q_si`, the state prevalence
    of origin i floored at 1% of its floored national prevalence. `level` selects which matrices
    are applied to municipalities: "national", "state", or "municipal".
    """
    if level not in {"national", "state", "municipal"}:
        raise ValueError(f"Unknown level: {level}")
    if level == "municipal" and (municipal_penalty is None or municipal_penalty <= 0):
        raise ValueError("A municipal fit requires a positive municipal penalty")
    mapping = np.asarray(municipality_state)
    n_states = int(mapping.max()) + 1
    origins, destinations = moments.cross.shape[1:]
    total = moments.combine(np.zeros(len(mapping), dtype=np.int64), 1)
    uniform = np.full((1, origins, destinations), 1 / destinations)
    fitted, national_sweeps = fit_rows(total.gram, total.cross, uniform, np.zeros((1, origins)), tolerance=tolerance)
    national = fitted[0]
    q_national = np.maximum(_prevalence(total.counts)[0], PREVALENCE_FLOOR)
    states = moments.combine(mapping, n_states)
    state_parent = np.broadcast_to(national, (n_states, origins, destinations)).copy()
    state_weights = np.broadcast_to(state_penalty * q_national, (n_states, origins)).copy()
    state_fit, state_sweeps = fit_rows(states.gram, states.cross, state_parent, state_weights, tolerance=tolerance)
    sweeps = {"national": int(national_sweeps.max()), "state": int(state_sweeps.max()), "municipal": 0}
    if level == "national":
        municipal = np.broadcast_to(national, (len(mapping), origins, destinations)).copy()
    elif level == "state":
        municipal = state_fit[mapping].copy()
    else:
        q_state = np.maximum(_prevalence(states.counts), q_national * STATE_PREVALENCE_FRACTION)
        municipal, municipal_sweeps = fit_rows(moments.gram, moments.cross, state_fit[mapping],
                                               municipal_penalty * q_state[mapping], tolerance=tolerance)
        sweeps["municipal"] = int(municipal_sweeps.max())
    return HierarchyFit(national, state_fit, municipal, sweeps)


def predict_shares(x: FloatArray, n1: FloatArray, n2: FloatArray, matrices: FloatArray,
                   groups: ArrayLike) -> FloatArray:
    """Predicted second-round counts, scaling first-round shares to the second-round electorate."""
    return np.einsum("sk,skd->sd", x, matrices[np.asarray(groups)]) * (n2 / n1)[:, None]


def prediction_score(predicted: FloatArray, observed: FloatArray, n2: FloatArray) -> dict:
    """Electorate-weighted mean squared error of destination shares."""
    residual = (predicted - observed) / n2[:, None]
    squared = np.sum(n2[:, None] * residual**2, axis=0) / n2.sum()
    return {"rmsePercentagePoints": (100 * np.sqrt(squared)).tolist(), "meanSquaredError": float(squared.mean()),
            "sections": int(len(n2))}
