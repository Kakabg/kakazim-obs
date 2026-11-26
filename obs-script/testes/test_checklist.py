"""Checklist antes da live (kakazim_panel/checklist.py) - regras puras, sem OBS."""

import unittest

from testes import base  # noqa: F401

from kakazim_panel import checklist

AGORA = 10_000_000


def mic(nome="Mic", aparelho="A", mudo=False, ativo=True, global_=False):
    return {"nome": nome, "aparelho": aparelho, "mudo": mudo, "ativo": ativo, "global": global_}


def item(itens, chave):
    return next(i for i in itens if i["chave"] == chave)


class TestChecklist(unittest.TestCase):
    def avaliar(self, fontes, conhecidos=None, estado=None, bot=AGORA):
        return checklist.avaliar(fontes, conhecidos or {}, estado or {}, bot, agora_ms=AGORA)

    def test_microfone_ok(self):
        m = item(self.avaliar([mic(), mic("Webcam", ativo=False)], {"Mic": "A"}), "microfone")
        self.assertTrue(m["ok"])

    def test_sem_leitura_ainda(self):
        self.assertIsNone(item(self.avaliar(None), "microfone")["ok"])

    def test_mic_global_ligado(self):
        m = item(self.avaliar([mic(), mic("Mic/Aux", global_=True)]), "microfone")
        self.assertFalse(m["ok"])
        self.assertEqual(m["texto"], "Mic global ligado")

    def test_dois_microfones_na_cena(self):
        m = item(self.avaliar([mic(), mic("Webcam")]), "microfone")
        self.assertEqual(m["texto"], "2 microfones na cena")

    def test_sem_microfone_na_cena(self):
        self.assertEqual(item(self.avaliar([mic(ativo=False)]), "microfone")["texto"], "Sem microfone na cena")

    def test_mudo(self):
        self.assertEqual(item(self.avaliar([mic(mudo=True)]), "microfone")["texto"], "Microfone no mudo")

    def test_trocou_de_aparelho(self):
        m = item(self.avaliar([mic(aparelho="B")], {"Mic": "A"}), "microfone")
        self.assertEqual(m["texto"], "Microfone trocou de aparelho")

    def test_servicos(self):
        estado = {"twitch": {"atualizadoEm": AGORA - 1000}, "kick": {"atualizadoEm": AGORA - 10 * 60 * 1000}}
        itens = self.avaliar([mic()], estado=estado, bot=AGORA - 5 * 60 * 1000)
        self.assertTrue(item(itens, "twitch")["ok"])
        self.assertFalse(item(itens, "kick")["ok"])
        self.assertFalse(item(itens, "bot")["ok"])
        self.assertIsNone(item(self.avaliar([mic()], bot=None), "bot")["ok"])


if __name__ == "__main__":
    unittest.main()
