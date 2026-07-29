"""Comandos de resposta automática do chat da Twitch, cadastrados na aba
admin "kakazim.bot" do Kakaverso (tabela kakaverso_comandos_chat).

Diferente da Kick e do Discord (tratados no próprio kakazim-bot, que já tem
cliente Postgres), a Twitch chega em tempo real aqui no kakazim-OBS (via
EventSub próprio, ver hub.py:_tratar_evento_twitch) - e este script não tem
cliente Postgres (só biblioteca padrão, de propósito - ver README.md).

Em duas etapas: 1) matching local contra a lista de palavras-chave (comando +
aliases) ativas na Twitch, cacheada de GET /api/comandos-chat - evita bater
no kakazim-bot a cada mensagem de chat, a maioria não é comando nenhum;
2) só quando bate com algo, POST /api/comandos-chat/executar no kakazim-bot,
que aí sim resolve o perfil, checa permissão (Sub/Admin) e cooldown (global +
por usuário) contra o Postgres, e devolve a resposta de verdade (ou None se
bloqueado)."""

import time

from .. import config
from ..http_util import ErroHttp, montar_url, requisitar

TTL_CACHE_S = 30

_cache = None  # set de palavras-chave (comando + aliases), minúsculas
_cache_atualizado_em = 0


def _atualizar_cache_se_necessario():
    global _cache, _cache_atualizado_em

    if _cache is not None and time.time() - _cache_atualizado_em < TTL_CACHE_S:
        return

    url = montar_url(
        f"{config.url_base_kakazim_bot()}/api/comandos-chat",
        {"key": config.obter("kick_relay_secret"), "plataforma": "twitch"},
    )
    corpo = requisitar(url)
    _cache = {palavra.lower() for palavra in (corpo or {}).get("palavras", [])}
    _cache_atualizado_em = time.time()


def executar_comando(texto_recebido, chatter_user_id, chatter_user_name, eh_mod_ou_broadcaster):
    """None se o texto não bater com nenhuma palavra-chave ativa, se a
    consulta ao kakazim-bot falhar (silencioso de propósito - uma falha aqui
    não deveria derrubar o processamento do chat) ou se o comando estiver
    bloqueado por permissão/cooldown. Caso contrário, a resposta configurada."""
    if not chatter_user_id:
        return None

    try:
        _atualizar_cache_se_necessario()
    except (ErroHttp, OSError) as erro:
        print(f"[Twitch] Falha ao consultar comandos de chat automático: {erro}")
        return None

    if (texto_recebido or "").strip().lower() not in _cache:
        return None

    url = montar_url(
        f"{config.url_base_kakazim_bot()}/api/comandos-chat/executar",
        {"key": config.obter("kick_relay_secret")},
    )
    dados = {
        "plataforma": "twitch",
        "texto": texto_recebido,
        "twitchUserId": str(chatter_user_id),
        "twitchUserName": chatter_user_name,
        "ehModOuBroadcaster": bool(eh_mod_ou_broadcaster),
    }

    try:
        corpo = requisitar(url, method="POST", dados_json=dados)
    except (ErroHttp, OSError) as erro:
        print(f"[Twitch] Falha ao executar comando de chat automático: {erro}")
        return None

    return (corpo or {}).get("resposta")
