"""Column-selecting readers for TSE open-data archives; counts are never altered."""
from __future__ import annotations

from pathlib import Path
import zipfile

import pandas as pd

SECTION_KEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]
PRESIDENT = 1


def read_member(archive: Path, member: str, **options) -> pd.DataFrame:
    """Read one semicolon-separated Latin-1 CSV member; municipality codes stay strings."""
    dtype = {"CD_MUNICIPIO": str, "CD_MUNICIPIO_ORIGEM": str, "CD_MUNICIPIO_DESTINO": str, **options.pop("dtype", {})}
    with zipfile.ZipFile(archive) as bundle, bundle.open(member) as stream:
        return pd.read_csv(stream, sep=";", encoding="latin1", dtype=dtype, **options)


def section_details(archive: Path) -> pd.DataFrame:
    columns = SECTION_KEY + ["NR_TURNO", "CD_CARGO", "NM_MUNICIPIO", "QT_APTOS", "QT_COMPARECIMENTO",
                             "QT_ABSTENCOES", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS", "ST_SECAO_INSTALADA",
                             "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "DS_LOCAL_VOTACAO_ENDERECO"]
    frame = read_member(archive, "detalhe_votacao_secao_2026_BR.csv", usecols=columns)
    if not frame.CD_CARGO.eq(PRESIDENT).all():
        raise ValueError("Section details contain offices other than president")
    if frame.duplicated(["NR_TURNO"] + SECTION_KEY).any():
        raise ValueError("Section details contain duplicated section records")
    return frame


def section_votes(archive: Path, chunksize: int = 1_000_000) -> pd.Series:
    """Votes summed by round, section and ballot number."""
    columns = SECTION_KEY + ["NR_TURNO", "CD_CARGO", "NR_VOTAVEL", "QT_VOTOS"]
    pieces = []
    with zipfile.ZipFile(archive) as bundle, bundle.open("votacao_secao_2026_BR.csv") as stream:
        for chunk in pd.read_csv(stream, sep=";", encoding="latin1", usecols=columns, chunksize=chunksize,
                                 dtype={"CD_MUNICIPIO": str}):
            if not chunk.CD_CARGO.eq(PRESIDENT).all():
                raise ValueError("Vote records contain offices other than president")
            pieces.append(chunk.groupby(["NR_TURNO"] + SECTION_KEY + ["NR_VOTAVEL"]).QT_VOTOS.sum())
    return pd.concat(pieces).groupby(level=list(range(6))).sum()


def presidential_candidates(archive: Path, complementary: Path) -> pd.DataFrame:
    """Presidential candidacies with the vote destination type used in the totals."""
    frame = read_member(archive, "consulta_cand_2026_BR.csv", dtype={"NR_CANDIDATO": int, "SQ_CANDIDATO": str})
    frame = frame[frame.DS_CARGO.str.upper().eq("PRESIDENTE")]
    extra = read_member(complementary, "consulta_cand_complementar_2026_BR.csv", dtype={"SQ_CANDIDATO": str},
                        usecols=["SQ_CANDIDATO", "NM_TIPO_DESTINACAO_VOTOS"]).drop_duplicates()
    if extra.SQ_CANDIDATO.duplicated().any():
        raise ValueError("A candidacy has several vote destination types")
    merged = frame.merge(extra, on="SQ_CANDIDATO", how="left", validate="many_to_one")
    return merged[["NR_TURNO", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "NM_TIPO_DESTINACAO_VOTOS"]]


def temporary_transfers(archive: Path) -> pd.DataFrame:
    return read_member(archive, "transf_temporaria_secao_2026.csv")
