"""Porta de server/index.js. Servidor HTTP local, só biblioteca padrão
(http.server + ThreadingHTTPServer) - cada conexão roda na sua própria
thread, então a conexão /events (SSE, de vida longa) não trava as outras
rotas nem o servidor.

Precisa rodar serve_forever() numa thread separada da chamada de
script_load/script_update do OBS - essas rodam na thread principal do OBS, e
uma chamada bloqueante ali travaria a interface inteira.
"""

import json
import mimetypes
import queue
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config, hub, store, streamelements
from .kick import chat as kick_chat
from .kick import oauth_pessoal as kick_oauth_pessoal
from .twitch import chat_pessoal as twitch_chat_pessoal
from .twitch import helix as twitch_helix
from .twitch import oauth as twitch_oauth

ARQUIVOS_ESTATICOS = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/style.css": "style.css",
}

# Mecanismo generico de push pra automacoes locais sem servidor HTTP proprio
# reportarem o proprio status - alternativa ao monitor de polling do
# cs2-scene-switcher (que ja roda seu proprio servidor HTTP pro GSI e so
# precisou ganhar um GET /status nele). Ver hub.reportar_status_automacao.
PADRAO_STATUS_AUTOMACAO = re.compile(r"^/api/automations/([a-z0-9-]+)/status$")

# Única rota chamada por JS rodando numa página de outro ORIGIN (o callback
# do kakazim-bot, servido em https://kakazim-bot-production.up.railway.app -
# ver README.md "Sobre a conta pessoal"). Navegadores modernos bloqueiam por
# padrão fetch() de uma página pública/HTTPS pra um endereço "local"
# (Private Network Access, ver https://developer.chrome.com/blog/private-network-access-preflight)
# como 127.0.0.1 - precisam de um preflight OPTIONS respondido com os
# cabeçalhos abaixo pra deixar passar. Nenhuma outra rota deste servidor
# precisa disso (todo o resto só é chamado pelo próprio front-end do painel,
# mesmo origin).
ROTAS_CORS_PRIVATE_NETWORK = {"/api/kick/chat-pessoal/token"}


def _cabecalhos_cors():
    # Sem credenciais (a autenticação é o "key" dentro do corpo JSON, não
    # cookie), então "*" é seguro aqui - não precisa ecoar o Origin.
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Private-Network": "true",
    }


def _public_dir():
    return Path(config.diretorio_base) / "public"


class Handler(BaseHTTPRequestHandler):
    server_version = "KakazimPainel/1.0"

    def log_message(self, format, *args):
        # Silencia o log de acesso padrão pra não poluir o console de Scripts do OBS.
        pass

    def do_GET(self):
        partes = urlparse(self.path)
        caminho = partes.path

        if caminho in ARQUIVOS_ESTATICOS:
            self._servir_estatico(ARQUIVOS_ESTATICOS[caminho])
        elif caminho.startswith("/vendor/"):
            self._servir_estatico(caminho.lstrip("/"))
        elif caminho == "/events":
            self._servir_sse()
        elif caminho == "/api/state":
            self._responder_json(hub.obter_estado())
        elif caminho == "/api/atividades":
            self._listar_historico(store.listar_atividades_pagina, parse_qs(partes.query))
        elif caminho == "/api/chat":
            self._listar_historico(store.listar_chat_pagina, parse_qs(partes.query))
        elif caminho == "/twitch/login":
            self._twitch_login(parse_qs(partes.query))
        elif caminho == "/twitch/callback":
            self._twitch_callback()
        else:
            self._responder_404()

    def do_OPTIONS(self):
        caminho = urlparse(self.path).path
        if caminho not in ROTAS_CORS_PRIVATE_NETWORK:
            self._responder_404()
            return

        # Resposta ao preflight CORS/Private Network Access - sem isso o
        # navegador nem chega a mandar o POST de verdade (ver
        # ROTAS_CORS_PRIVATE_NETWORK acima).
        self.send_response(204)
        for chave, valor in _cabecalhos_cors().items():
            self.send_header(chave, valor)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        caminho = urlparse(self.path).path
        correspondencia_automacao = PADRAO_STATUS_AUTOMACAO.match(caminho)

        if caminho == "/api/kick/seguidores":
            self._definir_seguidores_kick()
        elif caminho == "/api/twitch/enviar-mensagem":
            self._enviar_mensagem_twitch()
        elif caminho == "/api/chat/mensagem":
            self._enviar_mensagem_chat()
        elif caminho == "/api/kick/chat-pessoal/token":
            self._receber_token_kick_pessoal()
        elif caminho == "/api/atividades/repetir":
            self._repetir_atividade()
        elif correspondencia_automacao:
            self._reportar_status_automacao(correspondencia_automacao.group(1))
        else:
            self._responder_404()

    # --- rotas ---

    def _servir_estatico(self, nome_arquivo):
        base = _public_dir().resolve()
        caminho = (base / nome_arquivo).resolve()
        if base not in caminho.parents and caminho != base:
            self._responder_404()
            return

        try:
            conteudo = caminho.read_bytes()
        except OSError:
            self._responder_404()
            return

        tipo, _ = mimetypes.guess_type(str(caminho))
        self.send_response(200)
        self.send_header("Content-Type", tipo or "application/octet-stream")
        self.send_header("Content-Length", str(len(conteudo)))
        self.end_headers()
        self.wfile.write(conteudo)

    def _servir_sse(self):
        fila = queue.Queue()
        hub.registrar_cliente_sse(fila)

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            while True:
                mensagem = fila.get()
                linha = f"data: {json.dumps(mensagem, ensure_ascii=False)}\n\n"
                self.wfile.write(linha.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass
        finally:
            hub.desregistrar_cliente_sse(fila)

    # Paginação do histórico (Atividade recente / Chat) pra "carregar mais" no
    # scroll do frontend - o snapshot inicial (/api/state, /events) só traz os
    # últimos TAMANHO_SNAPSHOT_HISTORICO itens (ver hub.py), o resto do
    # histórico completo (sem limite, ver store.py) vive aqui.
    def _listar_historico(self, funcao_pagina, query):
        antes_bruto = query.get("antes", [None])[0]
        limite_bruto = query.get("limite", [None])[0]

        try:
            antes_de = int(antes_bruto) if antes_bruto else None
            limite = min(int(limite_bruto), 200) if limite_bruto else 50
        except (TypeError, ValueError):
            self._responder_json({"erro": "Parâmetros antes/limite inválidos."}, status=400)
            return

        itens = funcao_pagina(antes_de=antes_de, limite=limite)
        self._responder_json({"itens": itens})

    def _twitch_login(self, query):
        papel = (query.get("role") or ["streamer"])[0]
        if papel not in store.PAPEIS_TWITCH:
            self._responder_texto("Parâmetro role inválido (use streamer ou bot).", status=400)
            return
        self._redirecionar(twitch_oauth.construir_url_autorizacao(papel=papel))

    def _twitch_callback(self):
        query = parse_qs(urlparse(self.path).query)
        code = query.get("code", [None])[0]
        state = query.get("state", [None])[0]
        erro = query.get("error", [None])[0]

        if erro:
            self._responder_texto(f"Autorização negada pela Twitch: {erro}", status=400)
            return
        if not code or not state:
            self._responder_texto("Faltam os parâmetros code/state no callback.", status=400)
            return

        try:
            usuario, papel = twitch_oauth.trocar_code_por_token(code, state)
        except Exception as erro_troca:
            self._responder_texto(f"Falha ao concluir a autorização com a Twitch: {erro_troca}", status=500)
            return

        rotulo_papel = "conta bot" if papel == "bot" else "conta principal"
        self._responder_texto(
            f"Twitch autorizada ({rotulo_papel}): {usuario.get('display_name')}. Pode fechar essa aba - clique em "
            '"🔄 Reiniciar conexões" nas configurações do script (Tools > Scripts) pra ativar o chat/feed em tempo real.'
        )

    # Conta PESSOAL do streamer na Kick (chat:write), exclusiva pra caixa de
    # chat do painel - ver kick/oauth_pessoal.py. Não tem OAuth próprio aqui
    # (a Kick só permite 2 apps por conta, e os dois já estão em uso): o
    # botão "Autorizar minha conta Kick (pessoal, pra chat)" abre uma rota
    # nova no kakazim-bot (GET /kick/login/painel-obs), que reaproveita o
    # app do kakazimbot pra fazer o OAuth de verdade. O Railway (onde o
    # kakazim-bot roda) não alcança 127.0.0.1 nesta máquina, então é o
    # NAVEGADOR do usuário (via JS na página de callback do kakazim-bot)
    # quem entrega o token aqui - autenticado com o mesmo segredo já usado
    # pro resto da integração com o kakazim-bot (config: kick_relay_secret /
    # kakazim-bot: PAINEL_RELAY_SECRET).
    def _receber_token_kick_pessoal(self):
        # Chamada via fetch() pela página de callback do kakazim-bot, servida
        # noutro origin (https://kakazim-bot-production.up.railway.app) -
        # toda resposta (sucesso ou erro) precisa dos cabeçalhos CORS, senão
        # o navegador bloqueia o JS de ler o resultado mesmo que a chamada em
        # si tenha ido bem. Ver ROTAS_CORS_PRIVATE_NETWORK/do_OPTIONS acima.
        cors = _cabecalhos_cors()

        tamanho = int(self.headers.get("Content-Length", 0) or 0)
        bruto = self.rfile.read(tamanho) if tamanho else b""

        try:
            corpo = json.loads(bruto or b"{}")
        except json.JSONDecodeError:
            self._responder_json({"erro": "Corpo inválido (esperava JSON)."}, status=400, cabecalhos_extra=cors)
            return

        segredo_esperado = config.obter("kick_relay_secret")
        if not segredo_esperado or corpo.get("key") != segredo_esperado:
            self._responder_json({"erro": "Acesso negado."}, status=403, cabecalhos_extra=cors)
            return

        campos_obrigatorios = ("access_token", "refresh_token", "expires_in")
        if any(not corpo.get(campo) for campo in campos_obrigatorios):
            self._responder_json(
                {"erro": 'Envie { "key", "access_token", "refresh_token", "expires_in", "user_id", "name" }.'},
                status=400,
                cabecalhos_extra=cors,
            )
            return

        try:
            kick_oauth_pessoal.receber_token(corpo)
        except Exception as erro:
            self._responder_json(
                {"erro": f"Falha ao guardar o token recebido: {erro}"}, status=500, cabecalhos_extra=cors
            )
            return

        print(f"[Painel] Kick (conta pessoal, chat) autorizada via kakazim-bot: {corpo.get('name')}.")
        self._responder_json({"ok": True}, cabecalhos_extra=cors)

    def _definir_seguidores_kick(self):
        tamanho = int(self.headers.get("Content-Length", 0) or 0)
        bruto = self.rfile.read(tamanho) if tamanho else b""

        try:
            corpo = json.loads(bruto or b"{}")
            total = int(corpo.get("total"))
            if total < 0:
                raise ValueError("total negativo")
        except (TypeError, ValueError, json.JSONDecodeError):
            self._responder_json({"erro": 'Envie { "total": <número> }.'}, status=400)
            return

        hub.definir_total_seguidores_kick(total)
        self._responder_json({"ok": True, "total": total})

    def _reportar_status_automacao(self, nome):
        tamanho = int(self.headers.get("Content-Length", 0) or 0)
        bruto = self.rfile.read(tamanho) if tamanho else b""

        try:
            corpo = json.loads(bruto or b"{}")
            ligado = corpo["ligado"]
            if not isinstance(ligado, bool):
                raise ValueError("ligado não é bool")
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            self._responder_json({"erro": 'Envie { "ligado": <true|false> }.'}, status=400)
            return

        hub.reportar_status_automacao(nome, corpo)
        self._responder_json({"ok": True})

    # Caixa de texto do painel (embaixo do Chat) - sempre manda pro canal do
    # próprio streamer, na plataforma escolhida no seletor ao lado do
    # cabeçalho "Chat" (ver public/index.html e public/app.js). Diferente de
    # /api/twitch/enviar-mensagem (usado pelo plugin de Stream Deck, que
    # escolhe um canal de destino qualquer), aqui não há campo de canal.
    #
    # Única rota do projeto que usa a conta PESSOAL do streamer (Kakabg) em
    # vez do kakazimbot - ver twitch/chat_pessoal.py e kick/chat.py.
    def _enviar_mensagem_chat(self):
        tamanho = int(self.headers.get("Content-Length", 0) or 0)
        bruto = self.rfile.read(tamanho) if tamanho else b""

        try:
            corpo = json.loads(bruto or b"{}")
            plataforma = (corpo.get("plataforma") or "").strip()
            mensagem = (corpo.get("message") or "").strip()
            if plataforma not in ("kick", "twitch") or not mensagem:
                raise ValueError("dados inválidos")
        except (TypeError, ValueError, json.JSONDecodeError):
            self._responder_json(
                {"erro": 'Envie { "plataforma": "kick"|"twitch", "message": "<texto>" }.'}, status=400
            )
            return

        try:
            if plataforma == "twitch":
                twitch_chat_pessoal.enviar_mensagem_chat(mensagem)
            else:
                kick_chat.enviar_mensagem_chat(mensagem)
        except Exception as erro:
            nome_plataforma = "Twitch" if plataforma == "twitch" else "Kick"
            self._responder_json({"erro": f"Falha ao enviar mensagem no chat da {nome_plataforma}: {erro}"}, status=502)
            return

        self._responder_json({"ok": True})

    # Ícone "repetir" em cada item da Atividade recente (ver public/app.js) -
    # repassa o próprio item pro kakazim-bot repetir o alerta na StreamElements
    # (ver kakazim_panel/streamelements.py). O item chega pronto no corpo (o
    # frontend já tem tipo/plataforma/usuario/detalhe renderizados, sem
    # precisar de um lookup por id aqui) - funciona pra QUALQUER item da
    # lista, não só o mais recente.
    def _repetir_atividade(self):
        tamanho = int(self.headers.get("Content-Length", 0) or 0)
        bruto = self.rfile.read(tamanho) if tamanho else b""

        try:
            corpo = json.loads(bruto or b"{}")
            item = {
                "tipo": corpo.get("tipo"),
                "plataforma": corpo.get("plataforma"),
                "usuario": corpo.get("usuario"),
                "detalhe": corpo.get("detalhe"),
            }
            if not item["tipo"] or not item["plataforma"]:
                raise ValueError("tipo/plataforma ausentes")
        except (TypeError, ValueError, json.JSONDecodeError):
            self._responder_json({"erro": 'Envie { "tipo", "plataforma", "usuario", "detalhe" }.'}, status=400)
            return

        try:
            streamelements.repetir_evento(item)
        except RuntimeError as erro:
            self._responder_json({"erro": str(erro)}, status=502)
            return

        self._responder_json({"ok": True})

    def _enviar_mensagem_twitch(self):
        tamanho = int(self.headers.get("Content-Length", 0) or 0)
        bruto = self.rfile.read(tamanho) if tamanho else b""

        try:
            corpo = json.loads(bruto or b"{}")
            mensagem = (corpo.get("message") or "").strip()
            canal = (corpo.get("channel") or "").strip() or None
            if not mensagem:
                raise ValueError("mensagem vazia")
        except (TypeError, ValueError, json.JSONDecodeError):
            self._responder_json({"erro": 'Envie { "message": "<texto>", "channel": "<login da Twitch>" }.'}, status=400)
            return

        try:
            twitch_helix.enviar_mensagem_chat(mensagem, canal=canal)
        except Exception as erro:
            self._responder_json({"erro": f"Falha ao enviar mensagem no chat da Twitch: {erro}"}, status=502)
            return

        self._responder_json({"ok": True})

    # --- helpers de resposta ---

    def _responder_json(self, dados, status=200, cabecalhos_extra=None):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        for chave, valor in (cabecalhos_extra or {}).items():
            self.send_header(chave, valor)
        self.end_headers()
        self.wfile.write(corpo)


    def _responder_texto(self, texto, status=200):
        corpo = texto.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _redirecionar(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def _responder_404(self):
        self._responder_texto("Não encontrado.", status=404)


class ServidorHttp:
    """Dono do ciclo de vida do servidor HTTP local. serve_forever() bloqueia,
    então roda numa thread própria - nunca na thread principal do OBS."""

    def __init__(self):
        self._servidor = None
        self._thread = None

    def iniciar(self):
        porta = config.obter("porta")
        self._servidor = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
        self._thread = threading.Thread(target=self._servidor.serve_forever, daemon=True, name="http-server")
        self._thread.start()
        print(f"[Painel] Escutando em http://localhost:{porta}")

    def parar(self):
        if self._servidor is not None:
            # shutdown() só para o loop de aceitar conexões novas - conexões
            # /events já abertas (o Browser Source do OBS) ficam presas até o
            # processo do OBS encerrar de vez, mas como são threads daemon
            # isso não impede o OBS de fechar normalmente.
            self._servidor.shutdown()
            self._servidor.server_close()
            self._servidor = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
