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


def buscar_usuario_por_login(login):
    """Resolve um login (username) da Twitch pro user id correspondente -
    nao exige nenhum escopo especial, so um token valido qualquer."""
    corpo = _chamar_helix("users", {"login": login})
    usuarios = (corpo or {}).get("data") or []
    if not usuarios:
        raise RuntimeError(f'Canal Twitch "{login}" não encontrado.')
    return usuarios[0]


def enviar_mensagem_chat(mensagem, canal=None):
    """Manda mensagem no chat de um canal, autenticado como a conta bot
    separada (kakazimbot) - sender_id e' sempre do bot. `canal` (login da
    Twitch) define o destino; se omitido, cai pro canal autorizado como
    "streamer" (retrocompatibilidade). Exige token do bot (User Access
    Token, via OAuth) com escopos user:write:chat + user:bot (ver
    /twitch/login?role=bot).

    Importante: como isso usa um User Access Token da propria conta do
    kakazimbot (nao um App Access Token), a Twitch so exige o escopo
    user:write:chat - nao precisa o dono do canal de destino adicionar
    "kakazimbot" como moderador nem autorizar o escopo channel:bot (essa
    exigencia so existe pra quem manda mensagem com App Access Token). Na
    pratica, o kakazimbot entra no chat como um usuario comum, entao esta
    sujeito as mesmas regras do canal de destino que qualquer chatter:
    modo somente-seguidores, somente-assinantes, slow mode, palavra
    bloqueada pelo AutoMod, ou o proprio kakazimbot estar banido/bloqueado
    naquele canal especifico.
    """
    if canal:
        usuario = buscar_usuario_por_login(canal)
        broadcaster_id = usuario["id"]
    else:
        broadcaster_id = broadcaster_user_id()

    tokens_bot = store.buscar_tokens_twitch("bot")
    bot_user_id = tokens_bot.get("userId")
    if not bot_user_id:
        raise RuntimeError("Twitch (bot) ainda não autorizada. Acesse /twitch/login?role=bot primeiro.")

    access_token = obter_access_token_valido(papel="bot")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": config.obter("twitch_client_id"),
    }
    dados_json = {
        "broadcaster_id": broadcaster_id,
        "sender_id": bot_user_id,
        "message": mensagem,
    }
    try:
        return requisitar(f"{HELIX_BASE}/chat/messages", method="POST", headers=headers, dados_json=dados_json)
    except ErroHttp as erro:
        if erro.status == 401:
            raise RuntimeError(
                f"Token do kakazimbot expirado ou sem o escopo user:write:chat - reautorize clicando em "
                f'"Autorizar Twitch (bot)" ({erro.status}): {erro.corpo}'
            ) from erro
        if erro.status == 403:
            raise RuntimeError(
                f"Twitch recusou a mensagem nesse canal ({erro.status}): {erro.corpo}. O kakazimbot manda "
                f"mensagem como um usuário comum entrando no chat, então está sujeito às mesmas regras do canal "
                f"de destino que qualquer chatter enfrentaria - confira se esse canal está com modo "
                f"somente-seguidores, somente-assinantes, slow mode, alguma palavra bloqueada pelo AutoMod, ou "
                f"se o kakazimbot está banido/bloqueado especificamente nele."
            ) from erro
        raise RuntimeError(f"Falha ao enviar mensagem no chat da Twitch ({erro.status}): {erro.corpo}") from erro
