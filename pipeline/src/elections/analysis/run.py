"""Run a declared analysis end to end and record its provenance.

Steps: tune the municipal penalty on training folds by validation-fold aggregate
prediction, score the selection on the holdout folds, refit every sensitivity
model on all sections, reconcile each section by IPF, attribute movers by an
explicit national bridge, and sum flows by municipality. Accounting bounds are
computed from the section counts alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time

import numpy as np
import pandas as pd
import scipy

from elections.analysis.specification import AnalysisSpec, ModelSpec
from elections.inference import (fit_hierarchy, grouped_section_bounds, national_bounds, predict_shares,
                                    prediction_score, reconcile_sections, section_moments)
from elections.preparation.panel import PANEL_VERSION, SectionPanel, array_digest, build_panel
from elections.sources.registry import REPOSITORY_ROOT, load_registry

RESULTS_VERSION = "results-2"
PIPELINE_SOURCE = REPOSITORY_ROOT / "pipeline/src/elections"
PANEL_CODE = ("preparation/panel.py", "sources", "taxonomy.py")
RESULT_ARRAYS = ("scenario_ids", "scenario_labels", "municipality_ids", "municipality_names", "municipality_state",
                 "state_ids", "observed", "electorate", "sections", "flows", "bounds_lower", "bounds_upper",
                 "state_bounds_lower", "state_bounds_upper", "national_bounds_lower", "national_bounds_upper",
                 "selected_national", "selected_states", "selected_municipalities")


@dataclass
class AnalysisResults:
    """Municipality-level flows per scenario; index 0 is the selected point estimate."""

    scenario_ids: np.ndarray
    scenario_labels: np.ndarray
    municipality_ids: np.ndarray
    municipality_names: np.ndarray
    municipality_state: np.ndarray
    state_ids: np.ndarray
    observed: np.ndarray        # (municipalities, origins)
    electorate: np.ndarray      # (municipalities,)
    sections: np.ndarray        # (municipalities,)
    flows: np.ndarray           # (scenarios, municipalities, origins, destinations)
    bounds_lower: np.ndarray    # (municipalities, origins, destinations)
    bounds_upper: np.ndarray
    state_bounds_lower: np.ndarray
    state_bounds_upper: np.ndarray
    national_bounds_lower: np.ndarray
    national_bounds_upper: np.ndarray
    selected_national: np.ndarray
    selected_states: np.ndarray
    selected_municipalities: np.ndarray
    metadata: dict = field(default_factory=dict)

    def state_flows(self) -> np.ndarray:
        result = np.zeros((self.flows.shape[0], len(self.state_ids)) + self.flows.shape[2:])
        np.add.at(result, (slice(None), self.municipality_state), self.flows)
        return result

    def digest(self) -> str:
        return array_digest({name: getattr(self, name) for name in RESULT_ARRAYS})

    def save(self, directory: Path) -> None:
        """Write a new run directory; an existing run is never overwritten."""
        directory.mkdir(parents=True, exist_ok=False)
        np.savez_compressed(directory / "results.npz", **{name: getattr(self, name) for name in RESULT_ARRAYS})
        metadata = {**self.metadata, "resultsSha256": self.digest()}
        (directory / "run.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")

    @classmethod
    def load(cls, directory: Path) -> "AnalysisResults":
        with np.load(directory / "results.npz", allow_pickle=False) as arrays:
            values = {name: arrays[name] for name in RESULT_ARRAYS}
        metadata = json.loads((directory / "run.json").read_text())
        results = cls(**values, metadata=metadata)
        if metadata.get("resultsSha256") != results.digest():
            raise ValueError(f"Run {directory} does not match its recorded results digest")
        return results


def code_revision() -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    try:
        tracked = ("pipeline", "data/specs", "data/sources.json", "data/geography", "data/schemas")
        return {"gitRevision": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--", *tracked))}
    except (OSError, subprocess.CalledProcessError):
        return {"gitRevision": None, "dirty": True}


def source_code_digest(paths: tuple[Path, ...] = (PIPELINE_SOURCE,)) -> str:
    """Digest of every Python file under the given paths, independent of Git state."""
    digest = hashlib.sha256()
    files = sorted(file for path in paths for file in ([path] if path.is_file() else path.rglob("*.py")))
    for file in files:
        digest.update(file.relative_to(PIPELINE_SOURCE.parent).as_posix().encode() + b"\0")
        digest.update(file.read_bytes() + b"\0")
    return digest.hexdigest()


def load_or_build_panel(raw_root: Path, cache_root: Path) -> SectionPanel:
    """Reuse a cached panel only for identical sources and panel-building code."""
    hashes = {key: source.sha256 for key, source in load_registry().items() if key.startswith("tse-")}
    code = source_code_digest(tuple(PIPELINE_SOURCE / name for name in PANEL_CODE))
    key = hashlib.sha256(json.dumps([PANEL_VERSION, hashes, code], sort_keys=True).encode()).hexdigest()[:16]
    path = cache_root / f"panel-{key}.npz"
    if path.exists():
        return SectionPanel.load(path)
    panel = build_panel(raw_root)
    panel.save(path)
    return panel


def _fit(model: ModelSpec, moments, panel: SectionPanel):
    return fit_hierarchy(moments, panel.municipality_state, level=model.level, state_penalty=model.state_penalty,
                         municipal_penalty=model.municipal_penalty)


def run_analysis(panel: SectionPanel, spec: AnalysisSpec, *, progress=print) -> AnalysisResults:
    started = time.monotonic()
    n_mun = len(panel.municipality_ids)
    origins, destinations = panel.x.shape[1], panel.y.shape[1]

    def moments(mask: np.ndarray | None = None):
        weights = None if mask is None else mask.astype(float)
        return section_moments(panel.x, panel.y, panel.n1, panel.n2, panel.municipality, n_mun, weights)

    def score(fit, mask: np.ndarray) -> dict:
        predicted = predict_shares(panel.x[mask], panel.n1[mask], panel.n2[mask], fit.municipalities,
                                   panel.municipality[mask])
        return prediction_score(predicted, panel.y[mask], panel.n2[mask])

    train = np.isin(panel.fold, spec.train_folds)
    validation = np.isin(panel.fold, spec.validation_folds)
    holdout = np.isin(panel.fold, spec.holdout_folds)
    train_moments = moments(train)
    tuning = {}
    for model in spec.candidates:
        fit = _fit(model, train_moments, panel)
        tuning[model.id] = {"validation": score(fit, validation), "sweeps": fit.sweeps}
        progress(f"tuning {model.id}: {tuning[model.id]['validation']['meanSquaredError']:.10g}")
    selected = min(spec.candidates, key=lambda model: tuning[model.id]["validation"]["meanSquaredError"])
    holdout_fit = _fit(selected, moments(~holdout), panel)
    holdout_score = score(holdout_fit, holdout)
    progress(f"selected {selected.id}; holdout {holdout_score['meanSquaredError']:.10g}")

    full_moments = moments()
    fits = {}
    scenarios = spec.scenarios(selected)
    observed = np.zeros((n_mun, origins))
    np.add.at(observed, panel.municipality, panel.x)
    flows = np.empty((len(scenarios), n_mun, origins, destinations))
    diagnostics = {}
    for index, scenario in enumerate(scenarios):
        if scenario.model.id not in fits:
            fits[scenario.model.id] = _fit(scenario.model, full_moments, panel)
        fit = fits[scenario.model.id]
        incoming, outgoing = panel.mobility(scenario.mobility, scenario.turnover)
        reconciled = reconcile_sections(panel.x, panel.y, panel.n1, panel.n2, incoming, outgoing, fit.municipalities,
                                        panel.municipality, panel.municipality, n_mun,
                                        probability_floor=scenario.probability_floor)
        flows[index] = reconciled.bridged()
        row_error = float(np.abs(flows[index].sum(axis=2) - observed).max())
        column_error = float(np.abs(flows[index].sum(axis=(0, 1)) - panel.y.sum(axis=0)).max())
        # Each section meets its column margins within the IPF tolerance (1e-6 vote).
        if row_error > 1e-3 or column_error > 1e-6 * len(panel.x):
            raise AssertionError(f"Scenario {scenario.id} does not preserve margins: {row_error}, {column_error}")
        diagnostics[scenario.id] = {
            "label": scenario.label, "model": scenario.model.id, "mobility": scenario.mobility,
            "turnover": scenario.turnover, "probabilityFloor": scenario.probability_floor,
            "sweeps": fit.sweeps, "ipfMaxMarginError": reconciled.max_margin_error,
            "ipfMaxIterations": reconciled.max_iterations, "movers": float(reconciled.leaving.sum()),
            "maxOriginRowError": row_error, "maxNationalDestinationError": column_error,
        }
        progress(f"scenario {scenario.id}: IPF iterations {reconciled.max_iterations}")

    # Bounds hold for any true mobility no larger, section by section, than the
    # largest mobility among the declared scenarios; they widen monotonically.
    mobilities = [panel.mobility(scenario.mobility, scenario.turnover) for scenario in scenarios]
    incoming = np.max([pair[0] for pair in mobilities], axis=0)
    outgoing = np.max([pair[1] for pair in mobilities], axis=0)
    bounds = grouped_section_bounds(panel.x, panel.y, incoming, outgoing, panel.municipality, n_mun)
    n_states = len(panel.state_ids)
    state_lower = np.zeros((n_states, origins, destinations))
    state_upper = np.zeros((n_states, origins, destinations))
    np.add.at(state_lower, panel.municipality_state, bounds.lower)
    np.add.at(state_upper, panel.municipality_state, bounds.upper)
    frechet_lower, frechet_upper = national_bounds(panel.x.sum(axis=0), panel.y.sum(axis=0))
    national_lower = np.maximum(bounds.lower.sum(axis=0), frechet_lower)
    national_upper = np.minimum(bounds.upper.sum(axis=0), frechet_upper)
    for label, lower, upper, values in (("municipality", bounds.lower, bounds.upper, flows),
                                        ("national", national_lower, national_upper, flows.sum(axis=1))):
        if (values < lower - 1e-6).any() or (values > upper + 1e-6).any():
            raise AssertionError(f"A scenario lies outside the {label} accounting bounds")

    selected_fit = fits[selected.id]
    electorate = np.bincount(panel.municipality, panel.n1, n_mun)
    sections = np.bincount(panel.municipality, minlength=n_mun).astype(float)
    revision = {**code_revision(), "sourceSha256": source_code_digest()}
    identity = {"specification": spec.sha256, "sources": panel.metadata["sourceSha256"], "code": revision,
                "panel": panel.digest()}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    today = dt.datetime.now(dt.timezone.utc)
    metadata = {
        "resultsVersion": RESULTS_VERSION, "runId": f"{spec.id}-{today:%Y%m%d}-{digest[:12]}",
        "createdUtc": today.isoformat(timespec="seconds"), "code": revision, "panelSha256": panel.digest(),
        "boundsMobility": "Per-section maximum of incoming and outgoing voters across the declared scenarios.",
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                        "pandas": pd.__version__},
        "specification": {"id": spec.id, "sha256": spec.sha256, "document": spec.document},
        "panel": panel.metadata, "tuning": tuning, "selectedModel": selected.id, "holdout": holdout_score,
        "scenarios": diagnostics,
        "elapsedSeconds": round(time.monotonic() - started, 1),
    }
    return AnalysisResults(
        scenario_ids=np.array([scenario.id for scenario in scenarios]),
        scenario_labels=np.array([scenario.label for scenario in scenarios]),
        municipality_ids=panel.municipality_ids, municipality_names=panel.municipality_names,
        municipality_state=panel.municipality_state, state_ids=panel.state_ids, observed=observed,
        electorate=electorate, sections=sections, flows=flows, bounds_lower=bounds.lower, bounds_upper=bounds.upper,
        state_bounds_lower=state_lower, state_bounds_upper=state_upper, national_bounds_lower=national_lower,
        national_bounds_upper=national_upper, selected_national=selected_fit.national,
        selected_states=selected_fit.states, selected_municipalities=selected_fit.municipalities, metadata=metadata)
