"""Envio de mensagem no chat da Kick pela caixa de texto do painel, usando a
conta PESSOAL do streamer (Kakabg) autorizada em oauth_pessoal.py.

Antes desta mudança, isso passava pelo relay do kakazim-bot (POST
/api/kick/enviar-mensagem), que usa a conta separada kakazimbot - igual o
Stream Deck ("Enviar Mensagem") continua fazendo. Só esta rota (POST
/api/chat/mensagem) foi trocada pra falar direto com a API da Kick usando o
token pessoal; nada mais no projeto muda.
"""

from .. import store
from ..http_util import ErroHttp, requisitar
from . import oauth_pessoal

CHAT_URL = "https://api.kick.com/public/v1/chat"


def enviar_mensagem_chat(mensagem):
    access_token = oauth_pessoal.obter_access_token_valido()
    broadcaster_user_id = store.buscar_token_kick_chat_pessoal().get("userId")
    if not broadcaster_user_id:
        raise RuntimeError("Conta pessoal da Kick (chat) ainda não autorizada.")

    headers = {"Authorization": f"Bearer {access_token}"}
    dados_json = {"broadcaster_user_id": broadcaster_user_id, "content": mensagem, "type": "user"}

    try:
        requisitar(CHAT_URL, method="POST", headers=headers, dados_json=dados_json)
    except ErroHttp as erro:
        raise RuntimeError(f"Falha ao enviar mensagem no chat da Kick ({erro.status}): {erro.corpo}") from erro
