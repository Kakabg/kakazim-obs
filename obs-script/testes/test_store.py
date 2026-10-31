"""Histórico de atividades e chat (SQLite em data/painel.db - aqui numa
pasta temporária, ver testes/base.py)."""

import time
import unittest

from testes import base  # noqa: F401

from kakazim_panel import store


def _agora_ms():
    return int(time.time() * 1000)


class TesteStore(unittest.TestCase):
    def test_atividades_paginam_do_mais_novo_pro_mais_velho(self):
        base_ms = _agora_ms()
        for i in range(5):
            store.adicionar_atividade(
                {"id": f"pag-{i}", "timestamp": base_ms + i, "plataforma": "twitch", "tipo": "seguidor", "usuario": f"u{i}"}
            )
        pagina = store.listar_atividades_pagina(limite=2)
        self.assertEqual([a["id"] for a in pagina], ["pag-4", "pag-3"])
        seguinte = store.listar_atividades_pagina(antes_de=pagina[-1]["timestamp"], limite=2)
        self.assertEqual([a["id"] for a in seguinte], ["pag-2", "pag-1"])

    def test_recentes_vem_em_ordem_crescente(self):
        base_ms = _agora_ms() + 10**12  # bem no futuro: sempre os 2 mais novos
        store.adicionar_atividade({"id": "rec-a", "timestamp": base_ms, "tipo": "outro"})
        store.adicionar_atividade({"id": "rec-b", "timestamp": base_ms + 1, "tipo": "outro"})
        ids = [a["id"] for a in store.listar_atividades_recentes(limite=2)]
        self.assertEqual(ids, ["rec-a", "rec-b"])

    def test_mesmo_id_nao_duplica(self):
        ts = _agora_ms() + 20_000
        store.adicionar_atividade({"id": "dup", "timestamp": ts, "tipo": "outro", "detalhe": "1"})
        store.adicionar_atividade({"id": "dup", "timestamp": ts, "tipo": "outro", "detalhe": "2"})
        itens = [a for a in store.listar_atividades_pagina(limite=500) if a["id"] == "dup"]
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["detalhe"], "2")

    def test_ultimo_sub_follow_ignora_outros_tipos(self):
        ts = _agora_ms() + 30_000
        store.adicionar_atividade({"id": "sf-1", "timestamp": ts, "tipo": "inscricao"})
        store.adicionar_atividade({"id": "sf-2", "timestamp": ts + 1, "tipo": "pix"})
        self.assertEqual(store.buscar_ultimo_sub_follow()["id"], "sf-1")

    def test_chat_guarda_sub_como_booleano(self):
        ts = _agora_ms() + 40_000
        store.adicionar_chat({"id": "c1", "timestamp": ts, "usuario": "a", "mensagem": "oi", "sub": 1})
        item = [c for c in store.listar_chat_pagina(limite=500) if c["id"] == "c1"][0]
        self.assertIs(item["sub"], True)

    def test_poda_apaga_so_chat_velho(self):
        velho = _agora_ms() - 72 * 60 * 60 * 1000
        store.adicionar_chat({"id": "velho", "timestamp": velho, "mensagem": "x"})
        store.adicionar_chat({"id": "novo", "timestamp": _agora_ms(), "mensagem": "y"})
        store.adicionar_atividade({"id": "ativ-velha", "timestamp": velho, "tipo": "outro"})
        store.podar_chat_antigo()
        ids_chat = {c["id"] for c in store.listar_chat_pagina(limite=500)}
        self.assertNotIn("velho", ids_chat)
        self.assertIn("novo", ids_chat)
        ids_ativ = {a["id"] for a in store.listar_atividades_pagina(limite=500)}
        self.assertIn("ativ-velha", ids_ativ)

    def test_seguidores_kick(self):
        store.definir_total_seguidores_kick(10)
        store.incrementar_seguidores_kick()
        self.assertEqual(store.buscar_kick()["followerTotal"], 11)


if __name__ == "__main__":
    unittest.main()
