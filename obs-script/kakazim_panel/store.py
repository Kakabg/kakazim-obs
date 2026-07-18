"""Persistencia local em JSON - porta de server/store.js (projeto Node original).

Guarda: tokens da Twitch, total de seguidores da Kick (cadastro manual + os
incrementos ao vivo) e os buffers de feed de atividade / chat, pra sobreviver a
um reload do Browser Source no OBS ou a um "Reload Scripts".
"""

import copy
import json
import os
import threading
import time
from pathlib import Path

from . import config

CAP_ATIVIDADES = 200
CAP_CHAT = 200

_ESTADO_PADRAO = {
    "twitch": {
        "accessToken": None,
        "refreshToken": None,
        "expiresAt": None,
        "userId": None,
        "login": None,
    },
    "kick": {
        "followerTotal": None,
        "followerSeedEm": None,
    },
    "atividades": [],
    "chat": [],
}

_lock = threading.Lock()
_estado = None


def _arquivo():
    return Path(config.diretorio_base) / "data" / "store.json"


def _carregar():
    try:
        with open(_arquivo(), "r", encoding="utf-8") as f:
            bruto = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return copy.deepcopy(_ESTADO_PADRAO)

    estado = copy.deepcopy(_ESTADO_PADRAO)
    for chave in estado:
        if chave in bruto:
            estado[chave] = bruto[chave]
    return estado


def _obter_estado():
    global _estado
    if _estado is None:
        _estado = _carregar()
    return _estado


def _salvar():
    """Escrita atomica (escreve num .tmp e renomeia) pra nao corromper o
    store.json se o processo morrer/OBS fechar no meio de uma gravacao."""
    caminho = _arquivo()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.parent / (caminho.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_estado, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


def salvar_tokens_twitch(access_token, refresh_token, expires_at, user_id, login):
    with _lock:
        estado = _obter_estado()
        estado["twitch"] = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": expires_at,
            "userId": user_id,
            "login": login,
        }
        _salvar()


def buscar_tokens_twitch():
    with _lock:
        return dict(_obter_estado()["twitch"])


def definir_total_seguidores_kick(total):
    with _lock:
        estado = _obter_estado()
        estado["kick"]["followerTotal"] = total
        estado["kick"]["followerSeedEm"] = int(time.time() * 1000)
        _salvar()


def incrementar_seguidores_kick(delta=1):
    with _lock:
        estado = _obter_estado()
        if estado["kick"]["followerTotal"] is None:
            return None
        estado["kick"]["followerTotal"] += delta
        _salvar()
        return estado["kick"]["followerTotal"]


def buscar_kick():
    with _lock:
        return dict(_obter_estado()["kick"])


def adicionar_atividade(item):
    with _lock:
        estado = _obter_estado()
        estado["atividades"].append(item)
        if len(estado["atividades"]) > CAP_ATIVIDADES:
            estado["atividades"] = estado["atividades"][-CAP_ATIVIDADES:]
        _salvar()


def listar_atividades():
    with _lock:
        return list(_obter_estado()["atividades"])


def adicionar_chat(item):
    with _lock:
        estado = _obter_estado()
        estado["chat"].append(item)
        if len(estado["chat"]) > CAP_CHAT:
            estado["chat"] = estado["chat"][-CAP_CHAT:]
        _salvar()


def listar_chat():
    with _lock:
        return list(_obter_estado()["chat"])
