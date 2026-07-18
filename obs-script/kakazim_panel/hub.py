"""Porta de server/hub.js. Estado central em memoria (thread-safe) + fan-out
pra clientes SSE conectados. Cada subsistema (Twitch, Kick, automacoes) chama
as funcoes daqui pra atualizar o estado e notificar o frontend.
"""

import copy
import threading
import time
import uuid

from . import config, store
from .automations.cs2_scene_switcher import MonitorCs2SceneSwitcher
from .kick import stats as kick_stats
from .kick.relay_client import ClienteRelayKick
from .twitch import helix as twitch_helix
from .twitch import oauth as twitch_oauth
from .twitch.eventsub import ClienteEventSub

INTERVALO_VIEWERS_S = 15
INTERVALO_TOTAIS_S = 60
INTERVALO_FALHA_MINIMO_S = 45

_lock = threading.RLock()

_estado = {
    "twitch": {"aoVivo": False, "viewers": 0, "seguidores": None, "inscritos": None},
    "kick": {"aoVivo": False, "viewers": 0, "seguidores": None, "inscritos": None},
    "atividades": [],
    "chat": [],
    "automacoes": {},
}

_clientes_sse = set()  # de queue.Queue

_parar_geral = threading.Event()
_threads_periodicas = []
_eventsub_cliente = None
_relay_cliente = None
_monitor_cs2 = None


# --- estado e distribuicao pros clientes SSE ---

def registrar_cliente_sse(fila):
    with _lock:
        _clientes_sse.add(fila)
    fila.put({"tipo": "snapshot", "dados": obter_estado()})


def desregistrar_cliente_sse(fila):
    with _lock:
        _clientes_sse.discard(fila)


def _transmitir(mensagem):
    with _lock:
        filas = list(_clientes_sse)
    for fila in filas:
        fila.put(mensagem)


def _atualizar_stats(plataforma, parcial):
    with _lock:
        _estado[plataforma].update(parcial)
        copia = dict(_estado[plataforma])
    _transmitir({"tipo": "stats", "plataforma": plataforma, "dados": copia})


def _registrar_atividade(item):
    completo = {"id": str(uuid.uuid4()), "timestamp": int(time.time() * 1000), **item}
    store.adicionar_atividade(completo)
    with _lock:
        _estado["atividades"] = store.listar_atividades()
    _transmitir({"tipo": "atividade", "item": completo})


def _registrar_chat(item):
    completo = {"id": str(uuid.uuid4()), "timestamp": int(time.time() * 1000), **item}
    store.adicionar_chat(completo)
    with _lock:
        _estado["chat"] = store.listar_chat()
    _transmitir({"tipo": "chat", "item": completo})


def _atualizar_automacao(nome, dados):
    with _lock:
        _estado["automacoes"][nome] = dados
    _transmitir({"tipo": "automacao", "nome": nome, "dados": dados})


def definir_total_seguidores_kick(total):
    store.definir_total_seguidores_kick(total)
    _atualizar_stats("kick", {"seguidores": total})


def obter_estado():
    with _lock:
        return copy.deepcopy(_estado)


# --- Twitch ---

def _tratar_evento_twitch(tipo, evento):
    if tipo == "channel.follow":
        _registrar_atividade({"plataforma": "twitch", "tipo": "seguidor", "usuario": evento.get("user_name")})
        with _lock:
            atual = _estado["twitch"]["seguidores"]
        if atual is not None:
            _atualizar_stats("twitch", {"seguidores": atual + 1})
        return

    if tipo == "channel.subscribe":
        detalhe = "presenteada" if evento.get("is_gift") else None
        _registrar_atividade(
            {"plataforma": "twitch", "tipo": "inscricao", "usuario": evento.get("user_name"), "detalhe": detalhe}
        )
        with _lock:
            atual = _estado["twitch"]["inscritos"]
        if atual is not None:
            _atualizar_stats("twitch", {"inscritos": atual + 1})
        return

    if tipo == "channel.subscription.message":
        # Resub (renovação) - diferente de channel.subscribe, que só dispara na
        # primeira inscrição. Não mexe no total de inscritos: a Twitch não
        # manda channel.subscribe de novo pra quem já tava inscrito.
        _registrar_atividade(
            {"plataforma": "twitch", "tipo": "inscricao", "usuario": evento.get("user_name"), "detalhe": "renovação"}
        )
        return

    if tipo == "channel.raid":
        _registrar_atividade(
            {
                "plataforma": "twitch",
                "tipo": "raid",
                "usuario": evento.get("from_broadcaster_user_name"),
                "detalhe": str(evento.get("viewers")) if evento.get("viewers") is not None else None,
            }
        )
        return

    if tipo == "channel.chat.message":
        mensagem = (evento.get("message") or {}).get("text", "")
        _registrar_chat(
            {
                "plataforma": "twitch",
                "usuario": evento.get("chatter_user_name"),
                "mensagem": mensagem,
                "cor": evento.get("color") or None,
            }
        )


def _iniciar_twitch():
    if not twitch_oauth.autorizada():
        porta = config.obter("porta")
        print(f"[Twitch] Ainda não autorizado. Acesse http://localhost:{porta}/twitch/login uma vez.")
        return

    def atualizar_viewers():
        _atualizar_stats("twitch", twitch_helix.buscar_viewers_atuais())

    def atualizar_totais():
        seguidores = twitch_helix.buscar_total_seguidores()
        inscritos = twitch_helix.buscar_total_inscritos()
        _atualizar_stats("twitch", {"seguidores": seguidores, "inscritos": inscritos})

    _iniciar_loop_periodico(atualizar_viewers, INTERVALO_VIEWERS_S, "twitch-viewers")
    _iniciar_loop_periodico(atualizar_totais, INTERVALO_TOTAIS_S, "twitch-totais")

    global _eventsub_cliente
    _eventsub_cliente = ClienteEventSub(_tratar_evento_twitch)
    _eventsub_cliente.iniciar()


# --- Kick ---

def _tratar_evento_kick(tipo, payload):
    if tipo in ("channel.subscription.new", "channel.subscription.renewal"):
        detalhe = "renovação" if tipo == "channel.subscription.renewal" else None
        _registrar_atividade(
            {
                "plataforma": "kick",
                "tipo": "inscricao",
                "usuario": (payload.get("subscriber") or {}).get("username"),
                "detalhe": detalhe,
            }
        )
        return

    if tipo == "channel.followed":
        _registrar_atividade(
            {"plataforma": "kick", "tipo": "seguidor", "usuario": (payload.get("follower") or {}).get("username")}
        )
        novo_total = store.incrementar_seguidores_kick(1)
        if novo_total is not None:
            _atualizar_stats("kick", {"seguidores": novo_total})
        return

    if tipo == "chat.message.sent":
        sender = payload.get("sender") or {}
        identidade = sender.get("identity") or {}
        _registrar_chat(
            {
                "plataforma": "kick",
                "usuario": sender.get("username"),
                "mensagem": payload.get("content", ""),
                "cor": identidade.get("username_color"),
            }
        )


def _iniciar_kick():
    kick_salvo = store.buscar_kick()
    if kick_salvo.get("followerTotal") is not None:
        with _lock:
            _estado["kick"]["seguidores"] = kick_salvo["followerTotal"]

    if not config.obter("kick_client_id") or not config.obter("kick_client_secret") or not config.obter("kick_broadcaster_slug"):
        print("[Kick] Client ID/Secret/slug do canal não configurados - sem estatísticas (viewers/inscritos) da Kick.")
    else:
        def atualizar_stats_kick():
            _atualizar_stats("kick", kick_stats.buscar_stats())

        _iniciar_loop_periodico(atualizar_stats_kick, INTERVALO_VIEWERS_S, "kick-stats")

    if not config.obter("kick_relay_url") or not config.obter("kick_relay_secret"):
        print("[Kick] URL/segredo do relay não configurados - sem feed de atividade/chat da Kick.")
        return

    def _ao_receber_evento_relay(evento):
        _tratar_evento_kick(evento.get("tipo"), evento.get("payload") or {})

    global _relay_cliente
    _relay_cliente = ClienteRelayKick(_ao_receber_evento_relay)
    _relay_cliente.iniciar()


# --- automacoes ---

def _iniciar_automacoes():
    global _monitor_cs2
    _monitor_cs2 = MonitorCs2SceneSwitcher(_atualizar_automacao)
    _monitor_cs2.iniciar()


# --- helper de polling periodico ---

def _iniciar_loop_periodico(func, intervalo_s, nome):
    def alvo():
        falhas_seguidas = 0
        while not _parar_geral.is_set():
            try:
                func()
                falhas_seguidas = 0
                espera = intervalo_s
            except Exception as erro:
                falhas_seguidas += 1
                # Só avisa na 1a falha e depois de vez em quando, senão spamma
                # o log pra sempre enquanto a causa (ex: credenciais erradas)
                # não for corrigida.
                if falhas_seguidas == 1 or falhas_seguidas % 20 == 0:
                    print(f"[{nome}] Erro: {erro}")
                espera = max(intervalo_s, INTERVALO_FALHA_MINIMO_S)
            _parar_geral.wait(espera)

    thread = threading.Thread(target=alvo, daemon=True, name=nome)
    thread.start()
    _threads_periodicas.append(thread)
    return thread


# --- ciclo de vida (chamado por kakazim_obs.py / testar_localmente.py) ---

def iniciar():
    _parar_geral.clear()
    _iniciar_twitch()
    _iniciar_kick()
    _iniciar_automacoes()


def parar():
    _parar_geral.set()
    if _eventsub_cliente is not None:
        _eventsub_cliente.parar()
    if _relay_cliente is not None:
        _relay_cliente.parar()
    if _monitor_cs2 is not None:
        _monitor_cs2.parar()
    _threads_periodicas.clear()
