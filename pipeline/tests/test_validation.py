"""Scientific contract failures, including misleading denominator changes."""
import copy
import unittest

from elections.validation import validate_flow_row, validate_partition, validate_probability_matrix


def row(observed=100, values=(30, 40, 10, 5, 15)):
    return {"originId": "blank", "observed": observed,
            "estimated": dict(zip(["lula", "flavio", "blank", "null", "abstention"], values)),
            "sensitivity": None}


class ContractAccountingTests(unittest.TestCase):
    def test_invalid_tolerances_cannot_disable_accounting(self):
        for tolerance in [float("nan"), float("inf"), -1, 0, True]:
            with self.assertRaises(ValueError): validate_flow_row(row(), tolerance=tolerance)
            with self.assertRaises(ValueError): validate_probability_matrix([[1.0]], tolerance=tolerance)

    def test_missing_destination_and_finalist_renormalization_are_rejected(self):
        validate_flow_row(row())
        incomplete = row(); del incomplete["estimated"]["abstention"]
        with self.assertRaises(ValueError): validate_flow_row(incomplete)
        wrong = row(); wrong["observed"] = 70
        with self.assertRaises(ValueError): validate_flow_row(wrong)

    def test_nonfinite_negative_and_boolean_counts_are_rejected(self):
        for value in [float("nan"), float("inf"), -1, True]:
            invalid = row(); invalid["estimated"]["lula"] = value
            with self.assertRaises(ValueError): validate_flow_row(invalid)
        validate_flow_row(row(0, (0, 0, 0, 0, 0)))
        with self.assertRaises(ValueError): validate_flow_row(row(0, (0.0001, 0, 0, 0, 0)))

    def test_sensitivity_must_contain_point_but_is_not_aggregated(self):
        parent = row(); parent["sensitivity"] = {"lula": {"min": 25, "max": 35}, "flavio": {"min": 35, "max": 45}}
        validate_flow_row(parent)
        invalid = copy.deepcopy(parent); invalid["sensitivity"]["lula"]["max"] = 29
        with self.assertRaises(ValueError): validate_flow_row(invalid)
        children = [[row(40, (10, 15, 5, 4, 6))], [row(60, (20, 25, 5, 1, 9))]]
        # Different scenario extrema need not add to the parent's extrema.
        children[0][0]["sensitivity"] = {"lula": {"min": 0, "max": 40}, "flavio": {"min": 0, "max": 40}}
        validate_partition([parent], children)

    def test_partition_detects_missing_residual_and_duplicate_origin(self):
        first = row(40, (10, 15, 5, 4, 6)); second = row(60, (20, 25, 5, 1, 9))
        validate_partition([row()], [[first], [second]])
        with self.assertRaises(ValueError): validate_partition([row()], [[first]])
        with self.assertRaises(ValueError): validate_partition([row(), row()], [[first], [second]])
        with self.assertRaises(ValueError): validate_partition([row()], [])

    def test_probability_matrix_requires_five_or_other_explicit_destinations_to_sum_to_one(self):
        validate_probability_matrix([[0.3, 0.4, 0.1, 0.05, 0.15]])
        with self.assertRaises(ValueError): validate_probability_matrix([[0.3, 0.4]])
        with self.assertRaises(ValueError): validate_probability_matrix([[0.7, -0.1, 0.4]])


if __name__ == "__main__":
    unittest.main()
