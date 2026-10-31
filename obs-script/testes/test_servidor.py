"""Sobe o servidor do painel numa porta livre (sem iniciar o hub, ou seja,
sem falar com Twitch/Kick) e confere que a página e as rotas básicas
respondem."""

import json
import socket
import unittest
import urllib.error
import urllib.request

from testes import base  # noqa: F401

from kakazim_panel import config
from kakazim_panel.http_server import ServidorHttp


def _porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TesteServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._porta_original = config.obter("porta")
        porta = _porta_livre()
        config.atualizar({"porta": porta})
        cls.url = f"http://127.0.0.1:{porta}"
        cls.servidor = ServidorHttp()
        cls.servidor.iniciar()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()
        config.atualizar({"porta": cls._porta_original})

    def _get(self, caminho):
        with urllib.request.urlopen(self.url + caminho, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()

    def test_pagina_principal(self):
        status, cabecalhos, corpo = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", cabecalhos.get("Content-Type", ""))
        self.assertIn(b"<html", corpo.lower())

    def test_arquivos_estaticos(self):
        for caminho in ("/app.js", "/style.css", "/vendor/tabler-icons/brand-kick.svg"):
            with self.subTest(caminho=caminho):
                status, _, corpo = self._get(caminho)
                self.assertEqual(status, 200)
                self.assertGreater(len(corpo), 0)

    def test_historico_de_atividades_responde_json(self):
        status, _, corpo = self._get("/api/atividades")
        self.assertEqual(status, 200)
        json.loads(corpo)

    def test_rota_desconhecida_da_404(self):
        with self.assertRaises(urllib.error.HTTPError) as contexto:
            self._get("/nao-existe")
        self.assertEqual(contexto.exception.code, 404)

    def test_nao_sai_da_pasta_publica(self):
        # Tentativa de ler arquivo fora de public/ via /vendor/../..
        with self.assertRaises(urllib.error.HTTPError) as contexto:
            self._get("/vendor/../../kakazim_panel/config.py")
        self.assertIn(contexto.exception.code, (400, 403, 404))


if __name__ == "__main__":
    unittest.main()
