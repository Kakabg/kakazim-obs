import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from testes import base  # noqa: F401

from kakazim_panel import http_util


class _Eco(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _responder(self, status, corpo):
        dados = corpo.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        if self.path == "/erro":
            self._responder(500, "deu ruim")
        elif self.path == "/vazio":
            self._responder(204, "")
        else:
            self._responder(200, json.dumps({"ua": self.headers.get("User-Agent"), "caminho": self.path}))

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        corpo = self.rfile.read(tamanho).decode("utf-8")
        self._responder(200, json.dumps({"tipo": self.headers.get("Content-Type"), "corpo": corpo}))


class TesteHttpUtil(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), _Eco)
        cls.url = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def test_montar_url_ignora_none(self):
        self.assertEqual(http_util.montar_url("https://x.com/a", {"b": 1, "c": None}), "https://x.com/a?b=1")
        self.assertEqual(http_util.montar_url("https://x.com/a", {}), "https://x.com/a")

    def test_user_agent_de_navegador_por_padrao(self):
        # Sem isso a Cloudflare da Kick bloqueia (ver comentário em http_util.py).
        resposta = http_util.requisitar(self.url + "/eco")
        self.assertEqual(resposta["ua"], http_util.USER_AGENT_PADRAO)

    def test_user_agent_explicito_e_respeitado(self):
        resposta = http_util.requisitar(self.url + "/eco", headers={"User-Agent": "meu-agente"})
        self.assertEqual(resposta["ua"], "meu-agente")

    def test_envia_json(self):
        resposta = http_util.requisitar(self.url + "/eco", method="POST", dados_json={"a": 1})
        self.assertEqual(resposta["tipo"], "application/json")
        self.assertEqual(json.loads(resposta["corpo"]), {"a": 1})

    def test_envia_formulario(self):
        resposta = http_util.requisitar(self.url + "/eco", method="POST", dados_form={"a": "b c"})
        self.assertEqual(resposta["tipo"], "application/x-www-form-urlencoded")
        self.assertEqual(resposta["corpo"], "a=b+c")

    def test_resposta_vazia_vira_none(self):
        self.assertIsNone(http_util.requisitar(self.url + "/vazio"))

    def test_erro_http_vira_ErroHttp(self):
        with self.assertRaises(http_util.ErroHttp) as contexto:
            http_util.requisitar(self.url + "/erro")
        self.assertEqual(contexto.exception.status, 500)
        self.assertIn("deu ruim", contexto.exception.corpo)


if __name__ == "__main__":
    unittest.main()
