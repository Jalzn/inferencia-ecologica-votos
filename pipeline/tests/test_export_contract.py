"""Release regression checks using the small versioned real-data fixture (schema 2.0)."""
from __future__ import annotations

from copy import deepcopy
import json
import shutil
from pathlib import Path
import tempfile
import unittest

import numpy as np

from elections.export.release import flow_rows, write_resource
from elections.export.verify import read_resource, safe_resource_path, validate_bundle, validate_release, validate_rows
from elections.taxonomy import DESTINATION_IDS, ORIGIN_IDS

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data/fixtures/public"


class ExportContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((FIXTURE / "manifest.json").read_text())
        cls.national = read_resource(FIXTURE, cls.manifest["resources"]["national"])
        cls.state = read_resource(FIXTURE, cls.manifest["resources"]["states"]["MG"])

    def test_fixture_has_real_totals_and_all_raw_origins(self):
        place = self.national["place"]
        self.assertEqual(place["electorate"], 158745079)
        self.assertEqual([row["originId"] for row in place["rows"]], list(ORIGIN_IDS))
        self.assertEqual(place["rows"][2]["observed"], 3448569)
        self.assertEqual(self.manifest["scope"], "fixture")
        self.assertEqual(self.manifest["model"]["scenarioCount"], 12)
        self.assertTrue(self.manifest["model"]["sensitivityDescription"])
        self.assertEqual(set(self.manifest["resources"]["states"]), {"MG"})
        self.assertEqual(len(self.state["children"]), 853)
        self.assertTrue(validate_release(FIXTURE, deep_schema=True)["ok"])

    def test_fixture_cannot_be_published_as_production(self):
        with self.assertRaisesRegex(ValueError, "full release"):
            validate_release(FIXTURE, require_full=True)

    def test_compressed_resources_use_binary_suffix_for_byte_integrity(self):
        descriptor = self.manifest["resources"]["states"]["MG"]
        self.assertEqual(descriptor["encoding"], "gzip")
        self.assertTrue(descriptor["path"].endswith(".json.bin"))
        invalid = deepcopy(descriptor)
        invalid["path"] = invalid["path"].replace(".json.bin", ".json.gz")
        with self.assertRaisesRegex(ValueError, "transport byte integrity"):
            read_resource(FIXTURE, invalid)

    def test_missing_municipality_breaks_partition_conservation(self):
        broken = deepcopy(self.state)
        removed = broken["children"].pop()
        broken["geometry"]["municipalities"]["features"] = [
            feature for feature in broken["geometry"]["municipalities"]["features"] if feature["id"] != removed["id"]]
        with self.assertRaisesRegex(ValueError, "Partition"):
            validate_bundle(broken)

    def test_zero_origin_and_missing_destination_are_distinct_failures(self):
        rows = deepcopy(self.state["place"]["rows"])
        rows[0]["observed"] = 0
        rows[0]["estimated"] = dict.fromkeys(DESTINATION_IDS, 0)
        rows[0]["estimated"]["lula"] = 0.000001
        with self.assertRaisesRegex(ValueError, "Zero observed"):
            validate_rows(rows)
        rows = deepcopy(self.state["place"]["rows"])
        del rows[0]["estimated"]["abstention"]
        with self.assertRaisesRegex(ValueError, "five"):
            validate_rows(rows)

    def test_resource_path_cannot_escape_release(self):
        for value in ["../manifest.json", "/etc/passwd", "https://example.com/a", "%2e%2e/x", "state.json?query"]:
            with self.assertRaises(ValueError, msg=value):
                safe_resource_path(FIXTURE, value)

    def test_integrity_check_detects_corrupted_bytes(self):
        descriptor = deepcopy(self.manifest["resources"]["national"])
        descriptor["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "integrity"):
            read_resource(FIXTURE, descriptor)

    def test_point_estimate_must_belong_to_sensitivity_and_bounds(self):
        broken = deepcopy(self.state)
        broken["place"]["rows"][2]["sensitivity"]["lula"] = {"min": 0, "max": 1}
        with self.assertRaisesRegex(ValueError, "outside its sensitivity"):
            validate_bundle(broken, schema=True)
        broken = deepcopy(self.state)
        broken["place"]["rows"][2]["identificationBounds"]["flavio"] = {"min": 0, "max": 1}
        with self.assertRaisesRegex(ValueError, "outside its identificationBounds"):
            validate_bundle(broken, schema=True)

    def test_sensitivity_range_must_lie_within_identification_bounds(self):
        broken = deepcopy(self.state)
        row = broken["place"]["rows"][2]
        row["identificationBounds"]["lula"]["max"] = row["sensitivity"]["lula"]["max"] - 1
        row["identificationBounds"]["lula"]["max"] = max(row["identificationBounds"]["lula"]["max"], row["estimated"]["lula"])
        with self.assertRaisesRegex(ValueError, "exceeds identification bounds"):
            validate_rows(broken["place"]["rows"])

    def test_every_row_has_identification_bounds(self):
        broken = deepcopy(self.state)
        del broken["children"][0]["rows"][3]["identificationBounds"]
        with self.assertRaisesRegex(ValueError, "identification bounds"):
            validate_bundle(broken)

    def test_geometry_must_match_a_child(self):
        broken = deepcopy(self.state)
        broken["geometry"]["municipalities"]["features"][0]["properties"]["id"] = "MG:00000"
        with self.assertRaisesRegex(ValueError, "Geometry"):
            validate_bundle(broken)

    def test_self_consistent_state_cannot_disagree_with_national_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / "release"
            shutil.copytree(FIXTURE, release)
            manifest = deepcopy(self.manifest)
            broken = deepcopy(self.state)
            for place in [broken["place"], *broken["children"]]:
                place["electorate"] *= 2
                place["sectionCount"] *= 2
                for row in place["rows"]:
                    row["observed"] *= 2
                    row["estimated"] = {key: value * 2 for key, value in row["estimated"].items()}
                    for field in ["sensitivity", "identificationBounds"]:
                        row[field] = {key: {bound: value * 2 for bound, value in interval.items()}
                                      for key, interval in row[field].items()}
            descriptor = manifest["resources"]["states"]["MG"]
            manifest["resources"]["states"]["MG"] = write_resource(release, descriptor["path"], broken, True)
            (release / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "differs from its parent"):
                validate_release(release, deep_schema=True)

    def test_rows_keep_point_scenario_ranges_and_separate_nulls(self):
        observed = np.arange(16, dtype=float) * 10 + 5
        flows = np.zeros((3, 16, 5))
        for scenario, factor in enumerate([0.5, 0.3, 0.6]):
            flows[scenario, :, 0] = observed * factor
            flows[scenario, :, 4] = observed * (1 - factor)
        lower = np.zeros((16, 5))
        upper = np.repeat(observed[:, None], 5, axis=1)
        rows = flow_rows(observed, flows, lower, upper)
        self.assertEqual(rows[13]["originId"], "null_ballot")
        self.assertEqual(rows[14]["originId"], "null_technical")
        self.assertEqual(rows[1]["estimated"]["lula"], 7.5)
        self.assertEqual(rows[1]["sensitivity"]["lula"], {"min": 4.5, "max": 9.0})
        self.assertEqual(rows[1]["identificationBounds"]["flavio"], {"min": 0.0, "max": 15.0})
        validate_rows(rows)


if __name__ == "__main__":
    unittest.main()
