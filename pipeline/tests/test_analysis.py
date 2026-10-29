"""End-to-end analysis on a synthetic closed-cohort panel: scenarios, bounds, and run identity.

The two-municipality real-data TSE fixture is not a closed cohort, so it tests
panel construction (test_panel.py) rather than the national analysis.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from elections.analysis.run import AnalysisResults, run_analysis
from elections.analysis.specification import load_spec
from elections.preparation.panel import SectionPanel

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "data/specs/2026-v3.json"


def synthetic_panel(seed: int = 2026, sections: int = 600) -> SectionPanel:
    """Closed-cohort sections from municipality-specific transition matrices.

    A few section pairs exchange voters between rounds so that net and registry
    mobility are nonzero but balance nationally, as in the real electorate.
    """
    random = np.random.default_rng(seed)
    municipality = np.repeat(np.arange(6), sections // 6)
    state = np.array([0, 0, 0, 1, 1, 1])[municipality]
    base = random.dirichlet(np.ones(5) * 0.6, 16)
    matrices = np.array([0.8 * base + 0.2 * random.dirichlet(np.ones(5), 16) for _ in range(6)])
    n1 = random.integers(150, 400, sections).astype(float)
    x = np.array([random.multinomial(int(n), random.dirichlet(np.ones(16) * 0.8)) for n in n1], dtype=float)
    y = np.array([sum(random.multinomial(int(count), matrices[municipality[s], i]) for i, count in enumerate(x[s]))
                  for s in range(sections)], dtype=float)
    movers = np.zeros(sections)
    movers[:20:2], movers[1:20:2] = 3, -3
    for s in np.flatnonzero(movers):
        column = int(np.argmax(y[s]))
        y[s, column] += movers[s]
    n2 = y.sum(axis=1)
    delta = n2 - n1
    ids = np.array([f"{'AA' if m < 3 else 'BB'}:{1000 + m}" for m in range(6)])
    return SectionPanel(
        x=x, y=y, n1=n1, n2=n2, state=state, municipality=municipality, component=np.arange(sections),
        fold=random.integers(0, 5, sections), incoming=np.maximum(delta, 0), outgoing=np.maximum(-delta, 0),
        incoming_registry=np.maximum(delta, 0) + (np.arange(sections) == 30), outgoing_registry=np.maximum(-delta, 0) + (np.arange(sections) == 30),
        state_ids=np.array(["AA", "BB"]), municipality_ids=ids, municipality_state=np.array([0, 0, 0, 1, 1, 1]),
        municipality_names=np.array([f"CIDADE {m}" for m in range(6)]), section_zone=np.ones(sections, dtype=np.int64),
        section_number=np.arange(sections), metadata={"sourceSha256": {"synthetic": "0" * 64}})


class AnalysisRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = synthetic_panel()
        cls.spec = load_spec(SPEC)
        cls.results = run_analysis(cls.panel, cls.spec, progress=lambda message: None)

    def test_twelve_scenarios_preserve_origins_and_national_destinations(self):
        results = self.results
        self.assertEqual(len(results.scenario_ids), 12)
        self.assertEqual(results.scenario_ids[0], results.metadata["selectedModel"])
        np.testing.assert_allclose(results.flows.sum(axis=3), np.broadcast_to(results.observed, results.flows.shape[:3]), atol=1e-6)
        for scenario in results.flows:
            np.testing.assert_allclose(scenario.sum(axis=(0, 1)), self.panel.y.sum(axis=0), atol=1e-4)
        self.assertTrue((results.flows >= 0).all())

    def test_every_scenario_lies_within_accounting_bounds(self):
        results = self.results
        self.assertTrue((results.flows >= results.bounds_lower - 1e-6).all())
        self.assertTrue((results.flows <= results.bounds_upper + 1e-6).all())
        self.assertTrue((results.bounds_upper <= results.observed[:, :, None] + 1e-9).all())
        national = results.flows.sum(axis=1)
        self.assertTrue((national >= results.national_bounds_lower - 1e-6).all())
        self.assertTrue((national <= results.national_bounds_upper + 1e-6).all())

    def test_run_identity_and_digests(self):
        results = self.results
        self.assertRegex(results.metadata["runId"], r"^2026-v3-\d{8}-[0-9a-f]{12}$")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "run"
            results.save(target)
            loaded = AnalysisResults.load(target)
            np.testing.assert_array_equal(loaded.flows, results.flows)
            with self.assertRaises(FileExistsError):
                results.save(target)
            metadata = json.loads((target / "run.json").read_text())
            metadata["resultsSha256"] = "0" * 64
            (target / "run.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "digest"):
                AnalysisResults.load(target)


if __name__ == "__main__":
    unittest.main()
