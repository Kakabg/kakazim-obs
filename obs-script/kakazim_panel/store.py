"""Persistencia local - porta de server/store.js (projeto Node original).

Guarda em JSON (store.json): tokens da Twitch, total de seguidores da Kick
(cadastro manual + os incrementos ao vivo) e o cursor do relay de eventos da
Kick. Guarda em SQLite (painel.db): o historico completo de atividades e chat
- crescem sem limite (nao e mais um buffer circular capado), pra dar um
historico persistente de verdade e paginavel em vez de um feed que reseta
sempre que o script do OBS reinicia.

Atividades ficam pra sempre. Chat tem retencao de RETENCAO_CHAT_HORAS (poda
periodica chamada por hub.py) - mensagem de chat e volume alto e baixo valor
historico depois de um tempo, diferente de atividade (sub/follow), que o
usuario pediu explicitamente pra nunca apagar.
"""

import copy
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from . import config

# Só o Chat tem poda automática por idade - Atividade recente guarda tudo pra
# sempre, por pedido explícito (mensagem de chat é alto volume e baixo valor
# histórico depois de um tempo; atividade tipo sub/follow não).
RETENCAO_CHAT_HORAS = 48

_ESTADO_TOKEN_TWITCH_PADRAO = {
    "accessToken": None,
    "refreshToken": None,
    "expiresAt": None,
    "userId": None,
    "login": None,
}

PAPEIS_TWITCH = ("streamer", "bot")

# Tokens da conta PESSOAL do streamer (Kakabg), separados de "twitch"/"kick"
# acima (que guardam streamer-leitura/bot) - usados exclusivamente pela caixa
# de chat direto do painel (ver twitch/device_auth_pessoal.py e
# kick/oauth_pessoal.py). Formato próprio em vez de reaproveitar PAPEIS_TWITCH
# porque são fluxos de autorização completamente diferentes (device code com
# app público vs. authorization_code+PKCE com app dedicado da Kick).
_ESTADO_TOKEN_PESSOAL_TWITCH_PADRAO = {
    "accessToken": None,
    "refreshToken": None,
    "expiresAt": None,
    "userId": None,
    "login": None,
}

_ESTADO_TOKEN_PESSOAL_KICK_PADRAO = {
    "accessToken": None,
    "refreshToken": None,
    "expiresAt": None,
    "userId": None,
    "nome": None,
}

_ESTADO_PADRAO = {
    "twitch": {
        "streamer": dict(_ESTADO_TOKEN_TWITCH_PADRAO),
        "bot": dict(_ESTADO_TOKEN_TWITCH_PADRAO),
    },
    "twitch_chat_pessoal": dict(_ESTADO_TOKEN_PESSOAL_TWITCH_PADRAO),
    "kick_chat_pessoal": dict(_ESTADO_TOKEN_PESSOAL_KICK_PADRAO),
    "kick": {
        "followerTotal": None,
        "followerSeedEm": None,
        # Maior id de evento (banco/db.js: eventos_painel, no kakazim-bot) ja
        # recebido do relay - mandado de volta como ?desde= na reconexao pra
        # nao perder eventos que chegaram enquanto o painel estava
        # desconectado (ver kick/relay_client.py).
        "ultimoEventoRelayId": None,
    },
}

_lock = threading.Lock()
_estado = None
_conexao_db = None


def _arquivo_json():
    return Path(config.diretorio_base) / "data" / "store.json"


def _arquivo_db():
    return Path(config.diretorio_base) / "data" / "painel.db"


def _migrar_estado_twitch(bruto_twitch):
    """Antes desta mudanca, estado["twitch"] guardava direto um unico token
    (do streamer) num dict achatado. Agora vira um token por papel
    (streamer/bot), pra dar espaco pra conta de bot separada - isso migra o
    formato antigo na primeira carga sem perder o token ja autorizado."""
    padrao = {papel: dict(_ESTADO_TOKEN_TWITCH_PADRAO) for papel in PAPEIS_TWITCH}
    if not isinstance(bruto_twitch, dict):
        return padrao

    if "accessToken" in bruto_twitch:
        padrao["streamer"] = bruto_twitch
        return padrao

    for papel in PAPEIS_TWITCH:
        if papel in bruto_twitch:
            padrao[papel] = bruto_twitch[papel]
    return padrao


def _carregar_bruto():
    try:
        with open(_arquivo_json(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _carregar():
    bruto = _carregar_bruto()

    estado = copy.deepcopy(_ESTADO_PADRAO)
    for chave in estado:
        if chave in bruto:
            estado[chave] = bruto[chave]
    estado["twitch"] = _migrar_estado_twitch(bruto.get("twitch"))
    # kick pode vir de um store.json anterior a essa mudanca, sem
    # ultimoEventoRelayId - preenche o que faltar sem perder followerTotal.
    estado["kick"] = {**_ESTADO_PADRAO["kick"], **estado.get("kick", {})}
    return estado


def _obter_estado():
    global _estado
    if _estado is None:
        _estado = _carregar()
    return _estado


def _salvar():
    """Escrita atomica (escreve num .tmp e renomeia) pra nao corromper o
    store.json se o processo morrer/OBS fechar no meio de uma gravacao."""
    caminho = _arquivo_json()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.parent / (caminho.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_estado, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


def salvar_tokens_twitch(access_token, refresh_token, expires_at, user_id, login, papel="streamer"):
    if papel not in PAPEIS_TWITCH:
        raise ValueError(f"Papel de token Twitch inválido: {papel}")
    with _lock:
        estado = _obter_estado()
        estado["twitch"][papel] = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": expires_at,
            "userId": user_id,
            "login": login,
        }
        _salvar()


def buscar_tokens_twitch(papel="streamer"):
    if papel not in PAPEIS_TWITCH:
        raise ValueError(f"Papel de token Twitch inválido: {papel}")
    with _lock:
        return dict(_obter_estado()["twitch"][papel])


def salvar_token_twitch_chat_pessoal(access_token, refresh_token, expires_at, user_id, login):
    with _lock:
        estado = _obter_estado()
        estado["twitch_chat_pessoal"] = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": expires_at,
            "userId": user_id,
            "login": login,
        }
        _salvar()


def buscar_token_twitch_chat_pessoal():
    with _lock:
        return dict(_obter_estado()["twitch_chat_pessoal"])


def salvar_token_kick_chat_pessoal(access_token, refresh_token, expires_at, user_id, nome):
    with _lock:
        estado = _obter_estado()
        estado["kick_chat_pessoal"] = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": expires_at,
            "userId": user_id,
            "nome": nome,
        }
        _salvar()


def buscar_token_kick_chat_pessoal():
    with _lock:
        return dict(_obter_estado()["kick_chat_pessoal"])


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


def definir_ultimo_evento_relay_kick(id_evento):
    with _lock:
        estado = _obter_estado()
        estado["kick"]["ultimoEventoRelayId"] = id_evento
        _salvar()


def buscar_ultimo_evento_relay_kick():
    with _lock:
        return _obter_estado()["kick"]["ultimoEventoRelayId"]


# --- historico (SQLite, sem limite - ver docstring do modulo) ---


def _obter_conexao():
    global _conexao_db
    if _conexao_db is not None:
        return _conexao_db

    caminho = _arquivo_db()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(str(caminho), check_same_thread=False)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA journal_mode = WAL")
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS atividades (
            id TEXT PRIMARY KEY,
            timestamp INTEGER NOT NULL,
            plataforma TEXT,
            tipo TEXT,
            usuario TEXT,
            detalhe TEXT
        )
        """
    )
    conexao.execute("CREATE INDEX IF NOT EXISTS idx_atividades_timestamp ON atividades (timestamp)")
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS chat (
            id TEXT PRIMARY KEY,
            timestamp INTEGER NOT NULL,
            plataforma TEXT,
            usuario TEXT,
            mensagem TEXT,
            cor TEXT,
            origem TEXT,
            sub INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conexao.execute("CREATE INDEX IF NOT EXISTS idx_chat_timestamp ON chat (timestamp)")
    # Banco de uma execucao anterior (antes de "sub" existir) nao ganha a
    # coluna nova so com o CREATE TABLE IF NOT EXISTS acima - SQLite nao tem
    # "ADD COLUMN IF NOT EXISTS" portavel entre versoes, entao tenta e ignora
    # o erro de coluna duplicada (banco ja migrado).
    try:
        conexao.execute("ALTER TABLE chat ADD COLUMN sub INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conexao.commit()

    _migrar_historico_legado(conexao)

    _conexao_db = conexao
    return _conexao_db


def _migrar_historico_legado(conexao):
    """Antes desta mudanca, atividades/chat viviam num array capado (200
    itens) dentro do proprio store.json. Se essa chave ainda existir num
    store.json antigo e as tabelas novas estiverem vazias, importa esse
    historico uma unica vez em vez de simplesmente descarta-lo na migracao."""
    bruto = _carregar_bruto()

    if conexao.execute("SELECT COUNT(*) FROM atividades").fetchone()[0] == 0:
        for item in bruto.get("atividades") or []:
            _inserir_atividade(conexao, item)

    if conexao.execute("SELECT COUNT(*) FROM chat").fetchone()[0] == 0:
        for item in bruto.get("chat") or []:
            _inserir_chat(conexao, item)

    conexao.commit()


def _inserir_atividade(conexao, item):
    conexao.execute(
        """
        INSERT OR REPLACE INTO atividades (id, timestamp, plataforma, tipo, usuario, detalhe)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            item["id"],
            item["timestamp"],
            item.get("plataforma"),
            item.get("tipo"),
            item.get("usuario"),
            item.get("detalhe"),
        ),
    )


def _inserir_chat(conexao, item):
    conexao.execute(
        """
        INSERT OR REPLACE INTO chat (id, timestamp, plataforma, usuario, mensagem, cor, origem, sub)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item["id"],
            item["timestamp"],
            item.get("plataforma"),
            item.get("usuario"),
            item.get("mensagem"),
            item.get("cor"),
            item.get("origem"),
            1 if item.get("sub") else 0,
        ),
    )


def _linha_para_atividade(linha):
    return {
        "id": linha["id"],
        "timestamp": linha["timestamp"],
        "plataforma": linha["plataforma"],
        "tipo": linha["tipo"],
        "usuario": linha["usuario"],
        "detalhe": linha["detalhe"],
    }


def _linha_para_chat(linha):
    return {
        "id": linha["id"],
        "timestamp": linha["timestamp"],
        "plataforma": linha["plataforma"],
        "usuario": linha["usuario"],
        "mensagem": linha["mensagem"],
        "cor": linha["cor"],
        "origem": linha["origem"],
        "sub": bool(linha["sub"]),
    }


def adicionar_atividade(item):
    with _lock:
        conexao = _obter_conexao()
        _inserir_atividade(conexao, item)
        conexao.commit()


def adicionar_chat(item):
    with _lock:
        conexao = _obter_conexao()
        _inserir_chat(conexao, item)
        conexao.commit()


def listar_atividades_recentes(limite=50):
    """Os `limite` itens mais novos, em ordem crescente (mais antigo
    primeiro) - pronto pro snapshot inicial do frontend (prependAtividade)."""
    with _lock:
        conexao = _obter_conexao()
        linhas = conexao.execute(
            "SELECT * FROM atividades ORDER BY timestamp DESC LIMIT ?", (limite,)
        ).fetchall()
    return [_linha_para_atividade(linha) for linha in reversed(linhas)]


def buscar_ultimo_sub_follow():
    """Item mais recente de sub/follow/renovação de QUALQUER plataforma
    (Kick e Twitch usam os mesmos valores de `tipo` - "seguidor"/"inscricao",
    ver hub.py:_tratar_evento_kick/_tratar_evento_twitch) - usado pelo botão
    "Repetir último alerta" do Stream Deck (ver http_server.py:
    POST /api/atividades/repetir-ultimo-sub-follow). None se não houver
    nenhum registrado ainda."""
    with _lock:
        conexao = _obter_conexao()
        linha = conexao.execute(
            "SELECT * FROM atividades WHERE tipo IN ('seguidor', 'inscricao') ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
    return _linha_para_atividade(linha) if linha else None


def listar_atividades_pagina(antes_de=None, limite=50):
    """Pagina de itens mais antigos que `antes_de` (timestamp em ms), em
    ordem decrescente - usado pelo "carregar mais" no scroll do feed."""
    with _lock:
        conexao = _obter_conexao()
        if antes_de is None:
            linhas = conexao.execute(
                "SELECT * FROM atividades ORDER BY timestamp DESC LIMIT ?", (limite,)
            ).fetchall()
        else:
            linhas = conexao.execute(
                "SELECT * FROM atividades WHERE timestamp < ? ORDER BY timestamp DESC LIMIT ?",
                (antes_de, limite),
            ).fetchall()
    return [_linha_para_atividade(linha) for linha in linhas]


def listar_chat_recentes(limite=50):
    with _lock:
        conexao = _obter_conexao()
        linhas = conexao.execute(
            "SELECT * FROM chat ORDER BY timestamp DESC LIMIT ?", (limite,)
        ).fetchall()
    return [_linha_para_chat(linha) for linha in reversed(linhas)]


def listar_chat_pagina(antes_de=None, limite=50):
    with _lock:
        conexao = _obter_conexao()
        if antes_de is None:
            linhas = conexao.execute(
                "SELECT * FROM chat ORDER BY timestamp DESC LIMIT ?", (limite,)
            ).fetchall()
        else:
            linhas = conexao.execute(
                "SELECT * FROM chat WHERE timestamp < ? ORDER BY timestamp DESC LIMIT ?",
                (antes_de, limite),
            ).fetchall()
    return [_linha_para_chat(linha) for linha in linhas]


def podar_chat_antigo(retencao_horas=RETENCAO_CHAT_HORAS):
    """Apaga mensagens de chat mais velhas que `retencao_horas`. Não mexe em
    atividades - essas ficam pra sempre (ver docstring do módulo)."""
    corte = int(time.time() * 1000) - retencao_horas * 60 * 60 * 1000
    with _lock:
        conexao = _obter_conexao()
        cursor = conexao.execute("DELETE FROM chat WHERE timestamp < ?", (corte,))
        conexao.commit()
    return cursor.rowcount
