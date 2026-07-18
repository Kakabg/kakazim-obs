"""Porta de server/kick/relayClient.js. Cliente SSE (so biblioteca padrao,
via urllib) do relay exposto pelo kakazim-bot (server.js: GET /painel/eventos).

A Kick so entrega webhook (nao tem WebSocket publico como a Twitch), entao so
o kakazim-bot no Railway pode receber esses eventos - esse cliente conecta
nele de fora pra dentro (o painel local puxa, o Railway nao precisa saber que
o PC existe).

Mantém um cursor (maior id de evento já recebido, persistido em
store.json) e manda de volta como ?desde= a cada (re)conexão - sem isso, um
evento que chegasse no kakazim-bot enquanto essa conexão estivesse caída
(rede, restart do script, PC desligado) seria perdido pra sempre, já que o
lado do kakazim-bot só empurrava pra quem estava conectado na hora
(fire-and-forget). Com o cursor, a reconexão pede replay do que ficou pra
trás (ver banco/db.js: eventos_painel e GET /painel/eventos no kakazim-bot).
"""

import json
import threading
import time
import urllib.request
from urllib.parse import urlencode

from .. import config, store

ATRASO_RECONEXAO_S = 5
# Um pouco maior que o intervalo do heartbeat (": ping") que o kakazim-bot
# manda a cada 20s - qualquer coisa maior que isso sem receber nada de fato
# indica conexao morta, nao so um periodo calmo sem eventos da Kick.
TIMEOUT_LEITURA_S = 35

# Visto em produção: uma conexão pode ficar "aberta" do lado do cliente sem
# erro nem timeout (ex.: o kakazim-bot reiniciou/redeployou e o socket antigo
# ficou órfão sem um FIN/RST chegar) e simplesmente parar de entregar eventos
# novos, mesmo o painel achando que ainda está tudo bem. Em vez de confiar só
# na detecção de timeout (que não pegou esse caso), força uma reconexão
# periódica preventiva - o pior caso é uma reconexão de graça a cada 10min.
DURACAO_MAXIMA_CONEXAO_S = 600


def _processar_bloco(bloco, on_evento):
    for linha in bloco.split("\n"):
        if not linha.startswith("data:"):
            continue
        bruto = linha[len("data:"):].strip()
        try:
            dados = json.loads(bruto)
        except (TypeError, ValueError) as erro:
            print(f"[Kick relay] Payload SSE inválido: {erro}")
            continue

        if isinstance(dados, dict) and dados.get("id") is not None:
            store.definir_ultimo_evento_relay_kick(dados["id"])
        on_evento(dados)


def _conectar_uma_vez(on_evento, parar_evento):
    url_base = config.obter("kick_relay_url")
    secret = config.obter("kick_relay_secret")
    parametros = {"key": secret}
    desde = store.buscar_ultimo_evento_relay_kick()
    if desde is not None:
        parametros["desde"] = desde
    url = f"{url_base}?{urlencode(parametros)}"

    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_LEITURA_S) as resp:
        print("[Kick relay] Conectado ao kakazim-bot.")
        inicio_conexao = time.time()
        buffer = ""
        while not parar_evento.is_set():
            if time.time() - inicio_conexao > DURACAO_MAXIMA_CONEXAO_S:
                print("[Kick relay] Reconexão preventiva (conexão atingiu o tempo máximo).")
                return

            # read1() (não read()) é essencial aqui: numa resposta chunked,
            # HTTPResponse.read(n) fica lendo chunk após chunk até juntar n
            # bytes (bloqueando esperando o PRÓXIMO chunk chegar, não só o
            # atual) - como cada evento vira um chunk bem menor que 4096
            # bytes, isso represava vários eventos (~5, dependendo do
            # tamanho de cada um) até soltar todos de uma vez em vez de
            # entregar cada um assim que chegasse. read1() faz no máximo uma
            # leitura de baixo nível e devolve na hora o que já tiver.
            pedaco = resp.read1(4096)
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
