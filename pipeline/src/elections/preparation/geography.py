"""State and municipality polygons keyed by TSE identifiers.

TSE municipality codes are linked to IBGE codes by state plus normalized name,
with a reviewed alias list for the remaining differences; there is no fuzzy
matching. Polygons come unchanged from the pinned IBGE mesh except for rounding
coordinates to four decimals. A municipality absent from the mesh stays without
geometry rather than borrowing a neighbor's polygon. Places abroad have none.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import unicodedata

from elections.sources.registry import REPOSITORY_ROOT, SourceFile, load_registry, verify_sources
from elections.taxonomy import ABROAD, STATE_NAMES

ALIASES_PATH = REPOSITORY_ROOT / "data/geography/municipality-aliases.json"
SOURCES = ("ibge-municipality-mesh", "ibge-state-mesh", "ibge-municipalities", "ibge-states")


@dataclass(frozen=True)
class Geography:
    states: dict                     # FeatureCollection keyed by state code
    municipalities: dict[str, dict]  # state code -> FeatureCollection keyed by TSE id
    links: dict[str, dict]           # TSE id -> {"ibgeCode", "name", "method"}
    report: dict


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if character.isalnum() and not unicodedata.combining(character))


def _round(coordinates):
    return [_round(value) for value in coordinates] if isinstance(coordinates, list) else round(coordinates, 4)


def _state_of(locality: dict) -> str:
    return locality["regiao-imediata"]["regiao-intermediaria"]["UF"]["sigla"]


def link_municipalities(municipality_ids: list[str], tse_names: list[str], registry_entries: list[dict],
                        aliases: dict[str, dict]) -> dict[str, dict]:
    by_code = {str(entry["id"]): entry for entry in registry_entries}
    index = defaultdict(list)
    for entry in registry_entries:
        index[(_state_of(entry), normalize_name(entry["nome"]))].append(str(entry["id"]))
    ambiguous = {key: codes for key, codes in index.items() if len(codes) > 1}
    if ambiguous:
        raise ValueError(f"Ambiguous IBGE names after normalization: {ambiguous}")
    links = {}
    for municipality_id, tse_name in zip(municipality_ids, tse_names, strict=True):
        state = municipality_id.split(":")[0]
        if state == ABROAD:
            continue
        key = (state, normalize_name(tse_name))
        if key in index:
            code, method = index[key][0], "normalized-name"
        elif municipality_id in aliases:
            alias = aliases[municipality_id]
            code, method = alias["ibgeCode"], "reviewed-alias"
            if tse_name != alias["tseName"] or by_code[code]["nome"] != alias["ibgeName"] or _state_of(by_code[code]) != state:
                raise ValueError(f"Alias for {municipality_id} no longer matches its sources")
        else:
            raise ValueError(f"No IBGE link for {municipality_id} ({tse_name})")
        links[municipality_id] = {"ibgeCode": code, "name": by_code[code]["nome"], "method": method}
    codes = [link["ibgeCode"] for link in links.values()]
    if len(set(codes)) != len(codes):
        raise ValueError("The TSE-IBGE link is not one-to-one")
    unused = set(aliases) - {key for key, link in links.items() if link["method"] == "reviewed-alias"}
    if unused:
        raise ValueError(f"Unused aliases: {sorted(unused)}")
    return links


def build_geography(raw_root: Path, municipality_ids: list[str], tse_names: list[str],
                    registry: dict[str, SourceFile] | None = None) -> Geography:
    registry = registry or load_registry()
    verify_sources(raw_root, {key: registry[key] for key in SOURCES})
    read = lambda key: json.loads((raw_root / registry[key].path).read_text())  # noqa: E731
    aliases = json.loads(ALIASES_PATH.read_text())["aliases"]
    links = link_municipalities(municipality_ids, tse_names, read("ibge-municipalities"), aliases)
    by_ibge = {link["ibgeCode"]: municipality_id for municipality_id, link in links.items()}

    municipalities: dict[str, list] = {state: [] for state in STATE_NAMES if state != ABROAD}
    unlinked_polygons = []
    for feature in read("ibge-municipality-mesh")["features"]:
        code = feature["properties"]["codarea"]
        municipality_id = by_ibge.get(code)
        if municipality_id is None:
            unlinked_polygons.append(code)
            continue
        state = municipality_id.split(":")[0]
        municipalities[state].append({
            "type": "Feature", "id": municipality_id,
            "properties": {"id": municipality_id, "name": links[municipality_id]["name"]},
            "geometry": {"type": feature["geometry"]["type"], "coordinates": _round(feature["geometry"]["coordinates"])}})
    state_codes = {str(entry["id"]): entry["sigla"] for entry in read("ibge-states")}
    states = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": state_codes[feature["properties"]["codarea"]],
         "properties": {"id": state_codes[feature["properties"]["codarea"]], "name": STATE_NAMES[state_codes[feature["properties"]["codarea"]]]},
         "geometry": {"type": feature["geometry"]["type"], "coordinates": _round(feature["geometry"]["coordinates"])}}
        for feature in read("ibge-state-mesh")["features"]]}
    with_geometry = {feature["id"] for features in municipalities.values() for feature in features}
    report = {
        "linkedMunicipalities": len(links),
        "linkMethods": {method: sum(link["method"] == method for link in links.values())
                        for method in ("normalized-name", "reviewed-alias")},
        "municipalitiesWithoutPolygon": sorted(set(links) - with_geometry),
        "polygonsWithoutTseMunicipality": sorted(unlinked_polygons),
        "statePolygons": len(states["features"]),
    }
    if report["polygonsWithoutTseMunicipality"] or len(states["features"]) != 27:
        raise ValueError(f"Unexpected geography coverage: {report}")
    collections = {state: {"type": "FeatureCollection", "features": sorted(features, key=lambda item: item["id"])}
                   for state, features in municipalities.items()}
    return Geography(states, collections, links, report)
