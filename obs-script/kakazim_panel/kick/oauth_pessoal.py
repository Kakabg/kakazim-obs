"""Token da conta PESSOAL do streamer (Kakabg) na Kick, usado exclusivamente
pela caixa de chat direto do painel (POST /api/chat/mensagem, ver chat.py).

A Kick só permite 2 apps OAuth por conta, e os dois já estão em uso
(Kakazimbot, Kakaverso) - não dá pra criar um terceiro app dedicado só pra
isso. A solução foi reaproveitar o app do kakazimbot: o botão "Autorizar
minha conta Kick (pessoal, pra chat)" abre uma rota nova no kakazim-bot
(GET /kick/login/painel-obs, ver server.js), que faz o OAuth de verdade
(mesmo app) e, no callback, detectando esse propósito, NÃO salva a config
de streamer/bot de sempre - em vez disso serve uma página que entrega o
token pra este painel via fetch() do lado do NAVEGADOR (o Railway, onde o
kakazim-bot roda, não tem como alcançar 127.0.0.1 na máquina do usuário -
só o navegador dele, que está na mesma máquina que este painel, consegue).

Importante: como o kakazim-bot fica sempre de pé no Railway (diferente de
uma tentativa anterior que dependia do Kakaverso rodando local no PC), essa
autorização não exige manter nada extra aberto no PC do usuário além do
próprio OBS.

Consequência: como quem tem o client_secret do app é o kakazim-bot (não
este script), renovar o token perto de expirar também passa por lá
(POST /api/kick/chat-pessoal/renovar) - este módulo nunca fala com
id.kick.com/oauth/token diretamente. As duas pontas se autenticam com o
mesmo segredo já usado pelo resto da integração com o kakazim-bot
(config: kick_relay_secret / kakazim-bot: PAINEL_RELAY_SECRET).
"""

import time
from urllib.parse import urlparse

from .. import config, store
from ..http_util import ErroHttp, montar_url, requisitar

MARGEM_EXPIRACAO_MS = 2 * 60 * 1000


def _url_base_kakazim_bot():
    """Deriva esquema+host do kakazim-bot a partir de kick_relay_url (já
    configurado pro relay de eventos) - não usa o caminho dele
    (/painel/eventos), só a origem."""
    partes = urlparse(config.obter("kick_relay_url"))
    return f"{partes.scheme}://{partes.netloc}"


def montar_url_login(porta):
    """URL do botão "Autorizar minha conta Kick (pessoal, pra chat)" -
    aponta pro kakazim-bot, não pra Kick diretamente (é o kakazim-bot quem
    monta a URL de autorização de verdade, com o client_id/secret dele)."""
    segredo = config.obter("kick_relay_secret")
    return montar_url(f"{_url_base_kakazim_bot()}/kick/login/painel-obs", {"key": segredo, "porta": porta})


def receber_token(dados):
    """Chamado pela rota HTTP que a página de callback do kakazim-bot invoca
    (via fetch() no navegador) depois de trocar o code por token (ver
    http_server.py). `dados` já vem no formato entregue por ela:
    access_token, refresh_token, expires_in, user_id, name."""
    store.salvar_token_kick_chat_pessoal(
        access_token=dados["access_token"],
        refresh_token=dados["refresh_token"],
        expires_at=int(time.time() * 1000) + dados["expires_in"] * 1000,
        user_id=dados.get("user_id"),
        nome=dados.get("name"),
    )


def _renovar_token(refresh_token):
    segredo = config.obter("kick_relay_secret")
    url = montar_url(f"{_url_base_kakazim_bot()}/api/kick/chat-pessoal/renovar", {"key": segredo})
    try:
        token = requisitar(url, method="POST", dados_json={"refresh_token": refresh_token})
    except ErroHttp as erro:
        raise RuntimeError(
            f"Falha ao renovar token pessoal da Kick via kakazim-bot ({erro.status}): {erro.corpo}."
        ) from erro
    except OSError as erro:
        # Conexão recusada/indisponível (não é um ErroHttp - o kakazim-bot
        # nem chegou a responder). O kakazim-bot roda 24/7 no Railway, então
        # isso normalmente é problema de rede local, não do serviço em si.
        raise RuntimeError(
            f"Não consegui falar com o kakazim-bot pra renovar o token pessoal da Kick - {erro}"
        ) from erro

    tokens_atuais = store.buscar_token_kick_chat_pessoal()
    store.salvar_token_kick_chat_pessoal(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token") or refresh_token,
        expires_at=int(time.time() * 1000) + token["expires_in"] * 1000,
        user_id=tokens_atuais.get("userId"),
        nome=tokens_atuais.get("nome"),
    )
    return token["access_token"]


def obter_access_token_valido():
    tokens = store.buscar_token_kick_chat_pessoal()
    if not tokens.get("accessToken") or not tokens.get("refreshToken"):
        raise RuntimeError(
            'Conta pessoal da Kick (chat) ainda não autorizada - clique em "Autorizar minha conta Kick '
            '(pessoal, pra chat)" nas configurações do script.'
        )

    expira_em = tokens.get("expiresAt")
    if expira_em and int(time.time() * 1000) < expira_em - MARGEM_EXPIRACAO_MS:
        return tokens["accessToken"]

    return _renovar_token(tokens["refreshToken"])


def autorizada():
    tokens = store.buscar_token_kick_chat_pessoal()
    return bool(tokens.get("accessToken") and tokens.get("refreshToken"))
