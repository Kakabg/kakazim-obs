"""Porta de server/kick/stats.js - polling da API publica oficial da Kick
(client_credentials, sem OAuth de usuario) pra viewers e total de inscritos."""

import threading
import time

from .. import config
from ..http_util import ErroHttp, montar_url, requisitar

TOKEN_URL = "https://id.kick.com/oauth/token"
CANAIS_URL = "https://api.kick.com/public/v1/channels"

_lock = threading.Lock()
_app_access_token = None
_expira_em = 0
_broadcaster_user_id_cache = None


def _obter_app_access_token():
    global _app_access_token, _expira_em
    with _lock:
        if _app_access_token and time.time() < _expira_em:
            return _app_access_token

        dados_form = {
            "grant_type": "client_credentials",
            "client_id": config.obter("kick_client_id"),
            "client_secret": config.obter("kick_client_secret"),
        }
        try:
            corpo = requisitar(TOKEN_URL, method="POST", dados_form=dados_form)
        except ErroHttp as erro:
            raise RuntimeError(f"Falha ao obter app access token da Kick ({erro.status}): {erro.corpo}") from erro

        _app_access_token = corpo["access_token"]
        # Margem de 1min antes de expirar de verdade.
        _expira_em = time.time() + corpo["expires_in"] - 60
        return _app_access_token


def _buscar_canal(params):
    access_token = _obter_app_access_token()
    url = montar_url(CANAIS_URL, params)
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        corpo = requisitar(url, headers=headers)
    except ErroHttp as erro:
        raise RuntimeError(f"Falha ao buscar canal Kick ({erro.status}): {erro.corpo}") from erro

    dados = (corpo or {}).get("data") or []
    return dados[0] if dados else None


def broadcaster_user_id():
    global _broadcaster_user_id_cache
    if _broadcaster_user_id_cache:
        return _broadcaster_user_id_cache

    slug = config.obter("kick_broadcaster_slug")
    canal = _buscar_canal({"slug": slug})
    if not canal or not canal.get("broadcaster_user_id"):
        raise RuntimeError(f'Não encontrei o canal Kick "{slug}".')

    _broadcaster_user_id_cache = canal["broadcaster_user_id"]
    return _broadcaster_user_id_cache


def buscar_stats():
    id_ = broadcaster_user_id()
    canal = _buscar_canal({"broadcaster_user_id": id_}) or {}
    stream = canal.get("stream") or {}
    return {
        "aoVivo": bool(stream.get("is_live")),
        "viewers": stream.get("viewer_count", 0),
        "inscritos": canal.get("active_subscribers_count", 0),
    }
