"""Configuracao central do painel, em memoria - equivalente ao process.env do
backend Node original (server/index.js e afins), so que os valores vem da UI
nativa de Scripts do OBS (script_properties/script_update) em vez de um .env.

Fica num dict simples protegido por lock porque varias threads (servidor HTTP,
cliente EventSub da Twitch, cliente do relay da Kick, pollers) leem essa
configuracao a qualquer momento.
"""

import threading
from urllib.parse import urlparse

_lock = threading.Lock()

PADROES = {
    "porta": 8420,
    "twitch_client_id": "",
    "twitch_client_secret": "",
    "twitch_broadcaster_login": "",
    "kick_client_id": "",
    "kick_client_secret": "",
    "kick_broadcaster_slug": "",
    "kick_relay_url": "https://kakazim-bot-production.up.railway.app/painel/eventos",
    "kick_relay_secret": "",
    "cs2_status_url": "http://127.0.0.1:3211/status",
}

_config = dict(PADROES)

# Preenchido pelo ponto de entrada (kakazim_obs.py ou testar_localmente.py),
# aponta pra pasta obs-script/ - usado por store.py e http_server.py pra achar
# data/ e public/ sem depender do diretorio de trabalho atual.
diretorio_base = None


def definir_diretorio_base(caminho):
    global diretorio_base
    diretorio_base = caminho


def obter(chave):
    with _lock:
        return _config.get(chave)


def obter_tudo():
    with _lock:
        return dict(_config)


def atualizar(valores):
    """Atualiza 1+ chaves de uma vez. Só aceita chaves já conhecidas em PADROES,
    pra evitar erro de digitação silencioso vindo do lado do OBS."""
    with _lock:
        for chave, valor in valores.items():
            if chave not in PADROES:
                raise KeyError(f"Config desconhecida: {chave}")
            _config[chave] = valor


def url_base_kakazim_bot():
    """Deriva esquema+host do kakazim-bot a partir de kick_relay_url (já
    configurado pro relay de eventos) - não usa o caminho dele
    (/painel/eventos), só a origem. Reaproveitado por qualquer chamada HTTP
    pro kakazim-bot (renovação de token pessoal da Kick, comandos de chat
    automático da Twitch etc)."""
    partes = urlparse(obter("kick_relay_url"))
    return f"{partes.scheme}://{partes.netloc}"
