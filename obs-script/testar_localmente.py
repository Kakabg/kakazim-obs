"""Sobe o painel FORA do OBS, direto no terminal - pra testar antes de
confiar nele dentro do OBS. O modulo `obspython` so existe dentro do processo
do OBS, entao este arquivo nao importa ele: so o pacote kakazim_panel, que e
100% independente do OBS (toda a integracao com obspython fica isolada em
kakazim_obs.py).

Uso:
    python testar_localmente.py

Credenciais vem de variaveis de ambiente (mesmo nome dos campos do script de
OBS, em maiusculo, prefixado com KAKAZIM_). Exemplo (PowerShell):

    $env:KAKAZIM_TWITCH_CLIENT_ID = "..."
    $env:KAKAZIM_TWITCH_CLIENT_SECRET = "..."
    $env:KAKAZIM_TWITCH_BROADCASTER_LOGIN = "kakazim"
    $env:KAKAZIM_KICK_CLIENT_ID = "..."
    $env:KAKAZIM_KICK_CLIENT_SECRET = "..."
    $env:KAKAZIM_KICK_BROADCASTER_SLUG = "kakazim"
    $env:KAKAZIM_KICK_RELAY_SECRET = "..."
    python testar_localmente.py

Sem nenhuma variavel definida, ainda sobe o servidor e serve o frontend
normalmente - so sem falar de verdade com Twitch/Kick. Serve pra confirmar
que o codigo sobe sem erro e a pagina carrega antes de colocar dentro do OBS.
"""

import os
import sys
import time

_DIRETORIO_SCRIPT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIRETORIO_SCRIPT)

from kakazim_panel import config, hub  # noqa: E402
from kakazim_panel.http_server import ServidorHttp  # noqa: E402

config.definir_diretorio_base(_DIRETORIO_SCRIPT)

_valores = {}
for _chave in config.PADROES:
    _valor_env = os.environ.get(f"KAKAZIM_{_chave.upper()}")
    if _valor_env is not None:
        _valores[_chave] = int(_valor_env) if _chave == "porta" else _valor_env
config.atualizar(_valores)

servidor = ServidorHttp()
servidor.iniciar()
hub.iniciar()

porta = config.obter("porta")
print(f"\nPainel de teste rodando em http://localhost:{porta} - Ctrl+C pra parar.\n")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    print("\nEncerrando...")
    hub.parar()
    servidor.parar()
    print("Encerrado.")
