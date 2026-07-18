"""Porta de server/twitch/eventsub.js. Unica dependencia externa do painel -
websocket-client (pip) - ver obs-script/README.md pra instalacao. Conecta
direto na Twitch (wss://eventsub.wss.twitch.tv/ws), sem depender do
kakazim-bot/Railway, pra channel.follow / channel.subscribe /
channel.subscription.message / channel.raid / channel.chat.message.
"""

import json
import threading

import websocket

from .. import config
from ..http_util import ErroHttp, requisitar
from .helix import broadcaster_user_id
from .oauth import obter_access_token_valido

URL_PADRAO = "wss://eventsub.wss.twitch.tv/ws"
SUBSCRICOES_URL = "https://api.twitch.tv/helix/eventsub/subscriptions"
ATRASO_RECONEXAO_S = 5


def _tipos_desejados(id_):
    return [
        {"type": "channel.follow", "version": "2", "condition": {"broadcaster_user_id": id_, "moderator_user_id": id_}},
        {"type": "channel.subscribe", "version": "1", "condition": {"broadcaster_user_id": id_}},
        {"type": "channel.subscription.message", "version": "1", "condition": {"broadcaster_user_id": id_}},
        {"type": "channel.raid", "version": "1", "condition": {"to_broadcaster_user_id": id_}},
        {"type": "channel.chat.message", "version": "1", "condition": {"broadcaster_user_id": id_, "user_id": id_}},
    ]


def _criar_inscricao(tipo, versao, condicao, session_id):
    access_token = obter_access_token_valido()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": config.obter("twitch_client_id"),
    }
    corpo = {
        "type": tipo,
        "version": versao,
        "condition": condicao,
        "transport": {"method": "websocket", "session_id": session_id},
    }
    try:
        requisitar(SUBSCRICOES_URL, method="POST", headers=headers, dados_json=corpo)
    except ErroHttp as erro:
        print(f"[Twitch EventSub] Falha ao assinar {tipo} ({erro.status}): {erro.corpo}")


def _assinar_tudo(session_id):
    id_ = broadcaster_user_id()
    for desejado in _tipos_desejados(id_):
        _criar_inscricao(desejado["type"], desejado["version"], desejado["condition"], session_id)


class ClienteEventSub:
    """Cliente WebSocket da Twitch EventSub. Roda numa thread propria
    (run_forever bloqueia) com reconexao automatica."""

    def __init__(self, on_evento):
        self._on_evento = on_evento
        self._parar = threading.Event()
        self._ws_app = None
        self._thread = None

    def iniciar(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="twitch-eventsub")
        self._thread.start()

    def parar(self):
        self._parar.set()
        if self._ws_app is not None:
            try:
                self._ws_app.close()
            except Exception:
                pass

    def _loop(self):
        while not self._parar.is_set():
            try:
                self._conectar_uma_vez()
            except Exception as erro:
                print(f"[Twitch EventSub] Erro na conexão: {erro}")

            if self._parar.is_set():
                return

            print(f"[Twitch EventSub] Conexão fechada. Reconectando em {ATRASO_RECONEXAO_S}s...")
            self._parar.wait(ATRASO_RECONEXAO_S)

    def _conectar_uma_vez(self):
        def on_message(ws_app, mensagem_bruta):
            try:
                mensagem = json.loads(mensagem_bruta)
            except (TypeError, ValueError):
                return

            tipo = (mensagem.get("metadata") or {}).get("message_type")

            if tipo == "session_welcome":
                session_id = mensagem["payload"]["session"]["id"]
                print(f"[Twitch EventSub] Sessão conectada ({session_id}), assinando eventos...")
                _assinar_tudo(session_id)
                return

            if tipo == "session_keepalive":
                return

            if tipo == "notification":
                subscription = mensagem["payload"]["subscription"]
                evento = mensagem["payload"]["event"]
                try:
                    self._on_evento(subscription["type"], evento)
                except Exception as erro:
                    print(f"[Twitch EventSub] Erro ao processar evento {subscription.get('type')}: {erro}")
                return

            if tipo == "session_reconnect":
                # Simplificação consciente: em vez de manter duas conexões
                # simultâneas (a troca "sem perda de eventos" recomendada pela
                # Twitch), só fecha e deixa o loop de fora reconectar do zero
                # na URL padrão e re-assinar. Pode perder um evento raríssimo
                # nesse meio-tempo - aceitável pra um painel de exibição, não
                # vale a complexidade extra de duas sessões concorrentes aqui.
                print("[Twitch EventSub] Twitch pediu reconexão, encerrando sessão atual...")
                ws_app.close()
                return

            if tipo == "revocation":
                print(f"[Twitch EventSub] Assinatura revogada: {mensagem['payload'].get('subscription')}")

        def on_error(ws_app, erro):
            print(f"[Twitch EventSub] Erro no WebSocket: {erro}")

        ws_app = websocket.WebSocketApp(URL_PADRAO, on_message=on_message, on_error=on_error)
        self._ws_app = ws_app
        ws_app.run_forever()
