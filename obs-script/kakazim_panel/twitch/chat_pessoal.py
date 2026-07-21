"""Envio de mensagem no chat da Twitch pela caixa de texto do painel, usando
a conta PESSOAL do streamer (Kakabg) autorizada em device_auth_pessoal.py -
não usa o token do kakazimbot. Só a rota POST /api/chat/mensagem usa essa
identidade; o resto do projeto (helix.enviar_mensagem_chat, consumido pelo
Stream Deck e por qualquer outro fluxo) continua 100% no kakazimbot, sem
nenhuma mudança.

Sempre manda pro próprio canal (broadcaster_id == sender_id == a conta
autorizada) - diferente de helix.enviar_mensagem_chat, não existe conceito
de "canal de destino" aqui.
"""

from .. import store
from ..http_util import ErroHttp, requisitar
from . import device_auth_pessoal

CHAT_URL = "https://api.twitch.tv/helix/chat/messages"


def enviar_mensagem_chat(mensagem):
    access_token = device_auth_pessoal.obter_access_token_valido()
    user_id = store.buscar_token_twitch_chat_pessoal().get("userId")
    if not user_id:
        raise RuntimeError("Conta pessoal da Twitch (chat) ainda não autorizada.")

    headers = {"Authorization": f"Bearer {access_token}", "Client-Id": device_auth_pessoal.CLIENT_ID}
    dados_json = {"broadcaster_id": user_id, "sender_id": user_id, "message": mensagem}

    try:
        requisitar(CHAT_URL, method="POST", headers=headers, dados_json=dados_json)
    except ErroHttp as erro:
        raise RuntimeError(f"Falha ao enviar mensagem no chat da Twitch ({erro.status}): {erro.corpo}") from erro
