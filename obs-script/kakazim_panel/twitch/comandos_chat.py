"""Comandos de resposta automática do chat da Twitch, cadastrados na aba
admin "kakazim.bot" do Kakaverso (tabela kakaverso_comandos_chat).

Diferente da Kick e do Discord (tratados no próprio kakazim-bot, que já tem
cliente Postgres), a Twitch chega em tempo real aqui no kakazim-OBS (via
EventSub próprio, ver hub.py:_tratar_evento_twitch) - e este script não tem
cliente Postgres (só biblioteca padrão, de propósito - ver README.md). Por
isso consulta os comandos por HTTP, em GET /api/comandos-chat no kakazim-bot
(mesmo segredo compartilhado de sempre - config: kick_relay_secret /
kakazim-bot: PAINEL_RELAY_SECRET).
"""

import time

from .. import config
from ..http_util import ErroHttp, montar_url, requisitar

TTL_CACHE_S = 30

_cache = None  # dict comando_minusculo -> resposta
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
    _cache = {item["comando"].lower(): item["resposta"] for item in (corpo or {}).get("comandos", [])}
    _cache_atualizado_em = time.time()


def buscar_resposta_comando(texto_recebido):
    """None se não bater com nenhum comando ativo, ou se a consulta ao
    kakazim-bot falhar (silencioso de propósito - uma falha aqui não deveria
    derrubar o processamento do chat, só significa "sem resposta automática
    dessa vez")."""
    try:
        _atualizar_cache_se_necessario()
    except (ErroHttp, OSError) as erro:
        print(f"[Twitch] Falha ao consultar comandos de chat automático: {erro}")
        return None

    return _cache.get((texto_recebido or "").strip().lower())
