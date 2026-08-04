"""Repete (mostra de novo) o alerta de um evento da Atividade recente na
AlertBox da StreamElements - a chamada de verdade pra API da StreamElements
(com a credencial dela) mora no kakazim-bot (ver server.js: POST /api/
streamelements/repetir-evento, streamelements/eventos.js); este módulo só
repassa pra lá, autenticado com o mesmo segredo já usado pro resto da
integração com o kakazim-bot (config: kick_relay_secret / kakazim-bot:
PAINEL_RELAY_SECRET) - mesmo padrão de kick/oauth_pessoal.py.
"""

from . import config
from .http_util import ErroHttp, montar_url, requisitar


def repetir_evento(item):
    """`item`: {"tipo", "plataforma", "usuario", "detalhe"} - mesmo shape de
    um item da Atividade recente (ver hub.py:_registrar_atividade). Lança
    RuntimeError com uma mensagem amigável em caso de falha (usada direto na
    resposta HTTP pro frontend, ver http_server.py)."""
    segredo = config.obter("kick_relay_secret")
    url = montar_url(f"{config.url_base_kakazim_bot()}/api/streamelements/repetir-evento", {"key": segredo})

    try:
        requisitar(
            url,
            method="POST",
            dados_json={
                "tipo": item.get("tipo"),
                "plataforma": item.get("plataforma"),
                "usuario": item.get("usuario"),
                "detalhe": item.get("detalhe"),
            },
        )
    except ErroHttp as erro:
        raise RuntimeError(f"kakazim-bot recusou repetir o alerta ({erro.status}): {erro.corpo}") from erro
    except OSError as erro:
        raise RuntimeError(f"Não consegui falar com o kakazim-bot pra repetir o alerta - {erro}") from erro
