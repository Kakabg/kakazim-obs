"""Monitor de status da automacao de troca de cena do CS2.

Hoje essa automacao roda dentro do plugin de Stream Deck "Kakazim.Live"
(projeto kakazim-live, action cs2-scene-switcher) - nao mais no script Node
standalone antigo (Documents/SCRIPTS/cs2-scene-switcher). O plugin so expunha
o servidor de GSI (POST /gsi, sem nada de status); adicionamos um
`GET /status` nesse mesmo servidor (kakazim-live/src/actions/cs2-scene-switcher/
gsi-server.ts e automation-controller.ts) especificamente pra esse painel
conseguir checar via HTTP. Ver o resumo final pra detalhes/passos de rebuild.

Como esse servidor só existe enquanto a automação está "running" (o processo
do plugin de Stream Deck em si fica sempre de pé enquanto o Stream Deck está
aberto, mas só liga o server quando a tecla é ativada), uma conexão recusada
já significa "desligada" - não precisa de um sinal explícito de "off".
"""

import threading

from .. import config
from ..http_util import requisitar

INTERVALO_S = 5
TIMEOUT_S = 2


def _consultar_status():
    url = config.obter("cs2_status_url")
    try:
        corpo = requisitar(url, timeout=TIMEOUT_S)
    except Exception:
        # Sem resposta = automação desligada (ou Stream Deck fechado) - de
        # qualquer forma, não está trocando cena agora.
        return {"ligado": False}

    corpo = corpo or {}
    return {"ligado": bool(corpo.get("rodando")), "obsConectado": bool(corpo.get("obsConectado"))}


class MonitorCs2SceneSwitcher:
    def __init__(self, on_atualizar):
        self._on_atualizar = on_atualizar
        self._parar = threading.Event()
        self._thread = None

    def iniciar(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="cs2-scene-switcher-monitor")
        self._thread.start()

    def parar(self):
        self._parar.set()

    def _loop(self):
        while not self._parar.is_set():
            status = _consultar_status()
            self._on_atualizar("cs2-scene-switcher", status)
            self._parar.wait(INTERVALO_S)
