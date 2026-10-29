"""Origin, destination, and geography identifiers shared by analysis and export.

Analysis arrays use the column order defined here. Labels are reader-facing
Portuguese; identifiers are stable English keys used by the public contract.
"""
from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = "2.0"
ELECTION_YEAR = 2026


@dataclass(frozen=True)
class Origin:
    id: str
    label: str
    short_label: str
    kind: str
    ballot_number: int | None = None
    ballot_name: str | None = None


# First-round presidential ballot numbers and TSE ballot names, verified against
# consulta_cand when the panel is built. Number 28 (PRTB) was totaled as a
# technical null; it is kept as a separate origin rather than merged with nulls.
ORIGINS = (
    Origin("lula", "Lula", "L", "candidate", 13, "LULA"),
    Origin("flavio", "Flávio Bolsonaro", "FB", "candidate", 22, "FLAVIO BOLSONARO"),
    Origin("augusto_cury", "Augusto Cury", "AC", "candidate", 70, "ESCRITOR AUGUSTO CURY"),
    Origin("renan_santos", "Renan Santos", "RS", "candidate", 14, "RENAN SANTOS"),
    Origin("ronaldo_caiado", "Ronaldo Caiado", "RC", "candidate", 55, "RONALDO CAIADO"),
    Origin("romeu_zema", "Romeu Zema", "RZ", "candidate", 30, "ZEMA"),
    Origin("samara_martins", "Samara Martins", "SM", "candidate", 80, "SAMARA"),
    Origin("hertz_dias", "Hertz Dias", "HD", "candidate", 16, "HERTZ DIAS"),
    Origin("clariana_barao", "Clariana Barão", "CB", "candidate", 27, "CLARIANA BARAO"),
    Origin("edmilson_costa", "Edmilson Costa", "EC", "candidate", 21, "EDMILSON COSTA"),
    Origin("wilson_grassi", "Wilson Grassi", "WG", "candidate", 35, "VETERINÁRIO WILSON GRASSI"),
    Origin("rui_costa_pimenta", "Rui Costa Pimenta", "RP", "candidate", 29, "RUI COSTA PIMENTA"),
    Origin("blank", "Brancos", "B", "blank", 95),
    Origin("null_ballot", "Nulos na urna", "N", "null", 96),
    Origin("null_technical", "Nulos técnicos (código 28)", "N", "null", 28),
    Origin("abstention", "Abstenção", "A", "abstention"),
)
ORIGIN_IDS = tuple(origin.id for origin in ORIGINS)
CANDIDATES = tuple(origin for origin in ORIGINS if origin.kind == "candidate")
FINALIST_NUMBERS = (13, 22)
BLANK_NUMBER, NULL_NUMBER, TECHNICAL_NULL_NUMBER = 95, 96, 28

DESTINATIONS = (("lula", "Lula"), ("flavio", "Flávio"), ("blank", "Brancos"), ("null", "Nulos"),
                ("abstention", "Abstenção"))
DESTINATION_IDS = tuple(key for key, _ in DESTINATIONS)

# Display groups: eliminated candidates, blank, combined nulls, abstention.
DISPLAY_GROUPS = tuple(
    [(origin.id, origin.label, origin.short_label, (origin.id,)) for origin in ORIGINS[2:13]]
    + [("null", "Nulos", "N", ("null_ballot", "null_technical")),
       ("abstention", "Abstenção", "A", ("abstention",))]
)

STATE_NAMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí",
    "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul",
    "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins", "ZZ": "Exterior",
}
ABROAD = "ZZ"
BRAZILIAN_MUNICIPALITIES = 5571
