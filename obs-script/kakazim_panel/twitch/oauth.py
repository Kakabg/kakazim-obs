"""Porta de server/twitch/oauth.js. Fluxo OAuth local (callback em
http://localhost:<porta>/twitch/callback) pra um app Twitch dedicado ao
painel - ver README.md em obs-script/ sobre por que esse app e separado do
kakazim-bot."""

import secrets
import time
from urllib.parse import urlencode

from .. import config, store
from ..http_util import ErroHttp, requisitar

AUTORIZACAO_URL = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
USERS_URL = "https://api.twitch.tv/helix/users"

# O token e sempre do proprio streamer lendo o proprio canal, entao nao
# precisa de user:bot (isso so e exigido pra contas de bot separadas do
# broadcaster/moderador).
ESCOPOS = "channel:read:subscriptions moderator:read:followers user:read:chat"

MARGEM_EXPIRACAO_MS = 2 * 60 * 1000

# So um fluxo de autorizacao por vez (uso pessoal, local).
_state_em_andamento = None


def _redirect_uri():
    porta = config.obter("porta")
    return f"http://localhost:{porta}/twitch/callback"


def construir_url_autorizacao():
    global _state_em_andamento
    _state_em_andamento = secrets.token_hex(16)

    params = {
        "client_id": config.obter("twitch_client_id"),
        "response_type": "code",
        "redirect_uri": _redirect_uri(),
        "scope": ESCOPOS,
        "state": _state_em_andamento,
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
    global _state_em_andamento
    if not _state_em_andamento or state != _state_em_andamento:
        raise RuntimeError("State inválido ou expirado. Acesse /twitch/login de novo.")
    _state_em_andamento = None

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
    )

    return usuario


def _renovar_token(refresh_token):
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

    tokens_atuais = store.buscar_tokens_twitch()
    store.salvar_tokens_twitch(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token") or refresh_token,
        expires_at=int(time.time() * 1000) + token["expires_in"] * 1000,
        user_id=tokens_atuais.get("userId"),
        login=tokens_atuais.get("login"),
    )

    return token["access_token"]


def obter_access_token_valido():
    tokens = store.buscar_tokens_twitch()
    if not tokens.get("accessToken") or not tokens.get("refreshToken"):
        raise RuntimeError("Twitch ainda não autorizada. Acesse /twitch/login primeiro.")

    expira_em = tokens.get("expiresAt")
    if expira_em and int(time.time() * 1000) < expira_em - MARGEM_EXPIRACAO_MS:
        return tokens["accessToken"]

    return _renovar_token(tokens["refreshToken"])


def autorizada():
    tokens = store.buscar_tokens_twitch()
    return bool(tokens.get("accessToken") and tokens.get("refreshToken"))
