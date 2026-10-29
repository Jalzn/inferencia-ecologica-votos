"""Panel construction from verbatim TSE rows and the TSE-IBGE municipality link."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from elections.preparation.geography import link_municipalities, normalize_name
from elections.preparation.panel import build_panel, verify_candidates
from elections.sources import tse
from elections.sources.registry import load_registry, verify_sources

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data/fixtures/tse"


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(FIXTURE / "sources.json")
        cls.panel = build_panel(FIXTURE, cls.registry)

    def test_real_fixture_rows_keep_every_origin_and_destination(self):
        panel = self.panel
        self.assertEqual(panel.sections, 18)
        self.assertEqual(panel.municipality_ids.tolist(), ["MG:40614", "MG:40657"])
        self.assertEqual(panel.municipality_names.tolist(), ["ANTÔNIO PRADO DE MINAS", "ARACITABA"])
        np.testing.assert_array_equal(panel.x.sum(axis=1), panel.n1)
        np.testing.assert_array_equal(panel.y.sum(axis=1), panel.n2)
        self.assertEqual(panel.x.sum(axis=0).astype(int).tolist(),
                         [1772, 1457, 93, 66, 74, 10, 1, 1, 2, 3, 1, 0, 67, 133, 1, 1073])
        self.assertEqual(panel.y.sum(axis=0).astype(int).tolist(), [2030, 1516, 55, 76, 1080])

    def test_mobility_scenarios_balance_each_section(self):
        panel = self.panel
        for mode in ("net", "registry"):
            incoming, outgoing = panel.mobility(mode)
            np.testing.assert_array_equal(incoming - outgoing, panel.n2 - panel.n1)
            self.assertTrue((outgoing <= panel.n1).all() and (incoming <= panel.n2).all())
        incoming, outgoing = panel.mobility("net", turnover=0.005)
        np.testing.assert_allclose(incoming - outgoing, panel.n2 - panel.n1)
        with self.assertRaises(ValueError):
            panel.mobility("unknown")

    def test_folds_keep_linked_polling_places_together(self):
        panel = self.panel
        for component in np.unique(panel.component):
            self.assertEqual(len(np.unique(panel.fold[panel.component == component])), 1)

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "panel.npz"
            self.panel.save(path)
            loaded = type(self.panel).load(path)
            np.testing.assert_array_equal(loaded.x, self.panel.x)
            self.assertEqual(loaded.metadata, json.loads(json.dumps(self.panel.metadata)))
            self.assertEqual(loaded.digest(), self.panel.digest())
            arrays = dict(np.load(path))
            arrays["x"] = arrays["x"] + 1
            np.savez_compressed(path, **arrays)
            with self.assertRaisesRegex(ValueError, "digest"):
                type(self.panel).load(path)

    def test_candidate_names_are_checked_against_the_registry(self):
        candidates = tse.presidential_candidates(FIXTURE / "consulta_cand_2026.zip",
                                                 FIXTURE / "consulta_cand_complementar_2026.zip")
        verify_candidates(candidates)
        self.assertEqual(set(candidates.loc[candidates.NR_CANDIDATO.eq(28), "NM_TIPO_DESTINACAO_VOTOS"]),
                         {"#NULO", "Nulo técnico"})
        for column, number, value in [("NM_URNA_CANDIDATO", 70, "OUTRO NOME"),
                                      ("NM_TIPO_DESTINACAO_VOTOS", 70, "Nulo técnico"),
                                      ("NM_TIPO_DESTINACAO_VOTOS", 28, "Válido")]:
            changed = candidates.copy()
            changed.loc[changed.NR_CANDIDATO.eq(number), column] = value
            with self.assertRaises(ValueError, msg=(column, number, value)):
                verify_candidates(changed)

    def test_modified_source_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            for entry in self.registry.values():
                shutil.copyfile(FIXTURE / entry.path, copy / entry.path)
            verify_sources(copy, self.registry)
            with (copy / "consulta_cand_2026.zip").open("ab") as stream:
                stream.write(b"\0")
            with self.assertRaises(ValueError):
                verify_sources(copy, self.registry)


class MunicipalityLinkTests(unittest.TestCase):
    @staticmethod
    def entry(code: int, name: str, state: str) -> dict:
        return {"id": code, "nome": name, "regiao-imediata": {"regiao-intermediaria": {"UF": {"sigla": state}}}}

    def test_exact_normalized_names_and_reviewed_aliases(self):
        registry = [self.entry(3100104, "Abadia dos Dourados", "MG"), self.entry(3165206, "São Tomé das Letras", "MG")]
        aliases = {"MG:53031": {"ibgeCode": "3165206", "tseName": "SÃO THOMÉ DAS LETRAS", "ibgeName": "São Tomé das Letras"}}
        links = link_municipalities(["MG:40010", "MG:53031", "ZZ:29386"], ["ABADIA DOS DOURADOS", "SÃO THOMÉ DAS LETRAS", "LISBOA"],
                                    registry, aliases)
        self.assertEqual(links["MG:40010"], {"ibgeCode": "3100104", "name": "Abadia dos Dourados", "method": "normalized-name"})
        self.assertEqual(links["MG:53031"]["method"], "reviewed-alias")
        self.assertNotIn("ZZ:29386", links)
        self.assertEqual(normalize_name("São Tomé-das Letras"), "saotomedasletras")

    def test_unmatched_stale_alias_and_ambiguity_fail(self):
        registry = [self.entry(3100104, "Abadia dos Dourados", "MG")]
        with self.assertRaises(ValueError):
            link_municipalities(["MG:1"], ["OUTRA CIDADE"], registry, {})
        stale = {"MG:1": {"ibgeCode": "3100104", "tseName": "OUTRA", "ibgeName": "Abadia dos Dourados"}}
        with self.assertRaises(ValueError):
            link_municipalities(["MG:1"], ["OUTRA CIDADE"], registry, stale)
        with self.assertRaises(ValueError):
            link_municipalities(["MG:1"], ["X"], registry + [self.entry(3100105, "Abadia  dos Dourados", "MG")], {})


if __name__ == "__main__":
    unittest.main()
