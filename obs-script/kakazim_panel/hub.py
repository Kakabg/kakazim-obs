"""Porta de server/hub.js. Estado central em memoria (thread-safe) + fan-out
pra clientes SSE conectados. Cada subsistema (Twitch, Kick, automacoes) chama
as funcoes daqui pra atualizar o estado e notificar o frontend.
"""

import copy
import threading
import time
import uuid

from . import config, discord_status, store
from .automations.cs2_scene_switcher import MonitorCs2SceneSwitcher
from .kick import stats as kick_stats
from .kick.relay_client import ClienteRelayKick
from .twitch import anuncios_conquistas as twitch_anuncios_conquistas
from .twitch import comandos_chat as twitch_comandos_chat
from .twitch import contagem_mensagens as twitch_contagem_mensagens
from .twitch import helix as twitch_helix
from .twitch import oauth as twitch_oauth
from .twitch import sorteio as twitch_sorteio
from .twitch.eventsub import ClienteEventSub

INTERVALO_VIEWERS_S = 15
INTERVALO_TOTAIS_S = 60
INTERVALO_ANUNCIOS_S = 20
INTERVALO_FALHA_MINIMO_S = 45
INTERVALO_PODA_CHAT_S = 60 * 60
INTERVALO_DISCORD_S = 3

# Intervalo entre mensagens quando mais de um anúncio (bônus + conquista, ou
# várias conquistas de uma vez) precisa ser mandado em sequência - evita
# postar tudo grudado (mesmo espírito do lado da Kick, ver kakazim-bot/
# server.js: processarMensagemChatKick).
INTERVALO_ENTRE_ANUNCIOS_S = 1.2

# Quantos itens de historico mandar no snapshot inicial (SSE "message" tipo
# snapshot) - o resto do historico completo (agora sem limite, ver store.py)
# fica disponivel sob demanda via GET /api/atividades e /api/chat, paginado.
TAMANHO_SNAPSHOT_HISTORICO = 50

_lock = threading.RLock()

_estado = {
    "twitch": {"aoVivo": False, "viewers": 0, "seguidores": None, "inscritos": None},
    "kick": {"aoVivo": False, "viewers": 0, "seguidores": None, "inscritos": None},
    # mutado: None = desconhecido (ainda sem resposta do kakazim-bot, ou o
    # Caíque nunca entrou numa call desde que o bot ligou) - ver
    # discord_status.py. Indicador ainda não validado numa live de verdade.
    "discord": {"mutado": None},
    "atividades": [],
    "chat": [],
    # Pre-semeado com os dois nomes conhecidos hoje - cs2-scene-switcher já
    # aparecia "sempre" na prática porque seu monitor de polling atualiza o
    # estado poucos ms depois do boot (ver _iniciar_automacoes), mas clipador
    # só existe aqui depois do primeiro POST /api/automations/clipador/status
    # (reportar_status_automacao) - sem esse valor default, o chip dele só
    # aparecia na tela depois de ligar/desligar pela 1a vez. Chave nova de
    # automação futura sem monitor de polling nem push ainda tem esse mesmo
    # problema - adicione aqui também.
    "automacoes": {
        "cs2-scene-switcher": {"ligado": False},
        "clipador": {"ligado": False},
    },
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
        _estado["atividades"] = store.listar_atividades_recentes(TAMANHO_SNAPSHOT_HISTORICO)
    _transmitir({"tipo": "atividade", "item": completo})


def _registrar_chat(item):
    completo = {"id": str(uuid.uuid4()), "timestamp": int(time.time() * 1000), **item}
    store.adicionar_chat(completo)
    with _lock:
        _estado["chat"] = store.listar_chat_recentes(TAMANHO_SNAPSHOT_HISTORICO)
    _transmitir({"tipo": "chat", "item": completo})


def _atualizar_automacao(nome, dados):
    with _lock:
        _estado["automacoes"][nome] = dados
    _transmitir({"tipo": "automacao", "nome": nome, "dados": dados})


def reportar_status_automacao(nome, dados):
    """Ponto de entrada publico pra automacoes que reportam o proprio status
    por push (ex: Clipador, kakazim-live - ver POST /api/automations/<nome>/
    status em http_server.py) em vez de serem sondadas por um monitor daqui
    (como o cs2-scene-switcher, ver automations/cs2_scene_switcher.py). Cai
    no mesmo _atualizar_automacao que os monitores de polling usam - o
    frontend (public/app.js) ja trata "nome" de forma generica.
    """
    _atualizar_automacao(nome, dados)


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
        meses = evento.get("cumulative_months")
        texto_mensagem = (evento.get("message") or {}).get("text") or ""
        detalhe = f"renovou por {meses} meses" if meses is not None else "renovação"
        if texto_mensagem:
            detalhe += f": {texto_mensagem}"
        _registrar_atividade(
            {"plataforma": "twitch", "tipo": "inscricao", "usuario": evento.get("user_name"), "detalhe": detalhe}
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
        _responder_comando_chat_twitch(
            evento.get("chatter_user_id"), evento.get("chatter_user_name"), mensagem, evento.get("badges")
        )

        # !sorteio funciona pra QUALQUER UM, incluindo o streamer (precisa
        # conseguir testar/participar) - por isso fica fora do "if not
        # _eh_conta_do_proprio_canal" abaixo, só excluindo o próprio bot
        # (evita ele "participar" ao ecoar o próprio texto, embora isso não
        # devesse acontecer de qualquer forma).
        if not _eh_mensagem_do_bot(evento.get("chatter_user_id")) and (mensagem or "").strip().lower() == "!sorteio":
            texto_sorteio = twitch_sorteio.processar_comando_sorteio(
                evento.get("chatter_user_id"), evento.get("chatter_user_name")
            )
            if texto_sorteio:
                try:
                    twitch_helix.enviar_mensagem_chat(texto_sorteio)
                except Exception as erro:
                    print(f"[Twitch] Falha ao enviar resposta do !sorteio: {erro}")

        # Conta do próprio bot ou do próprio streamer não conta pra quests
        # nem dispara o bônus de "primeira mensagem da vida" (ver
        # contagem_mensagens.py) - não faz sentido o dono do canal ou o bot
        # ganharem o bônus de boas-vindas no próprio chat.
        if not _eh_conta_do_proprio_canal(evento.get("chatter_user_id")):
            resposta = twitch_contagem_mensagens.registrar_mensagem_chat(
                evento.get("chatter_user_id"),
                evento.get("chatter_user_name"),
                mensagem=mensagem,
                cor=evento.get("color"),
            )
            # Lista, não texto único - bônus de boas-vindas e conquista(s)
            # podem vir juntos na mesma mensagem (ver kakazim-bot: banco/
            # quests.js, comentário em montarAnuncioConquista).
            textos_resposta = (resposta or {}).get("responder") or []
            for indice, texto in enumerate(textos_resposta):
                if indice > 0:
                    time.sleep(INTERVALO_ENTRE_ANUNCIOS_S)
                try:
                    twitch_helix.enviar_mensagem_chat(texto)
                except Exception as erro:
                    print(f"[Twitch] Falha ao enviar bônus/anúncio de conquista: {erro}")


def _eh_mensagem_do_bot(chatter_user_id):
    """Só o próprio kakazimbot (conta bot autorizada via /twitch/login?
    role=bot) - evita loop de comando automático respondendo a si mesmo."""
    if chatter_user_id is None:
        return False
    tokens_bot = store.buscar_tokens_twitch("bot")
    bot_user_id = tokens_bot.get("userId")
    return bool(bot_user_id) and str(chatter_user_id) == str(bot_user_id)


def _eh_conta_do_proprio_canal(chatter_user_id):
    """Bot OU o próprio streamer (conta autorizada como canal principal) -
    usado só pra não contar mensagem/bônus de boas-vindas do dono do canal
    (diferente de _eh_mensagem_do_bot: comando automático continua
    respondendo o streamer normalmente, só o bônus/quest é que não faz
    sentido pro dono do próprio chat)."""
    if _eh_mensagem_do_bot(chatter_user_id):
        return True

    try:
        return str(chatter_user_id) == str(twitch_helix.broadcaster_user_id())
    except RuntimeError:
        return False


def _eh_mod_ou_broadcaster_twitch(badges):
    """"Admin" (tier de permissão dos comandos de chat) = moderador ou o
    próprio streamer - badges vem direto do evento EventSub
    channel.chat.message (lista de {set_id, id, info})."""
    if not isinstance(badges, list):
        return False
    return any(badge.get("set_id") in ("moderator", "broadcaster") for badge in badges)


def _responder_comando_chat_twitch(chatter_user_id, chatter_user_name, mensagem, badges):
    """Comando de resposta automática (aba admin "kakazim.bot" do
    Kakaverso). Não responde mensagem do próprio kakazimbot - evita loop
    (comparando com a conta bot autorizada via /twitch/login?role=bot)."""
    if _eh_mensagem_do_bot(chatter_user_id):
        return

    resposta = twitch_comandos_chat.executar_comando(
        mensagem, chatter_user_id, chatter_user_name, _eh_mod_ou_broadcaster_twitch(badges)
    )
    if not resposta:
        return

    try:
        twitch_helix.enviar_mensagem_chat(resposta)
    except Exception as erro:
        print(f"[Twitch] Falha ao responder comando de chat automático: {erro}")


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

    def verificar_anuncios_pendentes():
        # Conquista de CLIPE (detectada no polling do kakazim-bot, sem
        # request nosso em andamento) - ver twitch/anuncios_conquistas.py.
        for indice, texto in enumerate(twitch_anuncios_conquistas.buscar_anuncios_pendentes()):
            if indice > 0:
                time.sleep(INTERVALO_ENTRE_ANUNCIOS_S)
            try:
                twitch_helix.enviar_mensagem_chat(texto)
            except Exception as erro:
                print(f"[Twitch] Falha ao enviar anúncio de conquista pendente: {erro}")

    _iniciar_loop_periodico(atualizar_viewers, INTERVALO_VIEWERS_S, "twitch-viewers")
    _iniciar_loop_periodico(atualizar_totais, INTERVALO_TOTAIS_S, "twitch-totais")
    _iniciar_loop_periodico(verificar_anuncios_pendentes, INTERVALO_ANUNCIOS_S, "twitch-anuncios")

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
                # "bot_local" quando é o evento sintético que o kakazim-bot gera
                # ao enviar mensagem via /api/kick/enviar-mensagem (a Kick não
                # dispara chat.message.sent pra mensagens do próprio app/bot) -
                # ausente/None pra mensagem real de espectador.
                "origem": identidade.get("origem"),
            }
        )


# --- StreamElements ---
# Chega pelo mesmo relay SSE da Kick (ver _ao_receber_evento_relay abaixo) -
# o kakazim-bot manda tanto eventos da Kick quanto da StreamElements (e da
# LivePix, hoje inerte) pelo mesmo outbox/endpoint, diferenciados pelo prefixo
# do "tipo" ("streamelements." aqui).
def _tratar_evento_streamelements(tipo, payload):
    if tipo == "streamelements.tip":
        valor = payload.get("valor")
        moeda = payload.get("moeda")
        mensagem = payload.get("mensagem") or ""

        if valor is not None and moeda:
            valor_formatado = f"R$ {valor}" if moeda == "BRL" else f"{valor} {moeda}"
        else:
            valor_formatado = str(valor) if valor is not None else None

        if valor_formatado and mensagem:
            detalhe = f"{valor_formatado}: {mensagem}"
        else:
            detalhe = valor_formatado or mensagem or None

        _registrar_atividade(
            {"plataforma": "streamelements", "tipo": "doacao", "usuario": payload.get("nome"), "detalhe": detalhe}
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
        tipo = evento.get("tipo")
        payload = evento.get("payload") or {}
        if isinstance(tipo, str) and tipo.startswith("streamelements."):
            _tratar_evento_streamelements(tipo, payload)
        else:
            _tratar_evento_kick(tipo, payload)

    global _relay_cliente
    _relay_cliente = ClienteRelayKick(_ao_receber_evento_relay)
    _relay_cliente.iniciar()


# --- automacoes ---

def _iniciar_automacoes():
    global _monitor_cs2
    _monitor_cs2 = MonitorCs2SceneSwitcher(_atualizar_automacao)
    _monitor_cs2.iniciar()


# --- manutencao ---

def _podar_chat():
    """Só o Chat tem retenção por idade (RETENCAO_CHAT_HORAS em store.py) -
    Atividade recente guarda tudo pra sempre, por pedido explícito."""
    apagadas = store.podar_chat_antigo()
    if apagadas > 0:
        with _lock:
            _estado["chat"] = store.listar_chat_recentes(TAMANHO_SNAPSHOT_HISTORICO)


def _atualizar_status_discord():
    resultado = discord_status.buscar_status_mute()
    if resultado is not None:
        _atualizar_stats("discord", {"mutado": resultado.get("mutado")})


def _iniciar_manutencao():
    _iniciar_loop_periodico(_podar_chat, INTERVALO_PODA_CHAT_S, "poda-chat")
    # Independente de Kick/Twitch estarem configurados - o indicador de mute
    # só depende do kakazim-bot (Discord), roda sempre.
    _iniciar_loop_periodico(_atualizar_status_discord, INTERVALO_DISCORD_S, "discord-mute")


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

def _hidratar_historico():
    """_estado["atividades"]/["chat"] antes ficavam [] até o primeiro evento
    novo chegar (só _registrar_atividade/_registrar_chat os populavam) - um
    cliente que pedisse o snapshot logo depois de um restart do script/OBS
    via um histórico vazio mesmo com tudo intacto no banco. Carrega direto do
    store assim que o hub sobe, então o snapshot já reflete o histórico real
    mesmo antes de qualquer evento novo acontecer."""
    with _lock:
        _estado["atividades"] = store.listar_atividades_recentes(TAMANHO_SNAPSHOT_HISTORICO)
        _estado["chat"] = store.listar_chat_recentes(TAMANHO_SNAPSHOT_HISTORICO)


def iniciar():
    _parar_geral.clear()
    _hidratar_historico()
    _iniciar_twitch()
    _iniciar_kick()
    _iniciar_automacoes()
    _iniciar_manutencao()


def parar():
    _parar_geral.set()
    if _eventsub_cliente is not None:
        _eventsub_cliente.parar()
    if _relay_cliente is not None:
        _relay_cliente.parar()
    if _monitor_cs2 is not None:
        _monitor_cs2.parar()
    _threads_periodicas.clear()
