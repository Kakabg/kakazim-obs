"""Anúncios de conquista da Twitch detectados FORA do fluxo de mensagem de
chat (clipes, via polling do kakazim-bot em twitch/pollingClipes.js) - sem
request nosso em andamento pra "pegar carona" numa resposta (diferente das
quests de mensagem, que vêm junto com a resposta de POST /api/mensagem-chat/
twitch, ver contagem_mensagens.py), por isso consultamos periodicamente
GET /api/anuncios-twitch/pendentes no kakazim-bot (mesmo segredo
compartilhado de sempre) - ver hub.py: _iniciar_twitch.
"""

from .. import config
from ..http_util import ErroHttp, montar_url, requisitar


def buscar_anuncios_pendentes():
    """Lista de textos pra mandar no chat agora (pode ser vazia). Falha aqui
    não deve travar nada - só significa "sem anúncio novo dessa vez"
    (silencioso, mesmo padrão de comandos_chat.py)."""
    url = montar_url(
        f"{config.url_base_kakazim_bot()}/api/anuncios-twitch/pendentes",
        {"key": config.obter("kick_relay_secret")},
    )
    try:
        corpo = requisitar(url)
    except (ErroHttp, OSError) as erro:
        print(f"[Twitch] Falha ao consultar anúncios de conquista pendentes: {erro}")
        return []

    return (corpo or {}).get("anuncios") or []
