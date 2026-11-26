import unittest

from testes import base  # noqa: F401
from kakazim_panel import livepix


class TestLivePix(unittest.TestCase):
    def test_valor_em_centavos(self):
        self.assertEqual(livepix.formatar_valor(1000), "R$ 10,00")
        self.assertEqual(livepix.formatar_valor(123456), "R$ 1.234,56")
        self.assertIsNone(livepix.formatar_valor(None))

    def test_doacao_com_mensagem(self):
        item = livepix.montar_atividade(
            "livepix.message.new", {"username": "fulano", "message": " valeu ", "amount": 500, "currency": "BRL"}
        )
        self.assertEqual(item, {"plataforma": "livepix", "tipo": "doacao", "usuario": "fulano", "detalhe": "R$ 5,00: valeu"})

    def test_aceita_objeto_dentro_de_data(self):
        item = livepix.montar_atividade("livepix.message.new", {"data": {"username": "x", "amount": 200}})
        self.assertEqual(item["detalhe"], "R$ 2,00")
        self.assertEqual(item["usuario"], "x")

    def test_pagamento_nao_duplica(self):
        self.assertIsNone(livepix.montar_atividade("livepix.payment.new", {"amount": 500}))

    def test_assinatura(self):
        item = livepix.montar_atividade("livepix.subscription.new", {"username": "y"})
        self.assertEqual(item["tipo"], "inscricao")


if __name__ == "__main__":
    unittest.main()
