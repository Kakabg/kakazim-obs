"""Contagem de mensagens de chat da Twitch pra métrica de quests do
Kakaverso (kakaverso_quests: metrica "mensagens_chat", soma Kick+Twitch).

Diferente da Kick (contada direto no kakazim-bot, que já processa o webhook
chat.message.sent), a Twitch chega em tempo real aqui no kakazim-OBS (ver
hub.py: _tratar_evento_twitch/channel.chat.message) - e este script não tem
cliente Postgres (só biblioteca padrão, de propósito - ver README.md). Por
isso avisa o kakazim-bot por HTTP a cada mensagem, em
POST /api/mensagem-chat/twitch (mesmo segredo compartilhado de sempre -
config: kick_relay_secret / kakazim-bot: PAINEL_RELAY_SECRET), que
incrementa o contador e roda a checagem de quests do lado dele.
"""

from .. import config
from ..http_util import ErroHttp, montar_url, requisitar


def registrar_mensagem_chat(twitch_user_id, twitch_username):
    """Falha aqui não deve derrubar o processamento normal do chat (comando
    automático etc.) - só significa que essa mensagem não contou pra quest
    dessa vez (silencioso de propósito, mesmo padrão de comandos_chat.py)."""
    if not twitch_user_id:
        return

    url = montar_url(
        f"{config.url_base_kakazim_bot()}/api/mensagem-chat/twitch",
        {"key": config.obter("kick_relay_secret")},
    )
    try:
        requisitar(
            url,
            method="POST",
            dados_json={"twitchUserId": str(twitch_user_id), "twitchUsername": twitch_username},
        )
    except (ErroHttp, OSError) as erro:
        print(f"[Twitch] Falha ao registrar mensagem de chat pra quests: {erro}")
