"""Section panel: first-round origins and second-round destinations per polling section.

The panel keeps sections installed in both rounds. Rows are sections in the
official key order (state, municipality code as text, zone, section). Every
count is copied from TSE files and cross-checked against independent totals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from elections.sources import tse
from elections.sources.registry import SourceFile, load_registry, verify_sources
from elections.taxonomy import (BLANK_NUMBER, CANDIDATES, NULL_NUMBER, ORIGIN_IDS,
                                   TECHNICAL_NULL_NUMBER)

PANEL_VERSION = "panel-2"
FOLDS = 5
KEY = tse.SECTION_KEY
SOURCES = ("tse-section-votes", "tse-section-details", "tse-temporary-transfers", "tse-candidates",
           "tse-candidates-complementary")
MISSING_TEXT = {"", "#NULO", "#NE", "-1", "-3"}
ARRAYS = ("x", "y", "n1", "n2", "state", "municipality", "component", "fold", "incoming", "outgoing",
          "incoming_registry", "outgoing_registry", "state_ids", "municipality_ids", "municipality_state",
          "municipality_names", "section_zone", "section_number")


@dataclass
class SectionPanel:
    """Per-section counts; columns follow taxonomy.ORIGIN_IDS and DESTINATION_IDS."""

    x: np.ndarray
    y: np.ndarray
    n1: np.ndarray
    n2: np.ndarray
    state: np.ndarray
    municipality: np.ndarray
    component: np.ndarray
    fold: np.ndarray
    incoming: np.ndarray
    outgoing: np.ndarray
    incoming_registry: np.ndarray
    outgoing_registry: np.ndarray
    state_ids: np.ndarray
    municipality_ids: np.ndarray
    municipality_state: np.ndarray
    municipality_names: np.ndarray
    section_zone: np.ndarray
    section_number: np.ndarray
    metadata: dict = field(default_factory=dict)

    @property
    def sections(self) -> int:
        return len(self.x)

    def mobility(self, mode: str, turnover: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        """Incoming and outgoing voters per section under a declared mobility scenario."""
        if mode == "net":
            incoming, outgoing = self.incoming, self.outgoing
        elif mode == "registry":
            incoming, outgoing = self.incoming_registry, self.outgoing_registry
        else:
            raise ValueError(f"Unknown mobility mode: {mode}")
        if turnover:
            extra = turnover * np.minimum(self.n1, self.n2)
            incoming, outgoing = incoming + extra, outgoing + extra
        return incoming, outgoing

    def digest(self) -> str:
        return array_digest({name: getattr(self, name) for name in ARRAYS})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **{name: getattr(self, name) for name in ARRAYS})
        metadata = {**self.metadata, "arraysSha256": self.digest()}
        path.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> "SectionPanel":
        with np.load(path, allow_pickle=False) as arrays:
            values = {name: arrays[name] for name in ARRAYS}
        metadata = json.loads(path.with_suffix(".json").read_text())
        panel = cls(**values, metadata={key: value for key, value in metadata.items() if key != "arraysSha256"})
        if metadata.get("arraysSha256") != panel.digest():
            raise ValueError(f"Cached panel {path} does not match its recorded digest")
        return panel


def array_digest(arrays: dict[str, np.ndarray]) -> str:
    """Content digest of named arrays: name, dtype, shape and bytes, in the given order."""
    digest = hashlib.sha256()
    for name, value in arrays.items():
        value = np.ascontiguousarray(value)
        digest.update(json.dumps([name, value.dtype.str, value.shape]).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def _origin_columns() -> dict[int, int]:
    columns = {origin.ballot_number: index for index, origin in enumerate(CANDIDATES)}
    columns.update({BLANK_NUMBER: ORIGIN_IDS.index("blank"), NULL_NUMBER: ORIGIN_IDS.index("null_ballot"),
                    TECHNICAL_NULL_NUMBER: ORIGIN_IDS.index("null_technical")})
    return columns


def verify_candidates(candidates: pd.DataFrame) -> None:
    """Match ballot numbers to registered names and to their vote destination type.

    Each analysis candidate must be a single valid-vote candidacy. Ballot 28 must
    have been totaled as a technical null and as nothing else.
    """
    first_round = candidates[candidates.NR_TURNO.eq(1)]
    for origin in CANDIDATES:
        rows = first_round[first_round.NR_CANDIDATO.eq(origin.ballot_number)]
        if set(rows.NM_URNA_CANDIDATO) != {origin.ballot_name}:
            raise ValueError(f"Ballot {origin.ballot_number} is registered as {sorted(set(rows.NM_URNA_CANDIDATO))}, "
                             f"expected {origin.ballot_name}")
        if set(rows.NM_TIPO_DESTINACAO_VOTOS) != {"Válido"}:
            raise ValueError(f"Ballot {origin.ballot_number} is not a valid-vote candidacy")
    finalists = set(candidates.loc[candidates.NR_TURNO.eq(2), "NR_CANDIDATO"])
    if finalists != {13, 22}:
        raise ValueError(f"Unexpected second-round candidates: {sorted(finalists)}")
    technical = set(first_round.loc[first_round.NR_CANDIDATO.eq(TECHNICAL_NULL_NUMBER), "NM_TIPO_DESTINACAO_VOTOS"])
    if "Nulo técnico" not in technical or "Válido" in technical:
        raise ValueError(f"Ballot {TECHNICAL_NULL_NUMBER} was not totaled only as a technical null: {sorted(technical)}")
    numbers = set(first_round.NR_CANDIDATO)
    expected = {origin.ballot_number for origin in CANDIDATES} | {TECHNICAL_NULL_NUMBER}
    if numbers != expected:
        raise ValueError(f"Unexpected first-round ballot numbers: {sorted(numbers ^ expected)}")


def _place_folds(first: pd.DataFrame, second: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, dict]:
    """Validation folds that never split polling places linked across rounds.

    Each section first takes a fold from a hash of its first-round polling place.
    Places are then joined into connected components through identical place
    codes in both rounds and identical name plus address strings within a
    municipality. A component inherits the fold of its first section in key order.
    """
    frames = [first.reset_index(), second.reset_index()]
    places, addresses, unreliable = [], [], []
    for turn, frame in enumerate(frames, 1):
        prefix = frame.SG_UF + ":" + frame.CD_MUNICIPIO + ":"
        places.append((prefix + frame.NR_ZONA.astype(str) + ":" + frame.NR_LOCAL_VOTACAO.astype(str)).to_numpy(str))
        name = frame.NM_LOCAL_VOTACAO.fillna("").str.strip().str.upper()
        address = frame.DS_LOCAL_VOTACAO_ENDERECO.fillna("").str.strip().str.upper()
        missing = (name.isin(MISSING_TEXT) | address.isin(MISSING_TEXT)).to_numpy()
        text = (prefix + name + "|" + address).to_numpy(object)
        text[missing] = [f"__unreliable_address__{turn}_{index}" for index in np.flatnonzero(missing)]
        addresses.append(text.astype(str))
        unreliable.append(int(missing.sum()))
    initial = np.array([int(hashlib.sha256(name.encode()).hexdigest()[:8], 16) % FOLDS for name in places[0]])
    place_codes, _ = pd.factorize(np.concatenate(places))
    address_codes, _ = pd.factorize(np.concatenate(addresses))
    n = len(first)
    place1, place2 = place_codes[:n], place_codes[n:]
    address1, address2 = address_codes[:n], address_codes[n:]
    offset = int(place_codes.max()) + 1
    nodes = offset + int(address_codes.max()) + 1
    left = np.concatenate([place1, place1, place1])
    right = np.concatenate([place2, offset + address1, offset + address2])
    graph = coo_matrix((np.ones(len(left)), (left, right)), shape=(nodes, nodes)).tocsr()
    _, labels = connected_components(graph, directed=False)
    _, first_index, component = np.unique(labels[place1], return_index=True, return_inverse=True)
    fold = initial[first_index][component]
    for codes in ((place1, place2), (address1, address2)):
        identifiers = np.concatenate(codes)
        repeated = np.tile(fold, 2)
        low = np.full(identifiers.max() + 1, FOLDS)
        high = np.full(identifiers.max() + 1, -1)
        np.minimum.at(low, identifiers, repeated)
        np.maximum.at(high, identifiers, repeated)
        used = high >= 0
        if not np.array_equal(low[used], high[used]):
            raise AssertionError("A linked polling place spans validation folds")
    summary = {"components": int(len(first_index)), "sectionsMovedFromInitialFold": int(np.count_nonzero(fold != initial)),
               "unreliableAddresses": unreliable, "foldSections": np.bincount(fold, minlength=FOLDS).tolist()}
    return component.astype(np.int64), fold.astype(np.int64), summary


def _registry_mobility(transfers: pd.DataFrame, ids: pd.MultiIndex, delta: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """Mobility scenario informed by the temporary-transfer registry.

    Changes in registered transfers between rounds are attributed to their
    destination sections; voters returning home enter their registered section.
    Returns home and new departures from the same home section are netted, so
    the scenario counts net changes per section rather than every registered
    movement.
    Residuals needed to match each section's electorate change are added as
    unexplained entries or exits. No individual voter is identified.
    """
    home = [column + "_ORIGEM" for column in KEY]
    away = [column + "_DESTINO" for column in KEY]
    edges = transfers.groupby(home + away + ["NR_TURNO"]).QT_ELEITOR.sum().unstack("NR_TURNO", fill_value=0)
    edges["delta"] = edges.get(2, 0) - edges.get(1, 0)
    edges = edges[edges.delta.ne(0)].reset_index()
    returning = (-edges.groupby(home).delta.sum()).rename("delta").reset_index()
    for source, target in zip(home, away):
        returning[target] = returning[source]
    changes = pd.concat([edges[home + away + ["delta"]], returning[home + away + ["delta"]]])
    changes = changes.groupby(home + away).delta.sum().reset_index()
    changes["incoming"] = changes.delta.clip(lower=0)
    changes["outgoing"] = (-changes.delta).clip(lower=0)
    by_section = changes.groupby(away)[["incoming", "outgoing"]].sum()
    by_section.index.names = KEY
    known = by_section.reindex(ids, fill_value=0)
    incoming = known.incoming.to_numpy(float)
    outgoing = known.outgoing.to_numpy(float)
    residual = delta - incoming + outgoing
    incoming = incoming + np.maximum(residual, 0)
    outgoing = outgoing + np.maximum(-residual, 0)
    summary = {"registrySectionsNotInPanel": int(len(by_section.index.difference(ids))),
               "absoluteResidualAdded": float(np.abs(residual).sum())}
    return incoming, outgoing, summary


def build_panel(raw_root: Path, registry: dict[str, SourceFile] | None = None) -> SectionPanel:
    registry = registry or load_registry()
    hashes = verify_sources(raw_root, {key: registry[key] for key in SOURCES})
    path = {key: raw_root / registry[key].path for key in SOURCES}
    verify_candidates(tse.presidential_candidates(path["tse-candidates"], path["tse-candidates-complementary"]))

    details = tse.section_details(path["tse-section-details"])
    first = details[details.NR_TURNO.eq(1)].set_index(KEY).sort_index()
    second = details[details.NR_TURNO.eq(2)].set_index(KEY).sort_index()
    if not first.index.equals(second.index):
        raise ValueError("The two rounds list different sections")
    installed = first.ST_SECAO_INSTALADA.eq("Sim") & second.ST_SECAO_INSTALADA.eq("Sim")
    excluded = {"sections": int((~installed).sum()), "electorateFirstRound": int(first.QT_APTOS[~installed].sum()),
                "electorateSecondRound": int(second.QT_APTOS[~installed].sum())}
    first, second = first[installed], second[installed]
    ids = first.index

    columns = _origin_columns()
    votes = tse.section_votes(path["tse-section-votes"])
    numbers = set(votes.index.get_level_values("NR_VOTAVEL"))
    if not numbers <= set(columns):
        raise ValueError(f"Unmapped ballot numbers: {sorted(numbers - set(columns))}")
    by_column = votes.rename(index=columns, level="NR_VOTAVEL").groupby(level=list(range(6))).sum()
    by_column = by_column.unstack("NR_VOTAVEL", fill_value=0)
    round1 = by_column.xs(1, level="NR_TURNO").reindex(index=ids, columns=range(15), fill_value=0).to_numpy(np.int64)
    round2 = by_column.xs(2, level="NR_TURNO").reindex(index=ids, columns=range(15), fill_value=0).to_numpy(np.int64)
    blank, null, technical = (ORIGIN_IDS.index(name) for name in ("blank", "null_ballot", "null_technical"))
    for votes_by_round, frame, label in ((round1, first, "first"), (round2, second, "second")):
        if not np.array_equal(votes_by_round.sum(1), frame.QT_COMPARECIMENTO.to_numpy()):
            raise ValueError(f"Votes differ from turnout in the {label} round")
        if not (np.array_equal(votes_by_round[:, blank], frame.QT_VOTOS_BRANCOS.to_numpy())
                and np.array_equal(votes_by_round[:, null], frame.QT_VOTOS_NULOS.to_numpy())):
            raise ValueError(f"Blank or null votes differ from section details in the {label} round")
    if round2[:, 2:12].any() or round2[:, technical].any():
        raise ValueError("Second-round records contain eliminated candidates or technical nulls")
    x = np.column_stack([round1, first.QT_ABSTENCOES.to_numpy()]).astype(float)
    y = np.column_stack([round2[:, [0, 1, blank, null]], second.QT_ABSTENCOES.to_numpy()]).astype(float)
    n1, n2 = first.QT_APTOS.to_numpy(float), second.QT_APTOS.to_numpy(float)
    if not (np.array_equal(x.sum(1), n1) and np.array_equal(y.sum(1), n2)):
        raise ValueError("Origins or destinations do not add up to the electorate")
    if (n1 <= 0).any() or (n2 <= 0).any():
        raise ValueError("An installed section has an empty electorate")

    states = ids.get_level_values("SG_UF").to_numpy(str)
    municipality_keys = np.char.add(np.char.add(states, ":"), ids.get_level_values("CD_MUNICIPIO").to_numpy(str))
    state, state_ids = pd.factorize(states, sort=True)
    municipality, municipality_ids = pd.factorize(municipality_keys, sort=True)
    municipality_state = np.zeros(len(municipality_ids), dtype=np.int64)
    municipality_state[municipality] = state
    names = pd.Series(first.NM_MUNICIPIO.to_numpy(str)).groupby(municipality).unique()
    if names.map(len).ne(1).any():
        raise ValueError("A municipality code has several names")
    component, fold, partition = _place_folds(first, second)

    delta = n2 - n1
    incoming_registry, outgoing_registry, registry_summary = _registry_mobility(
        tse.temporary_transfers(path["tse-temporary-transfers"]), ids, delta)
    if (outgoing_registry > n1).any() or (incoming_registry > n2).any():
        raise ValueError("Registry mobility exceeds a section electorate")

    metadata = {
        "panelVersion": PANEL_VERSION, "sourceSha256": hashes, "sections": int(len(x)),
        "municipalities": int(len(municipality_ids)), "states": int(len(state_ids)),
        "excludedNotInstalled": excluded,
        "electorateFirstRound": int(n1.sum()), "electorateSecondRound": int(n2.sum()),
        "originTotals": dict(zip(ORIGIN_IDS, x.sum(0).tolist())),
        "destinationTotals": dict(zip(["lula", "flavio", "blank", "null", "abstention"], y.sum(0).tolist())),
        "sectionsWithElectorateChange": int(np.count_nonzero(delta)),
        "netMovers": float(np.maximum(delta, 0).sum()),
        "registryMovers": float(incoming_registry.sum()), **registry_summary,
        "validationPartition": partition,
    }
    return SectionPanel(
        x=x, y=y, n1=n1, n2=n2, state=state.astype(np.int64), municipality=municipality.astype(np.int64),
        component=component, fold=fold, incoming=np.maximum(delta, 0), outgoing=np.maximum(-delta, 0),
        incoming_registry=incoming_registry, outgoing_registry=outgoing_registry,
        state_ids=np.asarray(state_ids, dtype=str), municipality_ids=np.asarray(municipality_ids, dtype=str),
        municipality_state=municipality_state, municipality_names=np.array([value[0] for value in names], dtype=str),
        section_zone=ids.get_level_values("NR_ZONA").to_numpy(np.int64),
        section_number=ids.get_level_values("NR_SECAO").to_numpy(np.int64), metadata=metadata)
