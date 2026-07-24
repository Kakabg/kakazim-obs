"""Comando !sorteio (feature de lançamento) no chat da Twitch - mesmo
padrão de contagem_mensagens.py (avisa o kakazim-bot por HTTP, que tem o
Postgres), mas chamado À PARTE em hub.py, SEM a exclusão de "mensagem do
próprio canal" - o streamer também precisa conseguir testar/participar do
próprio sorteio, diferente da contagem de quests/bônus de boas-vindas (que
intencionalmente ignora mensagem do dono do canal).
"""

from .. import config
from ..http_util import ErroHttp, montar_url, requisitar


def processar_comando_sorteio(twitch_user_id, twitch_username):
    """None se não houver sorteio aberto, se a inscrição não mudou (mesmo
    número de tickets de antes - silencioso de propósito, evita responder
    de novo a cada repetição do comando) ou se a chamada falhar."""
    if not twitch_user_id:
        return None

    url = montar_url(
        f"{config.url_base_kakazim_bot()}/api/sorteio/comando-twitch",
        {"key": config.obter("kick_relay_secret")},
    )
    dados = {"twitchUserId": str(twitch_user_id), "twitchUsername": twitch_username}

    try:
        corpo = requisitar(url, method="POST", dados_json=dados)
    except (ErroHttp, OSError) as erro:
        print(f"[Twitch] Falha ao processar comando !sorteio: {erro}")
        return None

    return (corpo or {}).get("responder")
