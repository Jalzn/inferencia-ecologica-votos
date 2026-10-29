"""Declarative analysis specifications: candidate models, sensitivity scenarios, and folds."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    level: str
    state_penalty: float
    municipal_penalty: float | None = None


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    model: ModelSpec
    mobility: str = "net"
    turnover: float = 0.0
    probability_floor: float = 1e-4


@dataclass(frozen=True)
class AnalysisSpec:
    id: str
    label: str
    candidates: tuple[ModelSpec, ...]
    sensitivity_models: tuple[ModelSpec, ...]
    variants: tuple[dict, ...]
    probability_floor: float
    train_folds: tuple[int, ...]
    validation_folds: tuple[int, ...]
    holdout_folds: tuple[int, ...]
    sensitivity_description: str
    bounds_description: str
    sha256: str
    document: dict

    def scenarios(self, selected: ModelSpec) -> list[Scenario]:
        """Selected model first, then the other sensitivity models, then variants of the selection."""
        base = [Scenario(selected.id, selected.label, selected, probability_floor=self.probability_floor)]
        base += [Scenario(model.id, model.label, model, probability_floor=self.probability_floor)
                 for model in self.sensitivity_models if model.id != selected.id]
        for variant in self.variants:
            base.append(Scenario(variant["id"], variant["label"], selected, variant.get("mobility", "net"),
                                 float(variant.get("turnover", 0.0)),
                                 float(variant.get("probabilityFloor", self.probability_floor))))
        if len({scenario.id for scenario in base}) != len(base):
            raise ValueError("Scenario identifiers must be unique")
        return base


def _model(entry: dict, state_penalty: float) -> ModelSpec:
    if entry["level"] not in {"national", "state", "municipal"}:
        raise ValueError(f"Unknown model level in {entry['id']}")
    penalty = entry.get("municipalPenalty")
    if (entry["level"] == "municipal") != (penalty is not None):
        raise ValueError(f"Model {entry['id']} must set a municipal penalty exactly when it is municipal")
    return ModelSpec(entry["id"], entry["label"], entry["level"], float(entry.get("statePenalty", state_penalty)),
                     None if penalty is None else float(penalty))


def load_spec(path: Path) -> AnalysisSpec:
    content = path.read_bytes()
    document = json.loads(content)
    state_penalty = float(document["statePenalty"])
    candidates = tuple(_model(entry, state_penalty) for entry in document["candidates"])
    by_id = {model.id: model for model in candidates}
    sensitivity = tuple(by_id[entry] if isinstance(entry, str) else _model(entry, state_penalty)
                        for entry in document["sensitivityModels"])
    if not set(by_id) <= {model.id for model in sensitivity}:
        raise ValueError("Every tuning candidate must also be a sensitivity model")
    folds = document["folds"]
    groups = [set(folds[key]) for key in ("train", "validation", "holdout")]
    if any(a & b for index, a in enumerate(groups) for b in groups[index + 1:]):
        raise ValueError("Train, validation, and holdout folds must be disjoint")
    return AnalysisSpec(document["id"], document["label"], candidates, sensitivity, tuple(document["variants"]),
                        float(document["probabilityFloor"]), tuple(folds["train"]), tuple(folds["validation"]),
                        tuple(folds["holdout"]), document["sensitivityDescription"], document["boundsDescription"],
                        hashlib.sha256(content).hexdigest(), document)
