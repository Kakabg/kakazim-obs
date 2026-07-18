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
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config, hub, store
from .twitch import helix as twitch_helix
from .twitch import oauth as twitch_oauth

ARQUIVOS_ESTATICOS = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/style.css": "style.css",
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

    def do_POST(self):
        caminho = urlparse(self.path).path
        if caminho == "/api/kick/seguidores":
            self._definir_seguidores_kick()
        elif caminho == "/api/twitch/enviar-mensagem":
            self._enviar_mensagem_twitch()
        else:
            self._responder_404()

    # --- rotas ---

    def _servir_estatico(self, nome_arquivo):
        caminho = _public_dir() / nome_arquivo
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

    def _enviar_mensagem_twitch(self):
        tamanho = int(self.headers.get("Content-Length", 0) or 0)
        bruto = self.rfile.read(tamanho) if tamanho else b""

        try:
            corpo = json.loads(bruto or b"{}")
            mensagem = (corpo.get("message") or "").strip()
            if not mensagem:
                raise ValueError("mensagem vazia")
        except (TypeError, ValueError, json.JSONDecodeError):
            self._responder_json({"erro": 'Envie { "message": "<texto>" }.'}, status=400)
            return

        try:
            twitch_helix.enviar_mensagem_chat(mensagem)
        except Exception as erro:
            self._responder_json({"erro": f"Falha ao enviar mensagem no chat da Twitch: {erro}"}, status=502)
            return

        self._responder_json({"ok": True})

    # --- helpers de resposta ---

    def _responder_json(self, dados, status=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
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
