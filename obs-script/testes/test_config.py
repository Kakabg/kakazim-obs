import unittest

from testes import base  # noqa: F401

from kakazim_panel import config


class TesteConfig(unittest.TestCase):
    def setUp(self):
        self._original = config.obter_tudo()

    def tearDown(self):
        config.atualizar(self._original)

    def test_padroes_tem_porta_8420(self):
        self.assertEqual(config.PADROES["porta"], 8420)

    def test_chave_desconhecida_e_recusada(self):
        with self.assertRaises(KeyError):
            config.atualizar({"chave_que_nao_existe": "x"})

    def test_atualizar_e_obter(self):
        config.atualizar({"twitch_broadcaster_login": "canal_teste"})
        self.assertEqual(config.obter("twitch_broadcaster_login"), "canal_teste")

    def test_obter_tudo_devolve_copia(self):
        tudo = config.obter_tudo()
        tudo["porta"] = 1
        self.assertNotEqual(config.obter("porta"), 1)

    def test_url_base_do_bot_vem_do_relay(self):
        self.assertEqual(config.url_base_kakazim_bot(), "https://kakazim-bot-production.up.railway.app")
        config.atualizar({"kick_relay_url": "https://outro.exemplo.com/painel/eventos"})
        self.assertEqual(config.url_base_kakazim_bot(), "https://outro.exemplo.com")


if __name__ == "__main__":
    unittest.main()
