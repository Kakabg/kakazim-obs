"""Porta de server/twitch/oauth.js. Fluxo OAuth local (callback em
http://localhost:<porta>/twitch/callback) pra um app Twitch dedicado ao
painel - ver README.md em obs-script/ sobre por que esse app e separado do
kakazim-bot.

Suporta dois papeis de conta, cada um com seu proprio token guardado (ver
store.PAPEIS_TWITCH): "streamer" (a conta principal, so leitura/stats) e
"bot" (conta separada tipo kakazimbot, ja moderadora do canal, usada so pra
mandar mensagem no chat). O callback e compartilhado pelos dois fluxos - o
"state" da URL de autorizacao carrega qual papel esta em andamento."""

import secrets
import threading
import time
from urllib.parse import urlencode

from .. import config, store
from ..http_util import ErroHttp, requisitar

AUTORIZACAO_URL = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
USERS_URL = "https://api.twitch.tv/helix/users"

# Streamer: so leitura/stats, no mesmo canal - nao precisa mais de
# user:write:chat desde que o envio de mensagem passou pra conta bot (ver
# helix.enviar_mensagem_chat).
ESCOPOS_STREAMER = "channel:read:subscriptions moderator:read:followers user:read:chat"

# Bot: conta separada (kakazimbot), ja moderadora/editora do canal do
# streamer. user:write:chat manda a mensagem; user:bot e exigido pela Twitch
# pra contas de bot postando em canal de terceiros (mesmo sendo moderadora).
ESCOPOS_BOT = "user:write:chat user:bot"

MARGEM_EXPIRACAO_MS = 2 * 60 * 1000

TTL_STATE_S = 10 * 60

# Mapa state -> {"papel": ..., "criado_em": ...}. Antes so existia uma
# variavel global (um fluxo por vez); agora precisa suportar streamer e bot
# em paralelo/qualquer ordem, entao cada state carrega qual papel ele e.
_autorizacoes_em_andamento = {}
_lock_state = threading.Lock()


def _redirect_uri():
    porta = config.obter("porta")
    return f"http://localhost:{porta}/twitch/callback"


def _limpar_states_expirados():
    agora = time.time()
    expirados = [s for s, info in _autorizacoes_em_andamento.items() if agora - info["criado_em"] > TTL_STATE_S]
    for s in expirados:
        _autorizacoes_em_andamento.pop(s, None)


def construir_url_autorizacao(papel="streamer"):
    if papel not in store.PAPEIS_TWITCH:
        raise ValueError(f"Papel inválido: {papel}")

    with _lock_state:
        _limpar_states_expirados()
        state = secrets.token_hex(16)
        _autorizacoes_em_andamento[state] = {"papel": papel, "criado_em": time.time()}

    escopos = ESCOPOS_BOT if papel == "bot" else ESCOPOS_STREAMER
    params = {
        "client_id": config.obter("twitch_client_id"),
        "response_type": "code",
        "redirect_uri": _redirect_uri(),
        "scope": escopos,
        "state": state,
    }
    return f"{AUTORIZACAO_URL}?{urlencode(params)}"


def buscar_usuario_autenticado(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": config.obter("twitch_client_id"),
    }
    try:
        corpo = requisitar(USERS_URL, headers=headers)
    except ErroHttp as erro:
        raise RuntimeError(f"Falha ao buscar usuário Twitch ({erro.status}): {erro.corpo}") from erro

    usuarios = (corpo or {}).get("data") or []
    if not usuarios:
        raise RuntimeError("Resposta da Twitch não trouxe dados do usuário.")
    return usuarios[0]


def trocar_code_por_token(code, state):
    with _lock_state:
        entrada = _autorizacoes_em_andamento.pop(state, None)
    if not entrada:
        raise RuntimeError("State inválido ou expirado. Inicie a autorização de novo.")
    if time.time() - entrada["criado_em"] > TTL_STATE_S:
        raise RuntimeError("State expirado (mais de 10 minutos desde /twitch/login). Inicie a autorização de novo.")
    papel = entrada["papel"]

    dados_form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": config.obter("twitch_client_id"),
        "client_secret": config.obter("twitch_client_secret"),
        "redirect_uri": _redirect_uri(),
    }

    try:
        token = requisitar(TOKEN_URL, method="POST", dados_form=dados_form)
    except ErroHttp as erro:
        raise RuntimeError(f"Falha ao trocar code por token ({erro.status}): {erro.corpo}") from erro

    usuario = buscar_usuario_autenticado(token["access_token"])

    store.salvar_tokens_twitch(
        access_token=token["access_token"],
        refresh_token=token["refresh_token"],
        expires_at=int(time.time() * 1000) + token["expires_in"] * 1000,
        user_id=usuario["id"],
        login=usuario["login"],
        papel=papel,
    )

    return usuario, papel


def _renovar_token(refresh_token, papel="streamer"):
    dados_form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config.obter("twitch_client_id"),
        "client_secret": config.obter("twitch_client_secret"),
    }

    try:
        token = requisitar(TOKEN_URL, method="POST", dados_form=dados_form)
    except ErroHttp as erro:
        raise RuntimeError(f"Falha ao renovar token da Twitch ({erro.status}): {erro.corpo}") from erro

    tokens_atuais = store.buscar_tokens_twitch(papel)
    store.salvar_tokens_twitch(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token") or refresh_token,
        expires_at=int(time.time() * 1000) + token["expires_in"] * 1000,
        user_id=tokens_atuais.get("userId"),
        login=tokens_atuais.get("login"),
        papel=papel,
    )

    return token["access_token"]


def obter_access_token_valido(papel="streamer"):
    tokens = store.buscar_tokens_twitch(papel)
    if not tokens.get("accessToken") or not tokens.get("refreshToken"):
        sufixo = "?role=bot" if papel == "bot" else ""
        raise RuntimeError(f"Twitch ({papel}) ainda não autorizada. Acesse /twitch/login{sufixo} primeiro.")

    expira_em = tokens.get("expiresAt")
    if expira_em and int(time.time() * 1000) < expira_em - MARGEM_EXPIRACAO_MS:
        return tokens["accessToken"]

    return _renovar_token(tokens["refreshToken"], papel=papel)


def autorizada(papel="streamer"):
    tokens = store.buscar_tokens_twitch(papel)
    return bool(tokens.get("accessToken") and tokens.get("refreshToken"))
