"""Status de self-mute do Caíque no Discord, exposto pelo kakazim-bot (bot já
conectado ao servidor, ouvindo voiceStateUpdate - ver discord/muteStatus.js
lá) - consultado periodicamente aqui, mesmo padrão de twitch/
anuncios_conquistas.py.

ATENÇÃO: há relatos de bugs de confiabilidade no evento voiceStateUpdate em
algumas versões do discord.js (às vezes não dispara certinho pra mudança só
de self-mute, sem trocar de canal) - esse indicador precisa ser validado com
uma live de verdade antes de confiar 100% nele.
"""

from . import config
from .http_util import ErroHttp, montar_url, requisitar


def buscar_status_mute():
    """None se a consulta falhar (silencioso, mesmo padrão dos outros
    pollers) - ou o dict {"mutado": bool|None} devolvido pelo kakazim-bot."""
    url = montar_url(
        f"{config.url_base_kakazim_bot()}/api/discord/mute-status",
        {"key": config.obter("kick_relay_secret")},
    )
    try:
        return requisitar(url)
    except (ErroHttp, OSError) as erro:
        print(f"[Discord] Falha ao consultar status de mute: {erro}")
        return None
