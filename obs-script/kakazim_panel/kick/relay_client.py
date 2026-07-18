"""Porta de server/kick/relayClient.js. Cliente SSE (so biblioteca padrao,
via urllib) do relay exposto pelo kakazim-bot (server.js: GET /painel/eventos).

A Kick so entrega webhook (nao tem WebSocket publico como a Twitch), entao so
o kakazim-bot no Railway pode receber esses eventos - esse cliente conecta
nele de fora pra dentro (o painel local puxa, o Railway nao precisa saber que
o PC existe).
"""

import json
import threading
import urllib.request
from urllib.parse import urlencode

from .. import config

ATRASO_RECONEXAO_S = 5
# Um pouco maior que o intervalo do heartbeat (": ping") que o kakazim-bot
# manda a cada 20s - qualquer coisa maior que isso sem receber nada de fato
# indica conexao morta, nao so um periodo calmo sem eventos da Kick.
TIMEOUT_LEITURA_S = 35


def _processar_bloco(bloco, on_evento):
    for linha in bloco.split("\n"):
        if not linha.startswith("data:"):
            continue
        bruto = linha[len("data:"):].strip()
        try:
            on_evento(json.loads(bruto))
        except (TypeError, ValueError) as erro:
            print(f"[Kick relay] Payload SSE inválido: {erro}")


def _conectar_uma_vez(on_evento, parar_evento):
    url_base = config.obter("kick_relay_url")
    secret = config.obter("kick_relay_secret")
    url = f"{url_base}?{urlencode({'key': secret})}"

    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_LEITURA_S) as resp:
        print("[Kick relay] Conectado ao kakazim-bot.")
        buffer = ""
        while not parar_evento.is_set():
            pedaco = resp.read(4096)
            if not pedaco:
                break
            buffer += pedaco.decode("utf-8", errors="replace")

            while "\n\n" in buffer:
                bloco, buffer = buffer.split("\n\n", 1)
                _processar_bloco(bloco, on_evento)

    print("[Kick relay] Conexão encerrada pelo servidor.")


class ClienteRelayKick:
    def __init__(self, on_evento):
        self._on_evento = on_evento
        self._parar = threading.Event()
        self._thread = None

    def iniciar(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="kick-relay")
        self._thread.start()

    def parar(self):
        self._parar.set()

    def _loop(self):
        while not self._parar.is_set():
            try:
                _conectar_uma_vez(self._on_evento, self._parar)
            except Exception as erro:
                print(f"[Kick relay] Erro de conexão: {erro}")

            if self._parar.is_set():
                return

            self._parar.wait(ATRASO_RECONEXAO_S)
