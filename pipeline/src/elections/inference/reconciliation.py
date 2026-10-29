"""Iterative proportional fitting and an explicit independent mobility bridge."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os

import numpy as np
from numpy.typing import ArrayLike

from .arrays import ConvergenceError, FloatArray, nonnegative_array, probabilities as _probabilities


@dataclass(frozen=True)
class ReconciledTable:
    table: FloatArray
    iterations: int
    max_margin_error: float


@dataclass(frozen=True)
class MobilityBridge:
    national: FloatArray
    by_origin_section: FloatArray
    leaving_by_origin: FloatArray
    arriving_by_destination: FloatArray
    pairing_lower: FloatArray
    pairing_upper: FloatArray


def reconcile_table(
    seed: ArrayLike,
    row_totals: ArrayLike,
    column_totals: ArrayLike,
    *,
    tolerance: float = 1e-8,
    max_iterations: int = 20_000,
) -> ReconciledTable:
    """Fit both margins while preserving seed zeros as structural zeros.

    Impossible support is rejected when immediately detectable; other failures
    raise ConvergenceError rather than returning a misleading reconciled table.
    IPF is an accounting step, not validation of individual behavior.
    """
    table = nonnegative_array(seed, "seed", 2).copy()
    rows = nonnegative_array(row_totals, "row_totals", 1)
    columns = nonnegative_array(column_totals, "column_totals", 1)
    if table.shape != (len(rows), len(columns)):
        raise ValueError("seed shape must match both margins")
    if not np.isfinite(tolerance) or tolerance <= 0 or max_iterations < 1:
        raise ValueError("tolerance and max_iterations must be positive")
    if not np.isclose(rows.sum(), columns.sum(), rtol=0, atol=tolerance):
        raise ValueError("row and column totals must have equal mass")
    table[rows == 0, :] = 0
    table[:, columns == 0] = 0
    if rows.sum() == 0:
        return ReconciledTable(np.zeros_like(table), 0, 0.0)
    if np.any((rows > 0) & (table.sum(axis=1) == 0)) or np.any((columns > 0) & (table.sum(axis=0) == 0)):
        raise ValueError("positive margin has no supported seed cells")
    error = np.inf
    for iteration in range(1, max_iterations + 1):
        column_mass = table.sum(axis=0)
        table *= np.divide(columns, column_mass, out=np.zeros_like(columns), where=column_mass > 0)[None, :]
        row_mass = table.sum(axis=1)
        table *= np.divide(rows, row_mass, out=np.zeros_like(rows), where=row_mass > 0)[:, None]
        error = float(max(np.max(np.abs(table.sum(axis=1) - rows)), np.max(np.abs(table.sum(axis=0) - columns))))
        if error <= tolerance:
            return ReconciledTable(table, iteration, error)
    raise ConvergenceError(f"IPF did not converge in {max_iterations} iterations; margin error={error:g}")


def reconcile_section(
    origins: ArrayLike,
    destinations: ArrayLike,
    probabilities: ArrayLike,
    *,
    incoming: float = 0,
    outgoing: float = 0,
    probability_floor: float = 1e-4,
    tolerance: float = 1e-8,
    max_iterations: int = 20_000,
) -> ReconciledTable:
    """Reconcile a section including incoming and outgoing cohort margins.

    The final row represents incoming voters, the final column outgoing voters.
    Their intersection is structurally zero. A positive probability floor is an
    explicit seed assumption and must be included in sensitivity analysis.
    """
    x = nonnegative_array(origins, "origins", 1)
    y = nonnegative_array(destinations, "destinations", 1)
    p = _probabilities(probabilities, (len(x), len(y)), "probabilities")
    if not np.isfinite([incoming, outgoing, probability_floor]).all() or min(incoming, outgoing, probability_floor) < 0:
        raise ValueError("mobility counts and probability floor must be finite and nonnegative")
    if incoming > y.sum() or outgoing > x.sum():
        raise ValueError("incoming/outgoing counts cannot exceed their respective cohort")
    if not np.isclose(x.sum() + incoming, y.sum() + outgoing, rtol=0, atol=tolerance):
        raise ValueError("section margins and mobility counts do not balance")
    seed = np.zeros((len(x) + 1, len(y) + 1))
    seed[:-1, :-1] = x[:, None] * np.maximum(p, probability_floor)
    if x.sum() > 0:
        seed[:-1, -1] = x * outgoing / x.sum()
    seed[-1, :-1] = incoming * (y + 0.5) / (y.sum() + len(y) * 0.5)
    return reconcile_table(seed, np.append(x, incoming), np.append(y, outgoing), tolerance=tolerance, max_iterations=max_iterations)


def bridge_mobility(section_tables: ArrayLike, *, tolerance: float = 1e-6) -> MobilityBridge:
    """Pair leavers and entrants independently, retaining origin geography.

    Pairing bounds vary only the pairing of the already fitted mobile margins.
    They are not unconditional identification bounds for all electoral flows.
    """
    if not np.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    tables = nonnegative_array(section_tables, "section_tables", 3)
    if min(tables.shape[1:]) < 2:
        raise ValueError("each table needs substantive and mobility margins")
    if np.any(tables[:, -1, -1] != 0):
        raise ValueError("incoming-to-outgoing cells must remain structural zeros")
    leaving = tables[:, :-1, -1].sum(axis=0)
    arriving = tables[:, -1, :-1].sum(axis=0)
    if not np.isclose(leaving.sum(), arriving.sum(), rtol=0, atol=tolerance):
        raise ValueError("national incoming and outgoing margins must balance")
    direct = tables[:, :-1, :-1]
    movers = float(leaving.sum())
    if movers > 0:
        by_section = direct + tables[:, :-1, -1, None] * (arriving / movers)[None, None, :]
    else:
        by_section = direct.copy()
    direct_national = direct.sum(axis=0)
    lower = direct_national + np.maximum(0, leaving[:, None] + arriving[None, :] - movers)
    upper = direct_national + np.minimum(leaving[:, None], arriving[None, :])
    return MobilityBridge(by_section.sum(axis=0), by_section, leaving, arriving, lower, upper)


@dataclass(frozen=True)
class SectionFlows:
    """Reconciled section tables summed into reporting groups.

    `direct` holds voters who stay in their section; `leaving` holds first-round
    origins of voters who leave it, still attributed to the origin geography;
    `arriving` holds second-round destinations of entrants.
    """

    direct: FloatArray     # (groups, origins, destinations)
    leaving: FloatArray    # (groups, origins)
    arriving: FloatArray   # (groups, destinations)
    max_margin_error: float
    max_iterations: int

    def bridged(self) -> FloatArray:
        """Pair leavers with entrants independently of origin and destination nationally.

        The pairing assigns each leaver the national destination distribution of
        entrants. It preserves origin rows and national destinations. It is an
        explicit assumption; it assumes no persistence among movers.
        """
        movers = self.leaving.sum()
        if abs(self.arriving.sum() - movers) > 1e-3 + 1e-6 * movers:
            raise ValueError("Leavers and entrants must balance nationally before pairing")
        if movers <= 0:
            return self.direct.copy()
        destination_shares = self.arriving.sum(axis=0) / movers
        return self.direct + self.leaving[:, :, None] * destination_shares[None, None, :]


def _reconcile_chunk(x, y, n1, n2, incoming, outgoing, seeds, probability_floor, tolerance, max_iterations):
    count, origins, destinations = len(x), x.shape[1], y.shape[1]
    table = np.zeros((count, origins + 1, destinations + 1))
    table[:, :origins, :destinations] = x[:, :, None] * np.maximum(probability_floor, seeds)
    table[:, :origins, destinations] = x * (outgoing / n1)[:, None]
    table[:, origins, :destinations] = incoming[:, None] * (y + 0.5) / (n2 + destinations * 0.5)[:, None]
    work_rows = np.column_stack([x, incoming])
    work_columns = np.column_stack([y, outgoing])
    active, work = np.arange(count), table
    worst_error, worst_iterations = 0.0, 0
    for iteration in range(1, max_iterations + 1):
        total = work.sum(axis=1)
        work *= np.divide(work_columns, total, out=np.zeros_like(total), where=total > 0)[:, None, :]
        total = work.sum(axis=2)
        work *= np.divide(work_rows, total, out=np.zeros_like(total), where=total > 0)[:, :, None]
        error = np.abs(work.sum(axis=1) - work_columns).max(axis=1)
        done = error <= tolerance
        if done.any():
            table[active[done]] = work[done]
            worst_error = max(worst_error, float(error[done].max()))
            worst_iterations = iteration
            active, work = active[~done], work[~done]
            work_rows, work_columns = work_rows[~done], work_columns[~done]
        if not len(active):
            return table, worst_error, worst_iterations
    raise ConvergenceError(f"IPF did not converge for {len(active)} sections in {max_iterations} iterations; "
                           f"largest margin error {float(error.max()):g}")


def reconcile_sections(x: FloatArray, y: FloatArray, n1: FloatArray, n2: FloatArray, incoming: FloatArray,
                       outgoing: FloatArray, matrices: FloatArray, model_group: np.ndarray,
                       report_group: np.ndarray, n_report: int, *, probability_floor: float = 1e-4,
                       tolerance: float = 1e-6, max_iterations: int = 2_000_000,
                       chunk: int = 20_000, workers: int | None = None) -> SectionFlows:
    """IPF for every section, seeded by its model matrix, then summed by report group.

    Each section table has origins plus one incoming row and destinations plus one
    outgoing column; the incoming-outgoing cell is structurally zero. Seeds are
    origin counts times model probabilities floored at `probability_floor`;
    leavers are proportional to origins and entrants follow the section's
    second-round shares with a half-vote smoothing. Each section iterates until
    the largest column-margin error after row scaling is at most `tolerance`
    votes; failure raises ConvergenceError. Chunks run in threads and are summed
    in a fixed order, so results do not depend on the number of workers.
    """
    origins, destinations = x.shape[1], y.shape[1]
    starts = range(0, len(x), chunk)

    def run(start: int):
        part = slice(start, min(start + chunk, len(x)))
        return _reconcile_chunk(x[part], y[part], n1[part], n2[part], incoming[part], outgoing[part],
                                matrices[model_group[part]], probability_floor, tolerance, max_iterations)

    with ThreadPoolExecutor(max_workers=workers or os.cpu_count() or 1) as pool:
        outputs = list(pool.map(run, starts))
    direct = np.zeros((n_report, origins, destinations))
    leaving = np.zeros((n_report, origins))
    arriving = np.zeros((n_report, destinations))
    for start, (table, _, _) in zip(starts, outputs):
        groups = report_group[start:start + chunk]
        np.add.at(direct, groups, table[:, :origins, :destinations])
        np.add.at(leaving, groups, table[:, :origins, destinations])
        np.add.at(arriving, groups, table[:, origins, :destinations])
    return SectionFlows(direct, leaving, arriving, max(output[1] for output in outputs),
                        max(output[2] for output in outputs))
