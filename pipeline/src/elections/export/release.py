"""Export a public release (schema 2.0) from an analysis run and pinned geography."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np

from elections.analysis.run import AnalysisResults, code_revision
from elections.export.verify import validate_bundle
from elections.preparation.geography import build_geography, normalize_name
from elections.sources.registry import load_registry
from elections.taxonomy import (ABROAD, DESTINATION_IDS, DESTINATIONS, DISPLAY_GROUPS, ELECTION_YEAR, ORIGINS,
                                   SCHEMA_VERSION, STATE_NAMES)

FIXTURE_STATE = "MG"
ZERO = 1e-9
SOURCES = [
    {"label": "TSE · Resultados por seção 2026", "url": "https://dadosabertos.tse.jus.br/dataset/resultados-2026"},
    {"label": "TSE · Transferência temporária de eleitores 2026", "url": "https://dadosabertos.tse.jus.br/dataset/eleitorado-2026"},
    {"label": "IBGE · Malhas e localidades (API v3 e v1)", "url": "https://servicodados.ibge.gov.br/api/docs/"},
]
LIMITATIONS = [
    "Inferência ecológica a partir de totais por seção: as transições individuais não são identificadas.",
    "As estimativas são condicionais ao modelo; a faixa de sensibilidade não é um intervalo de confiança.",
    "A geografia é a do local de votação no primeiro turno, não a residência.",
    "Quem mudou de seção entre os turnos fica na geografia de origem; o destino desses eleitores segue uma hipótese nacional de pareamento.",
    "Limites de identificação valem célula a célula e não ocorrem necessariamente juntos.",
]


def write_resource(output: Path, relative: str, value: dict, compressed: bool = False) -> dict:
    content = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if compressed:
        content = gzip.compress(content, compresslevel=9, mtime=0)
    path = output / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {"path": relative, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            "encoding": "gzip" if compressed else "json"}


def display_name(value: str) -> str:
    if not value.isupper():
        return value
    words = value.title().split()
    return " ".join(word.lower() if index and word in {"De", "Da", "Do", "Das", "Dos", "E"} else word
                    for index, word in enumerate(words))


def _clean(value: float) -> float:
    return 0.0 if abs(value) < ZERO else float(value)


def flow_rows(observed: np.ndarray, flows: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> list[dict]:
    """Rows for one place: observed (K,), flows (scenarios, K, D) with the point first, bounds (K, D)."""
    rows = []
    for index, origin in enumerate(ORIGINS):
        def finalist_range(low: np.ndarray, high: np.ndarray) -> dict:
            return {destination: {"min": _clean(low[column]), "max": _clean(high[column])}
                    for column, destination in enumerate(DESTINATION_IDS[:2])}
        scenario_flows = flows[:, index]
        rows.append({
            "originId": origin.id, "observed": float(observed[index]),
            "estimated": {destination: _clean(scenario_flows[0, column]) for column, destination in enumerate(DESTINATION_IDS)},
            "sensitivity": finalist_range(scenario_flows.min(axis=0), scenario_flows.max(axis=0)),
            "identificationBounds": finalist_range(lower[index], upper[index]),
        })
    return rows


def _place(place_id: str, name: str, state: str, kind: str, parent: str | None, electorate: float, sections: float,
           rows: list[dict], ibge_code: str | None = None) -> dict:
    place = {"id": place_id, "name": name, "stateCode": state, "kind": kind, "parentId": parent,
             "electorate": float(electorate), "sectionCount": float(sections), "rows": rows}
    if ibge_code:
        place["ibgeCode"] = ibge_code
    return place


def _bundle(place: dict, level: str, children: list[dict], layer: str, label: str, collection: dict,
            version: str, source_label: str, limitations: list[str]) -> dict:
    names = {child["id"]: child["name"] for child in children}
    features = [{**feature, "properties": {"id": feature["id"], "name": names[feature["id"]]}}
                for feature in collection["features"] if feature["id"] in names]
    bundle = {"schemaVersion": SCHEMA_VERSION, "datasetVersion": version, "id": place["id"], "level": level,
              "place": place, "children": children, "geometry": {layer: {"type": "FeatureCollection", "features": features}},
              "layers": [{"id": layer, "label": label, "kind": "polygon"}], "defaultLayer": layer,
              "sourceLabel": source_label}
    if limitations:
        bundle["limitations"] = limitations
    return bundle


def export_release(run_directory: Path, raw_root: Path, output: Path, fixture: bool = False,
                   overwrite: bool = False) -> dict:
    started = time.monotonic()
    results = AnalysisResults.load(run_directory)
    meta = results.metadata
    if output.exists():
        if not overwrite:
            raise FileExistsError(f"{output} exists; pass overwrite to replace it")
        shutil.rmtree(output)
    output.mkdir(parents=True)
    version = meta["runId"] + ("-fixture" if fixture else "")
    municipality_ids = results.municipality_ids.tolist()
    geography = build_geography(raw_root, municipality_ids, results.municipality_names.tolist())

    state_flows = results.state_flows()
    state_observed = np.zeros((len(results.state_ids), results.observed.shape[1]))
    np.add.at(state_observed, results.municipality_state, results.observed)
    electorate = np.bincount(results.municipality_state, results.electorate, len(results.state_ids))
    sections = np.bincount(results.municipality_state, results.sections, len(results.state_ids))

    national = _place("BR", "Brasil", "BR", "national", None, results.electorate.sum(), results.sections.sum(),
                      flow_rows(results.observed.sum(axis=0), results.flows.sum(axis=1),
                                results.national_bounds_lower, results.national_bounds_upper))
    states = {}
    for index, state in enumerate(results.state_ids.tolist()):
        states[state] = _place(state, STATE_NAMES[state], state, "state", "BR", electorate[index], sections[index],
                               flow_rows(state_observed[index], state_flows[:, index], results.state_bounds_lower[index],
                                         results.state_bounds_upper[index]))
    municipalities: dict[str, list[dict]] = {state: [] for state in states}
    for index, municipality_id in enumerate(municipality_ids):
        state = municipality_id.split(":")[0]
        link = geography.links.get(municipality_id)
        name = link["name"] if link else display_name(str(results.municipality_names[index]))
        municipalities[state].append(_place(
            municipality_id, name, state, "foreign" if state == ABROAD else "municipality", state,
            results.electorate[index], results.sections[index],
            flow_rows(results.observed[index], results.flows[:, index], results.bounds_lower[index],
                      results.bounds_upper[index]), link["ibgeCode"] if link else None))

    resources: dict = {"states": {}}
    maximum_row_error = 0.0
    missing = set(geography.report["municipalitiesWithoutPolygon"])
    for state, children in municipalities.items():
        if fixture and state != FIXTURE_STATE:
            continue
        children.sort(key=lambda child: child["name"])
        limitations = []
        if state == ABROAD:
            limitations.append("Exterior: localidades eleitorais apresentadas em lista, sem mapa.")
        for child in children:
            if child["id"] in missing:
                limitations.append(f"{child['name']} não tem polígono na malha do IBGE utilizada e aparece apenas na lista; "
                                   "nessa malha, seu território está incluído em polígonos de municípios vizinhos.")
        collection = geography.municipalities.get(state, {"type": "FeatureCollection", "features": []})
        bundle = _bundle(states[state], "state", children, "municipalities",
                         "Localidades" if state == ABROAD else "Municípios", collection, version,
                         "TSE 2026 · Limites municipais IBGE", limitations)
        maximum_row_error = max(maximum_row_error, validate_bundle(bundle, schema=True)["maximumRowError"])
        resources["states"][state] = write_resource(output, f"states/{state}.json.bin", bundle, True)
    national_bundle = _bundle(national, "national", list(states.values()), "states", "Estados", geography.states,
                              version, "TSE 2026 · Limites estaduais IBGE",
                              ["O total do Brasil inclui eleitores no exterior (ZZ), que não têm polígono."])
    maximum_row_error = max(maximum_row_error, validate_bundle(national_bundle, schema=True)["maximumRowError"])
    resources["national"] = write_resource(output, "national.json", national_bundle)
    search_fields = ("id", "name", "stateCode", "kind", "parentId", "ibgeCode")
    search_places = [national, *states.values(), *(child for children in municipalities.values() for child in children)]
    tse_names = dict(zip(municipality_ids, (display_name(str(name)) for name in results.municipality_names), strict=True))
    entries = []
    for place in search_places:
        entry = {key: place[key] for key in search_fields if key in place}
        alias = tse_names.get(place["id"])
        if alias and normalize_name(alias) != normalize_name(place["name"]):
            entry["aliases"] = [alias]
        entries.append(entry)
    search = {"schemaVersion": SCHEMA_VERSION, "datasetVersion": version, "places": entries}
    resources["search"] = write_resource(output, "search-index.json", search)

    spec = meta["specification"]["document"]
    registry = load_registry()
    manifest = {
        "schemaVersion": SCHEMA_VERSION, "datasetVersion": version, "electionYear": ELECTION_YEAR,
        "scope": "fixture" if fixture else "full",
        "model": {"id": spec["id"], "label": spec["label"],
                  "status": "Estimativas condicionais ao modelo; transferências individuais não identificadas.",
                  "scenarioCount": len(results.scenario_ids),
                  "scenarios": [{"id": key, "label": label} for key, label in
                                zip(results.scenario_ids.tolist(), results.scenario_labels.tolist(), strict=True)],
                  "sensitivityDescription": spec["sensitivityDescription"],
                  "boundsDescription": spec["boundsDescription"]},
        "origins": [{"id": origin.id, "label": origin.label, "shortLabel": origin.short_label, "kind": origin.kind}
                    for origin in ORIGINS],
        "displayGroups": [{"id": key, "label": label, "shortLabel": short, "members": list(members)}
                          for key, label, short, members in DISPLAY_GROUPS],
        "destinations": [{"id": key, "label": label} for key, label in DESTINATIONS],
        "resources": resources,
        "provenance": {
            "operation": "Analysis run by this repository's pipeline from TSE section counts.",
            "runId": meta["runId"], "resultsSha256": meta["resultsSha256"], "panelSha256": meta["panelSha256"],
            "createdUtc": meta["createdUtc"], "code": meta["code"],
            "exportCode": code_revision(),
            "specification": {"id": spec["id"], "sha256": meta["specification"]["sha256"]},
            "selectedModel": meta["selectedModel"], "holdout": meta["holdout"],
            "sourceSha256": {**meta["panel"]["sourceSha256"],
                             **{key: registry[key].sha256 for key in registry if key.startswith("ibge-")}},
            "geography": geography.report, "electionDataYear": ELECTION_YEAR, "sources": SOURCES,
            "limitations": LIMITATIONS + (["Amostra real de desenvolvimento: Brasil, estados e municípios de Minas Gerais. "
                                           "Os totais permanecem completos."] if fixture else []),
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
    summary = {"schemaVersion": SCHEMA_VERSION, "datasetVersion": version, "scope": manifest["scope"],
               "runId": meta["runId"], "statePackages": len(resources["states"]),
               "municipalities": sum(len(children) for state, children in municipalities.items() if state != ABROAD),
               "foreignLocalities": len(municipalities.get(ABROAD, [])), "maximumRowError": maximum_row_error,
               "totalBytes": sum(path.stat().st_size for path in output.rglob("*") if path.is_file()),
               "elapsedSeconds": round(time.monotonic() - started, 1)}
    (output / "export-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary
