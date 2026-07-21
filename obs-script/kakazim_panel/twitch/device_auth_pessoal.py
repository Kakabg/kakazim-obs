"""Autorizacao da conta PESSOAL do streamer (Kakabg) na Twitch, via Device
Authorization Grant - usada exclusivamente pela caixa de chat direto do
painel (POST /api/chat/mensagem, ver chat_pessoal.py). Nao mexe em mais nada
do projeto: o kakazimbot continua sendo quem manda mensagem em
/api/twitch/enviar-mensagem (Stream Deck) e nos avisos automaticos - ver
helix.enviar_mensagem_chat, que fica intocado.

Reaproveita o mesmo client_id publico que o kakazim-live ja usa pro Device
Code Grant da conta pessoal (autorizacao de clipe oficial) - e um client
"Public" da Twitch (sem client_secret), pensado exatamente pra esse tipo de
fluxo embutido em ferramenta local, sem precisar de um app novo nem de
redirect URI nenhum (Device Code nao usa redirect). So muda o escopo pedido
(user:write:chat em vez de clips:edit) e onde o token fica guardado (aqui,
via store.salvar_token_twitch_chat_pessoal - independente do kakazim-live).
"""

import json
import time

from .. import store
from ..http_util import ErroHttp, requisitar

CLIENT_ID = "bzenn2frmnzkmgkczvan5yoxaad2x0"
SCOPES = "user:write:chat"

DEVICE_URL = "https://id.twitch.tv/oauth2/device"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
USERS_URL = "https://api.twitch.tv/helix/users"

MARGEM_EXPIRACAO_MS = 2 * 60 * 1000


def iniciar_device_authorization():
    """Passo 1: pede pra Twitch um codigo pra pessoa digitar em
    twitch.tv/activate (ou na URL que a propria resposta trouxer)."""
    corpo = requisitar(
        DEVICE_URL,
        method="POST",
        dados_form={"client_id": CLIENT_ID, "scopes": SCOPES},
    )
    return {
        "device_code": corpo["device_code"],
        "user_code": corpo["user_code"],
        "verification_uri": corpo["verification_uri"],
        "expires_in": corpo["expires_in"],
        "interval": corpo["interval"],
    }


def _pedir_token(device_code):
    try:
        corpo = requisitar(
            TOKEN_URL,
            method="POST",
            dados_form={
                "client_id": CLIENT_ID,
                "scopes": SCOPES,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        return {"token": corpo}
    except ErroHttp as erro:
        try:
            mensagem = json.loads(erro.corpo).get("message", "")
        except (TypeError, ValueError):
            mensagem = erro.corpo or ""
        if "authorization_pending" in mensagem:
            return {"pending": True}
        if "slow_down" in mensagem:
            return {"slow_down": True}
        return {"erro": mensagem or str(erro)}


def _buscar_usuario_autenticado(access_token):
    corpo = requisitar(USERS_URL, headers={"Authorization": f"Bearer {access_token}", "Client-Id": CLIENT_ID})
    usuarios = (corpo or {}).get("data") or []
    if not usuarios:
        raise RuntimeError("Resposta da Twitch não trouxe dados da conta.")
    return usuarios[0]


def aguardar_autorizacao(device_code, expires_in, interval):
    """Passo 2 (bloqueante - chamar numa thread separada, nunca na thread
    principal do OBS): fica perguntando pra Twitch se a pessoa ja autorizou,
    ate o prazo (expires_in) esgotar."""
    prazo_final = time.time() + expires_in
    intervalo = max(interval, 1)

    while time.time() < prazo_final:
        time.sleep(intervalo)
        resultado = _pedir_token(device_code)

        if resultado.get("pending"):
            continue
        if resultado.get("slow_down"):
            intervalo += 5
            continue
        if "erro" in resultado:
            raise RuntimeError(f"Autorização da Twitch falhou: {resultado['erro']}")

        token = resultado["token"]
        usuario = _buscar_usuario_autenticado(token["access_token"])

        store.salvar_token_twitch_chat_pessoal(
            access_token=token["access_token"],
            refresh_token=token["refresh_token"],
            expires_at=int(time.time() * 1000) + token["expires_in"] * 1000,
            user_id=usuario["id"],
            login=usuario["login"],
        )
        return usuario

    raise RuntimeError("Tempo esgotado esperando a autorização na Twitch (o código expirou).")


def _renovar_token(refresh_token):
    try:
        token = requisitar(
            TOKEN_URL,
            method="POST",
            dados_form={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": CLIENT_ID},
        )
    except ErroHttp as erro:
        raise RuntimeError(f"Falha ao renovar token pessoal da Twitch ({erro.status}): {erro.corpo}") from erro

    tokens_atuais = store.buscar_token_twitch_chat_pessoal()
    store.salvar_token_twitch_chat_pessoal(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token") or refresh_token,
        expires_at=int(time.time() * 1000) + token["expires_in"] * 1000,
        user_id=tokens_atuais.get("userId"),
        login=tokens_atuais.get("login"),
    )
    return token["access_token"]


def obter_access_token_valido():
    tokens = store.buscar_token_twitch_chat_pessoal()
    if not tokens.get("accessToken") or not tokens.get("refreshToken"):
        raise RuntimeError(
            'Conta pessoal da Twitch (chat) ainda não autorizada - clique em "Autorizar minha conta Twitch '
            '(pessoal, pra chat)" nas configurações do script.'
        )

    expira_em = tokens.get("expiresAt")
    if expira_em and int(time.time() * 1000) < expira_em - MARGEM_EXPIRACAO_MS:
        return tokens["accessToken"]

    return _renovar_token(tokens["refreshToken"])


def autorizada():
    tokens = store.buscar_token_twitch_chat_pessoal()
    return bool(tokens.get("accessToken") and tokens.get("refreshToken"))
