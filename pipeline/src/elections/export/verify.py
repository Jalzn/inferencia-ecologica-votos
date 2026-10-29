"""Validate release integrity, taxonomy, accounting, and geographic partitions (schema 2.0)."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

import jsonschema
import numpy as np

from elections.taxonomy import (ABROAD, BRAZILIAN_MUNICIPALITIES, DESTINATION_IDS as DESTINATIONS, DISPLAY_GROUPS,
                                   ORIGIN_IDS, SCHEMA_VERSION, STATE_NAMES)

PLACE_KINDS = {"national", "state", "municipality", "foreign"}

TOLERANCE = 0.001
SCHEMA_ROOT = Path(__file__).resolve().parents[4] / "data/schemas"


def check_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be a finite nonnegative number")
    return float(value)


def validate_rows(rows: list[dict]) -> float:
    if not isinstance(rows, list) or [row.get("originId") for row in rows] != list(ORIGIN_IDS):
        raise ValueError("Rows must preserve the 16 ordered raw origins")
    maximum = 0.0
    for row in rows:
        base = check_number(row["observed"], "observed")
        if set(row["estimated"]) != set(DESTINATIONS):
            raise ValueError("All five estimated destinations must be present")
        total = math.fsum(check_number(row["estimated"][key], key) for key in DESTINATIONS)
        error = abs(total - base)
        maximum = max(maximum, error)
        if error > TOLERANCE:
            raise ValueError(f"Flow conservation failed for {row['originId']}: {error}")
        if base == 0 and total != 0:
            raise ValueError("Zero observed origin cannot have positive estimated flows")
        for field in ["sensitivity", "identificationBounds"]:
            ranges = row.get(field)
            if ranges is None:
                continue
            if set(ranges) != {"lula", "flavio"}:
                raise ValueError(f"Invalid {field} destinations")
            for destination, interval in ranges.items():
                minimum = check_number(interval["min"], f"{field}.min")
                maximum_value = check_number(interval["max"], f"{field}.max")
                if minimum > maximum_value or maximum_value > base + TOLERANCE:
                    raise ValueError(f"Invalid {field} interval for {destination}")
                point = row["estimated"][destination]
                if point < minimum - TOLERANCE or point > maximum_value + TOLERANCE:
                    raise ValueError(f"Estimated point is outside its {field} interval for {destination}")
        if row.get("sensitivity") and row.get("identificationBounds"):
            for destination in ("lula", "flavio"):
                scenario, bound = row["sensitivity"][destination], row["identificationBounds"][destination]
                if scenario["min"] < bound["min"] - TOLERANCE or scenario["max"] > bound["max"] + TOLERANCE:
                    raise ValueError(f"Sensitivity range exceeds identification bounds for {destination}")
    return maximum


def validate_place(place: dict) -> float:
    for field in ["id", "name", "stateCode", "kind"]:
        if not isinstance(place.get(field), str) or not place[field]:
            raise ValueError(f"Missing place field: {field}")
    if place["kind"] not in PLACE_KINDS:
        raise ValueError(f"Invalid place kind: {place['kind']}")
    if not isinstance(place.get("parentId"), (str, type(None))):
        raise ValueError("Invalid parent identifier")
    for field in ["electorate", "sectionCount"]:
        check_number(place[field], field)
    if abs(math.fsum(row["observed"] for row in place["rows"]) - place["electorate"]) > TOLERANCE:
        raise ValueError(f"Origin totals differ from electorate: {place['id']}")
    if any(row.get("identificationBounds") is None for row in place["rows"]):
        raise ValueError(f"Missing identification bounds: {place['id']}")
    return validate_rows(place["rows"])


def validate_partition(parent: dict, children: list[dict], label: str) -> None:
    fields = [("electorate", parent["electorate"], [child["electorate"] for child in children]),
              ("sectionCount", parent["sectionCount"], [child["sectionCount"] for child in children])]
    for index, parent_row in enumerate(parent["rows"]):
        fields.append((f"{parent_row['originId']}.observed", parent_row["observed"],
                       [child["rows"][index]["observed"] for child in children]))
        fields.extend((f"{parent_row['originId']}.{destination}", parent_row["estimated"][destination],
                       [child["rows"][index]["estimated"][destination] for child in children]) for destination in DESTINATIONS)
    for field, expected, values in fields:
        error = abs(math.fsum(values) - expected)
        if error > TOLERANCE:
            raise ValueError(f"Partition {label}, {field}: error {error}")


def validate_bundle(bundle: dict, schema: bool = False) -> dict:
    if bundle.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("Unsupported bundle schema")
    if schema:
        definition = json.loads((SCHEMA_ROOT / "area-bundle.schema.json").read_text())
        jsonschema.Draft202012Validator(definition).validate(bundle)
    if bundle["id"] != bundle["place"]["id"]:
        raise ValueError("Bundle and selected place identifiers differ")
    expected_level = "national" if bundle["id"] == "BR" else "state"
    if bundle["level"] != expected_level:
        raise ValueError(f"Bundle {bundle['id']} must have level {expected_level}")
    maximum = validate_place(bundle["place"])
    children = bundle["children"]
    by_id = {child["id"]: child for child in children}
    if len(by_id) != len(children):
        raise ValueError("Duplicate child place identifiers")
    allowed = {"national": {"state"}, "state": {"foreign"} if bundle["id"] == ABROAD else {"municipality"}}[bundle["level"]]
    for child in children:
        maximum = max(maximum, validate_place(child))
        if child["parentId"] != bundle["id"] or child["kind"] not in allowed:
            raise ValueError(f"Child {child['id']} has an unexpected parent or kind")
    validate_partition(bundle["place"], children, bundle["id"])
    layer_ids = [layer["id"] for layer in bundle["layers"]]
    if layer_ids != [bundle["defaultLayer"]] or set(bundle["geometry"]) != set(layer_ids):
        raise ValueError("A bundle has exactly one layer, which is its default and its only geometry")
    seen = set()
    for feature in bundle["geometry"][layer_ids[0]]["features"]:
        place_id = feature["properties"]["id"]
        if place_id not in by_id or place_id in seen or feature["properties"].get("name") != by_id[place_id]["name"]:
            raise ValueError(f"Geometry does not match a unique child: {place_id}")
        seen.add(place_id)
    return {"maximumRowError": maximum, "children": len(children), "childrenWithGeometry": len(seen)}


def safe_resource_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", relative):
        raise ValueError("Unsafe resource path")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Resource path escapes release")
    absolute = (root / relative).resolve()
    if not absolute.is_relative_to(root.resolve()):
        raise ValueError("Resource symlink escapes release")
    return absolute


def read_resource(root: Path, descriptor: dict) -> dict:
    if descriptor.get("encoding") == "gzip" and not descriptor["path"].endswith(".json.bin"):
        raise ValueError("Compressed resources require .json.bin to preserve transport byte integrity")
    path = safe_resource_path(root, descriptor["path"])
    content = path.read_bytes()
    if len(content) != descriptor["bytes"] or hashlib.sha256(content).hexdigest() != descriptor["sha256"]:
        raise ValueError(f"Resource integrity mismatch: {descriptor['path']}")
    if descriptor["encoding"] == "gzip":
        content = gzip.decompress(content)
    elif descriptor["encoding"] != "json":
        raise ValueError("Unknown resource encoding")
    return json.loads(content)


def validate_release(root: Path, require_full: bool = False, deep_schema: bool = False) -> dict:
    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    definition = json.loads((SCHEMA_ROOT / "release-manifest.schema.json").read_text())
    jsonschema.Draft202012Validator(definition).validate(manifest)
    resources = manifest["resources"]
    if [origin["id"] for origin in manifest["origins"]] != list(ORIGIN_IDS):
        raise ValueError("Manifest origin taxonomy mismatch")
    if [destination["id"] for destination in manifest["destinations"]] != list(DESTINATIONS):
        raise ValueError("Manifest destination taxonomy mismatch")
    if [[group["id"], group["members"]] for group in manifest["displayGroups"]] != [[key, list(members)] for key, _, _, members in DISPLAY_GROUPS]:
        raise ValueError("Display groups do not match the raw origin taxonomy")
    if manifest["model"]["scenarioCount"] != len(manifest["model"]["scenarios"]):
        raise ValueError("Scenario count differs from the scenario list")
    if require_full:
        if manifest["scope"] != "full":
            raise ValueError("Production publication requires a full release; fixture rejected")
        for field in ("code", "exportCode"):
            code = manifest["provenance"].get(field, {})
            if not code.get("gitRevision") or code.get("dirty") is not False:
                raise ValueError("Production publication requires analysis and export from a clean, committed code revision")
    if manifest["scope"] == "full" and set(resources["states"]) != set(STATE_NAMES):
        raise ValueError("Full release must cover 27 states and the exterior")
    descriptors = [("BR", resources["national"]), *resources["states"].items()]
    paths = [descriptor["path"] for _, descriptor in descriptors] + [resources["search"]["path"]]
    if len(paths) != len(set(paths)):
        raise ValueError("Resource descriptors share a path")
    def signature(place: dict) -> str:
        return hashlib.sha256(json.dumps(place, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    national = read_resource(root, resources["national"])
    expected = {child["id"]: signature(child) for child in national["children"]}
    maximum, checked, byte_count = 0.0, 0, resources["national"]["bytes"]
    municipalities: set[str] = set()
    for key, descriptor in [("BR", resources["national"]), *resources["states"].items()]:
        bundle = national if key == "BR" else read_resource(root, descriptor)
        if bundle["datasetVersion"] != manifest["datasetVersion"] or bundle["id"] != key:
            raise ValueError("Bundle version or identifier differs from manifest")
        metrics = validate_bundle(bundle, schema=deep_schema or key in {"BR", "MG"})
        if key != "BR":
            if expected.get(key) != signature(bundle["place"]):
                raise ValueError(f"Selected place differs from its parent bundle: {key}")
            byte_count += descriptor["bytes"]
            municipalities.update(child["id"] for child in bundle["children"] if child["kind"] == "municipality")
        maximum = max(maximum, metrics["maximumRowError"])
        checked += 1 + metrics["children"]
    if manifest["scope"] == "full" and len(municipalities) != BRAZILIAN_MUNICIPALITIES:
        raise ValueError(f"Full release must contain {BRAZILIAN_MUNICIPALITIES} municipalities, found {len(municipalities)}")
    search = read_resource(root, resources["search"])
    if search["schemaVersion"] != SCHEMA_VERSION or search["datasetVersion"] != manifest["datasetVersion"]:
        raise ValueError("Search version mismatch")
    if len({place["id"] for place in search["places"]}) != len(search["places"]):
        raise ValueError("Duplicate search identifiers")
    searchable = {place["id"] for place in search["places"] if place["kind"] == "municipality"}
    if manifest["scope"] == "full" and searchable != municipalities:
        raise ValueError("Search index and published municipalities differ")
    return {"ok": True, "scope": manifest["scope"], "datasetVersion": manifest["datasetVersion"],
            "statePackages": len(resources["states"]), "municipalities": len(municipalities),
            "checkedPlaces": checked, "maximumRowError": maximum,
            "resourceBytes": byte_count + resources["search"]["bytes"],
            "schemaValidation": "all bundles" if deep_schema else "manifest, BR and MG; semantic checks on every bundle"}


def _expected_rows(observed: np.ndarray, flows: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> list[dict]:
    """Rows recomputed from run arrays, independently of the exporter's row builder."""
    rows = []
    for index, origin in enumerate(ORIGIN_IDS):
        cell = flows[:, index]
        rows.append({"originId": origin, "observed": float(observed[index]),
                     "estimated": {key: float(cell[0, column]) for column, key in enumerate(DESTINATIONS)},
                     "sensitivity": {key: {"min": float(cell[:, column].min()), "max": float(cell[:, column].max())}
                                     for column, key in enumerate(DESTINATIONS[:2])},
                     "identificationBounds": {key: {"min": float(lower[index, column]), "max": float(upper[index, column])}
                                              for column, key in enumerate(DESTINATIONS[:2])}})
    return rows


def _compare_rows(published: list[dict], expected: list[dict], place: str, tolerance: float = 1e-6) -> None:
    def values(rows):
        for row in rows:
            yield row["originId"], "observed", row["observed"]
            for key in DESTINATIONS:
                yield row["originId"], key, row["estimated"][key]
            for field in ("sensitivity", "identificationBounds"):
                for key in ("lula", "flavio"):
                    for end in ("min", "max"):
                        yield row["originId"], f"{field}.{key}.{end}", row[field][key][end]
    for (origin, field, value), (_, _, reference) in zip(values(published), values(expected), strict=True):
        if abs(value - reference) > tolerance:
            raise ValueError(f"{place} {origin}.{field} differs from the analysis run: {value} != {reference}")


def verify_against_run(root: Path, run_directory: Path, raw_root: Path | None = None) -> dict:
    """Check a release against the run it claims to come from.

    Every published row is recomputed from the run's arrays with code separate
    from the exporter. When raw inputs are available, the release is also
    exported again and every resource must be byte-identical, which covers
    names, IBGE codes and geometry.
    """
    from elections.analysis.run import AnalysisResults

    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    results = AnalysisResults.load(run_directory)
    provenance = manifest["provenance"]
    if provenance.get("runId") != results.metadata["runId"] or provenance.get("resultsSha256") != results.metadata["resultsSha256"]:
        raise ValueError("Release provenance does not identify this analysis run")
    observed, flows = results.observed, results.flows
    states = results.municipality_state
    state_observed = np.zeros((len(results.state_ids), observed.shape[1]))
    np.add.at(state_observed, states, observed)
    state_flows = results.state_flows()
    expected = {"BR": _expected_rows(observed.sum(0), flows.sum(1), results.national_bounds_lower, results.national_bounds_upper)}
    for index, state in enumerate(results.state_ids.tolist()):
        expected[state] = _expected_rows(state_observed[index], state_flows[:, index], results.state_bounds_lower[index],
                                         results.state_bounds_upper[index])
    for index, municipality in enumerate(results.municipality_ids.tolist()):
        expected[municipality] = _expected_rows(observed[index], flows[:, index], results.bounds_lower[index],
                                                results.bounds_upper[index])
    checked = set()
    resources = manifest["resources"]
    for key, descriptor in [("BR", resources["national"]), *resources["states"].items()]:
        bundle = read_resource(root, descriptor)
        for place in [bundle["place"], *bundle["children"]]:
            _compare_rows(place["rows"], expected[place["id"]], place["id"])
            checked.add(place["id"])
    report = {"run": results.metadata["runId"], "placesCompared": len(checked)}
    if raw_root is not None:
        import tempfile
        from elections.export.release import export_release
        with tempfile.TemporaryDirectory() as directory:
            again = Path(directory) / "release"
            export_release(run_directory, raw_root, again, fixture=manifest["scope"] == "fixture")
            regenerated = json.loads((again / "manifest.json").read_text())["resources"]
            published = [("national", resources["national"]), ("search", resources["search"]),
                         *[(f"states/{key}", value) for key, value in resources["states"].items()]]
            expected_resources = {"national": regenerated["national"], "search": regenerated["search"],
                                  **{f"states/{key}": value for key, value in regenerated["states"].items()}}
            for key, descriptor in published:
                if expected_resources.get(key, {}).get("sha256") != descriptor["sha256"]:
                    raise ValueError(f"Resource {key} differs from a fresh export of the run")
        report["resourcesRegenerated"] = len(published)
    return report
