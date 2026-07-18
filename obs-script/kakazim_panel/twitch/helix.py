"""Porta de server/twitch/helix.js - polling REST (viewers, seguidores,
inscritos)."""

from .. import config, store
from ..http_util import ErroHttp, montar_url, requisitar
from .oauth import obter_access_token_valido

HELIX_BASE = "https://api.twitch.tv/helix"


def _chamar_helix(caminho, params):
    access_token = obter_access_token_valido()
    url = montar_url(f"{HELIX_BASE}/{caminho}", params)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": config.obter("twitch_client_id"),
    }
    try:
        return requisitar(url, headers=headers)
    except ErroHttp as erro:
        raise RuntimeError(f"Falha ao chamar Helix {caminho} ({erro.status}): {erro.corpo}") from erro


def broadcaster_user_id():
    user_id = store.buscar_tokens_twitch().get("userId")
    if not user_id:
        raise RuntimeError("Twitch ainda não autorizada.")
    return user_id


def buscar_viewers_atuais():
    corpo = _chamar_helix("streams", {"user_id": broadcaster_user_id()})
    streams = (corpo or {}).get("data") or []
    if streams:
        return {"aoVivo": True, "viewers": streams[0].get("viewer_count", 0)}
    return {"aoVivo": False, "viewers": 0}


def buscar_total_seguidores():
    id_ = broadcaster_user_id()
    corpo = _chamar_helix("channels/followers", {"broadcaster_id": id_, "moderator_id": id_, "first": 1})
    return (corpo or {}).get("total", 0)


def buscar_total_inscritos():
    corpo = _chamar_helix("subscriptions", {"broadcaster_id": broadcaster_user_id(), "first": 1})
    return (corpo or {}).get("total", 0)


def enviar_mensagem_chat(mensagem):
    """Manda mensagem no chat da propria live, como o streamer autenticado
    (broadcaster_id == sender_id) - exige o escopo user:write:chat."""
    id_ = broadcaster_user_id()
    access_token = obter_access_token_valido()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": config.obter("twitch_client_id"),
    }
    dados_json = {
        "broadcaster_id": id_,
        "sender_id": id_,
        "message": mensagem,
    }
    try:
        return requisitar(f"{HELIX_BASE}/chat/messages", method="POST", headers=headers, dados_json=dados_json)
    except ErroHttp as erro:
        raise RuntimeError(f"Falha ao enviar mensagem no chat da Twitch ({erro.status}): {erro.corpo}") from erro
