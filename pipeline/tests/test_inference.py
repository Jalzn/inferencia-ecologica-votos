"""Independent optimization, accounting, and non-identification regressions."""
import unittest

import numpy as np
from scipy.optimize import minimize

from elections.inference import (
    ConvergenceError,
    bridge_mobility,
    fit_hierarchy,
    fit_rows,
    grouped_section_bounds,
    linear_contrast_bounds,
    mobility_bounds,
    national_bounds,
    predict_shares,
    project_simplex,
    reconcile_section,
    reconcile_sections,
    reconcile_table,
    section_bounds,
    section_moments,
)


def contextual_counterexample() -> dict[str, np.ndarray]:
    """Return two nonnegative individual-flow worlds with identical margins.

    These are synthetic expected counts, not evidence about actual voters.
    The homogeneous world follows a fixed 70/30 transition matrix; a contextual
    circulation changes transitions while preserving every observed margin.
    """
    first_origin = np.tile(np.arange(300, 701, 10, dtype=float), 6)
    origins = np.column_stack([first_origin, 1000 - first_origin])
    probabilities = np.array([[0.7, 0.3], [0.3, 0.7]])
    homogeneous = origins[:, :, None] * probabilities[None, :, :]
    contextual = homogeneous.copy()
    circulation = np.rint(0.4 * origins[:, 0] * origins[:, 1] / origins.sum(axis=1))
    contextual[:, 0, 0] += circulation
    contextual[:, 1, 1] += circulation
    contextual[:, 0, 1] -= circulation
    contextual[:, 1, 0] -= circulation
    return {"origins": origins, "destinations": homogeneous.sum(axis=1),
            "homogeneous": homogeneous, "contextual": contextual}


def random_sections(random, sections, origins, destinations, size=400):
    x = random.dirichlet(np.ones(origins), sections) * size
    y = random.dirichlet(np.ones(destinations), sections) * size
    return x, y, x.sum(axis=1), y.sum(axis=1)


class EstimatorTests(unittest.TestCase):
    def test_row_solver_matches_independent_optimizer(self):
        random = np.random.default_rng(42)
        x, y, n1, n2 = random_sections(random, 240, 4, 5)
        groups = np.arange(240) % 3
        moments = section_moments(x, y, n1, n2, groups, 3, weights=random.uniform(0.2, 2, 240))
        parent = random.dirichlet(np.ones(5), (3, 4))
        penalty = random.uniform(0, 30, (3, 4))
        fitted, sweeps = fit_rows(moments.gram, moments.cross, parent, penalty)
        self.assertTrue((sweeps > 0).all())
        for g in range(3):
            gram, cross = moments.gram[g], moments.cross[g]

            def objective(flat, g=g, gram=gram, cross=cross):
                matrix = flat.reshape(4, 5)
                return (np.sum(matrix * (gram @ matrix)) - 2 * np.sum(cross * matrix)
                        + np.sum(penalty[g, :, None] * (matrix - parent[g])**2))

            reference = minimize(objective, parent[g].ravel(), method="SLSQP", bounds=[(0, 1)] * 20,
                                 constraints={"type": "eq", "fun": lambda flat: flat.reshape(4, 5).sum(axis=1) - 1},
                                 options={"ftol": 1e-14, "maxiter": 5000})
            self.assertTrue(reference.success, reference.message)
            self.assertLessEqual(objective(fitted[g].ravel()), reference.fun + 1e-9)
            np.testing.assert_allclose(fitted[g], reference.x.reshape(4, 5), atol=1e-5)
        np.testing.assert_allclose(fitted.sum(axis=2), 1, atol=1e-12)

    def test_weighted_moments_equal_explicit_sums(self):
        random = np.random.default_rng(5)
        x, y, n1, n2 = random_sections(random, 30, 3, 4)
        weights = random.uniform(0, 2, 30)
        moments = section_moments(x, y, n1, n2, np.zeros(30, dtype=int), 1, weights)
        p, q, w = x / n1[:, None], y / n2[:, None], weights * n2
        np.testing.assert_allclose(moments.gram[0], (p * w[:, None]).T @ p)
        np.testing.assert_allclose(moments.cross[0], (p * w[:, None]).T @ q)
        np.testing.assert_allclose(moments.counts[0], (x * weights[:, None]).sum(axis=0))

    def test_homogeneous_generator_is_recovered_and_absent_origin_borrows_parent(self):
        random = np.random.default_rng(19)
        x = np.column_stack([random.dirichlet(np.ones(3), 100) * 600, np.zeros(100)])
        truth = random.dirichlet(np.ones(5), 4)
        y = x @ truth
        moments = section_moments(x, y, x.sum(axis=1), y.sum(axis=1), np.zeros(100, dtype=int), 1)
        parent = random.dirichlet(np.ones(5), (1, 4))
        fitted, _ = fit_rows(moments.gram, moments.cross, parent, np.zeros((1, 4)))
        np.testing.assert_allclose(fitted[0, :3], truth[:3], atol=1e-7)
        np.testing.assert_array_equal(fitted[0, 3], parent[0, 3])

    def test_hierarchy_levels_use_explicit_parents_and_prevalence_penalties(self):
        random = np.random.default_rng(190)
        x, y, n1, n2 = random_sections(random, 300, 3, 5)
        municipality = np.repeat(np.arange(5), 60)
        municipality_state = np.array([0, 0, 1, 1, 1])
        moments = section_moments(x, y, n1, n2, municipality, 5)
        fit = fit_hierarchy(moments, municipality_state, level="municipal", state_penalty=50, municipal_penalty=300)
        total = moments.counts.sum(axis=0)
        national, _ = fit_rows(moments.gram.sum(0)[None], moments.cross.sum(0)[None], np.full((1, 3, 5), 0.2), np.zeros((1, 3)))
        np.testing.assert_allclose(fit.national, national[0], atol=1e-10)
        state_counts = np.stack([moments.counts[municipality_state == s].sum(axis=0) for s in range(2)])
        q_national = total / total.sum()
        for s in range(2):
            members = municipality_state == s
            expected, _ = fit_rows(moments.gram[members].sum(0)[None], moments.cross[members].sum(0)[None],
                                   fit.national[None], 50 * q_national[None])
            np.testing.assert_allclose(fit.states[s], expected[0], atol=1e-10)
        for m in range(5):
            s = municipality_state[m]
            q_state = np.maximum(state_counts[s] / state_counts[s].sum(), q_national * 0.01)
            expected, _ = fit_rows(moments.gram[m][None], moments.cross[m][None], fit.states[s][None], 300 * q_state[None])
            np.testing.assert_allclose(fit.municipalities[m], expected[0], atol=1e-10)
        state_only = fit_hierarchy(moments, municipality_state, level="state", state_penalty=50)
        np.testing.assert_allclose(state_only.municipalities, state_only.states[municipality_state])
        national_only = fit_hierarchy(moments, municipality_state, level="national")
        np.testing.assert_allclose(national_only.municipalities, np.broadcast_to(national_only.national, (5, 3, 5)))
        with self.assertRaises(ValueError):
            fit_hierarchy(moments, municipality_state, level="municipal")

    def test_perfect_aggregate_prediction_does_not_recover_contextual_flows(self):
        case = contextual_counterexample()
        np.testing.assert_allclose(case["homogeneous"].sum(axis=1), case["contextual"].sum(axis=1))
        np.testing.assert_allclose(case["homogeneous"].sum(axis=2), case["contextual"].sum(axis=2))
        self.assertTrue((case["contextual"] >= 0).all())
        x, y = case["origins"], case["destinations"]
        n = x.sum(axis=1)
        train = np.arange(len(x)) % 5 != 0
        moments = section_moments(x, y, n, n, np.zeros(len(x), dtype=int), 1, train.astype(float))
        fitted, _ = fit_rows(moments.gram, moments.cross, np.full((1, 2, 2), 0.5), np.zeros((1, 2)))
        prediction = predict_shares(x[~train], n[~train], n[~train], fitted, np.zeros((~train).sum(), dtype=int))
        np.testing.assert_allclose(prediction, y[~train], atol=1e-6)
        true_share = case["contextual"][:, 0, 0].sum() / x[:, 0].sum()
        self.assertGreater(abs(true_share - fitted[0, 0, 0]), 0.18)

    def test_simplex_projection_and_iteration_failure_are_explicit(self):
        projected = project_simplex(np.array([[0.2, 0.9, -0.3], [5.0, 5, 5]]))
        np.testing.assert_allclose(projected, [[0.15, 0.85, 0], [1 / 3, 1 / 3, 1 / 3]])
        with self.assertRaises(ValueError):
            project_simplex(np.array([1.0, np.nan]))
        random = np.random.default_rng(3)
        x, y, n1, n2 = random_sections(random, 20, 3, 3)
        moments = section_moments(x, y, n1, n2, np.zeros(20, dtype=int), 1)
        with self.assertRaises(ConvergenceError):
            fit_rows(moments.gram, moments.cross, np.full((1, 3, 3), 1 / 3), np.zeros((1, 3)), max_iterations=1)


class ReconciliationTests(unittest.TestCase):
    def test_ipf_preserves_zero_margins_and_supported_odds_ratio(self):
        seed = np.array([[2.0, 3, 0], [4, 7, 0], [0, 0, 0]])
        fit = reconcile_table(seed, [40, 60, 0], [55, 45, 0])
        np.testing.assert_allclose(fit.table.sum(axis=1), [40, 60, 0], atol=1e-8)
        np.testing.assert_allclose(fit.table.sum(axis=0), [55, 45, 0], atol=1e-8)
        self.assertAlmostEqual(fit.table[0, 0] * fit.table[1, 1] / (fit.table[0, 1] * fit.table[1, 0]), 14 / 12)
        np.testing.assert_array_equal(fit.table[:, 2], 0)
        np.testing.assert_array_equal(fit.table[2], 0)

    def test_mobility_bridge_retains_origin_geography(self):
        tables = np.array([[[30.0, 10, 10], [5, 35, 10], [0, 0, 0]],
                           [[10.0, 20, 0], [20, 30, 0], [15, 5, 0]]])
        result = bridge_mobility(tables)
        expected = np.array([[[37.5, 12.5], [12.5, 37.5]], [[10, 20], [20, 30]]])
        np.testing.assert_allclose(result.by_origin_section, expected)
        np.testing.assert_allclose(result.by_origin_section.sum(axis=2), tables[:, :-1, :].sum(axis=2))
        np.testing.assert_allclose(result.national.sum(axis=0), tables[:, :, :-1].sum(axis=(0, 1)))
        self.assertFalse(np.allclose(result.by_origin_section.sum(axis=1), tables[:, :, :-1].sum(axis=1)))
        self.assertTrue((result.national >= result.pairing_lower).all())
        self.assertTrue((result.national <= result.pairing_upper).all())

    def test_section_reconciliation_has_five_destinations_and_structural_zero(self):
        x = [100.0, 60, 40]
        y = [70.0, 90, 15, 10, 20]
        probabilities = np.array([[1, 0, 0, 0, 0], [0, 1, 0, 0, 0], [0, 0, 0.2, 0.3, 0.5]])
        result = reconcile_section(x, y, probabilities, incoming=10, outgoing=5)
        self.assertEqual(result.table.shape, (4, 6))
        self.assertEqual(result.table[-1, -1], 0)
        np.testing.assert_allclose(result.table.sum(axis=1), x + [10], atol=1e-8)
        np.testing.assert_allclose(result.table.sum(axis=0), y + [5], atol=1e-8)

    def test_impossible_support_and_imbalanced_cohorts_fail(self):
        with self.assertRaises(ValueError):
            reconcile_table([[1, 0], [1, 0]], [50, 50], [50, 50])
        with self.assertRaises(ConvergenceError):
            reconcile_table(np.eye(2), [60, 40], [50, 50], max_iterations=5)
        with self.assertRaises(ValueError):
            reconcile_table(np.ones((2, 2)), [60, 40], [50, 51])
        with self.assertRaises(ValueError):
            reconcile_section([100], [110], [[1]], incoming=0, outgoing=0)


class SectionReconciliationTests(unittest.TestCase):
    def test_vectorized_sections_match_individual_reconciliation(self):
        random = np.random.default_rng(77)
        sections, origins, destinations = 40, 4, 5
        x = random.integers(5, 80, (sections, origins)).astype(float)
        n1 = x.sum(axis=1)
        outgoing = np.minimum(random.integers(0, 6, sections), n1 - 1).astype(float)
        incoming = random.permutation(outgoing)  # national movers balance, as in a closed cohort
        n2 = n1 + incoming - outgoing
        y = np.array([random.multinomial(int(total), random.dirichlet(np.ones(destinations))) for total in n2], dtype=float)
        matrices = random.dirichlet(np.ones(destinations), (3, origins))
        model_group = random.integers(0, 3, sections)
        report_group = np.arange(sections) % 4
        result = reconcile_sections(x, y, n1, n2, incoming, outgoing, matrices, model_group, report_group, 4, chunk=7)
        direct = np.zeros((4, origins, destinations)); leaving = np.zeros((4, origins)); arriving = np.zeros((4, destinations))
        for s in range(sections):
            table = reconcile_section(x[s], y[s], matrices[model_group[s]], incoming=incoming[s], outgoing=outgoing[s]).table
            direct[report_group[s]] += table[:-1, :-1]
            leaving[report_group[s]] += table[:-1, -1]
            arriving[report_group[s]] += table[-1, :-1]
        np.testing.assert_allclose(result.direct, direct, atol=1e-4)
        np.testing.assert_allclose(result.leaving, leaving, atol=1e-4)
        np.testing.assert_allclose(result.arriving, arriving, atol=1e-4)
        self.assertLessEqual(result.max_margin_error, 1e-6)
        bridged = result.bridged()
        observed = np.zeros((4, origins)); np.add.at(observed, report_group, x)
        np.testing.assert_allclose(bridged.sum(axis=2), observed, atol=1e-6)
        np.testing.assert_allclose(bridged.sum(axis=(0, 1)), y.sum(axis=0), atol=1e-4)

    def test_unconverged_sections_raise(self):
        x = np.array([[60.0, 40]]); y = np.array([[50.0, 50]])
        with self.assertRaises(ConvergenceError):
            reconcile_sections(x, y, x.sum(1), y.sum(1), np.zeros(1), np.zeros(1), np.array([[[0.99, 0.01], [0.01, 0.99]]]),
                               np.zeros(1, dtype=int), np.zeros(1, dtype=int), 1, max_iterations=1)


class IdentificationTests(unittest.TestCase):
    def test_grouped_bounds_contain_true_flows_of_mobile_cohorts(self):
        random = np.random.default_rng(31)
        for _ in range(20):
            size, sections, origins, destinations = 600, 9, 4, 5
            first = random.integers(sections, size=size)
            second = first.copy(); moving = random.random(size) < 0.1
            second[moving] = random.integers(sections, size=moving.sum())
            origin = random.integers(origins, size=size); destination = random.integers(destinations, size=size)
            x = np.zeros((sections, origins)); y = np.zeros((sections, destinations))
            np.add.at(x, (first, origin), 1); np.add.at(y, (second, destination), 1)
            n1, n2 = x.sum(axis=1), y.sum(axis=1)
            delta = n2 - n1
            groups = np.arange(sections) % 3
            truth = np.zeros((3, origins, destinations)); np.add.at(truth, (groups[first], origin, destination), 1)
            # The net change is the minimum movement; true movement is larger, so use the actual counts here.
            incoming = np.bincount(second[first != second], minlength=sections).astype(float)
            outgoing = np.bincount(first[first != second], minlength=sections).astype(float)
            bounds = grouped_section_bounds(x, y, incoming, outgoing, groups, 3)
            self.assertTrue((bounds.lower <= truth).all()); self.assertTrue((truth <= bounds.upper).all())
            self.assertTrue(np.allclose(incoming - outgoing, delta))
            lower, upper = mobility_bounds(x, y, incoming, outgoing)
            frechet_lower, frechet_upper = national_bounds(x.sum(axis=0), y.sum(axis=0))
            np.testing.assert_allclose(np.maximum(bounds.lower.sum(axis=0), frechet_lower), lower)
            self.assertTrue((np.minimum(bounds.upper.sum(axis=0), frechet_upper) <= upper + 1e-9).all())


    def test_cell_bounds_match_independent_transport_optimization(self):
        random = np.random.default_rng(2026)
        for _ in range(6):
            truth = random.integers(0, 20, (3, 5)).astype(float)
            x, y = truth.sum(axis=1), truth.sum(axis=0)
            lower, upper = national_bounds(x, y)
            for i in range(3):
                for j in range(5):
                    contrast = np.zeros((3, 5)); contrast[i, j] = 1
                    bound = linear_contrast_bounds(x, y, contrast)
                    self.assertAlmostEqual(bound.minimum, lower[i, j])
                    self.assertAlmostEqual(bound.maximum, upper[i, j])

    def test_joint_contrast_witnesses_preserve_margins(self):
        x, y = np.array([30.0, 70]), np.array([40.0, 40, 5, 5, 10])
        contrast = np.zeros((2, 5)); contrast[0, 0] = 1; contrast[0, 1] = -1
        result = linear_contrast_bounds(x, y, contrast)
        self.assertAlmostEqual(result.minimum, -30)
        self.assertAlmostEqual(result.maximum, 30)
        for witness in [result.minimum_table, result.maximum_table]:
            np.testing.assert_allclose(witness.sum(axis=1), x)
            np.testing.assert_allclose(witness.sum(axis=0), y)
            self.assertTrue((witness >= 0).all())

    def test_mobile_individual_cohort_lies_within_conservative_bounds(self):
        random = np.random.default_rng(9723)
        for _ in range(20):
            size, sections, origins, destinations = 400, 7, 4, 5
            first = random.integers(sections, size=size)
            second = first.copy(); moving = random.random(size) < 0.2
            second[moving] = random.integers(sections, size=moving.sum())
            origin = random.integers(origins, size=size); destination = random.integers(destinations, size=size)
            x = np.zeros((sections, origins)); y = np.zeros((sections, destinations)); truth = np.zeros((origins, destinations))
            np.add.at(x, (first, origin), 1); np.add.at(y, (second, destination), 1)
            np.add.at(truth, (origin, destination), 1)
            incoming = np.bincount(second[first != second], minlength=sections)
            outgoing = np.bincount(first[first != second], minlength=sections)
            lower, upper = mobility_bounds(x, y, incoming, outgoing)
            self.assertTrue((lower <= truth).all()); self.assertTrue((truth <= upper).all())

    def test_zero_margins_and_invalid_fixed_cohort(self):
        lower, upper = national_bounds([0, 0], [0, 0, 0, 0, 0])
        np.testing.assert_array_equal(lower, upper)
        np.testing.assert_array_equal(lower, 0)
        with self.assertRaises(ValueError):
            national_bounds([100_000_000, 58_745_079], [100_000_000, 58_745_078])
        with self.assertRaises(ValueError):
            section_bounds([[30, 20]], [[40, 20]])


if __name__ == "__main__":
    unittest.main()
