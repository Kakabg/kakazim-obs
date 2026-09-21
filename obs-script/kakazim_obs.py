"""Script de OBS (Tools > Scripts) que sobe o painel local da live (Kick +
Twitch) como um servidor HTTP em background, nativamente junto com o OBS -
sem precisar de terminal nem processo Node separado.

Ve o README.md nesta pasta pra instrucoes de instalacao (Python, dependencia
"websocket-client", apps da Twitch/Kick).

IMPORTANTE sobre threading: os callbacks deste arquivo (script_load,
script_update etc.) rodam na thread principal do OBS - qualquer chamada de
rede feita diretamente aqui travaria a interface toda. Por isso eles so
disparam threads em background (ver kakazim_panel/hub.py e http_server.py) e
nunca fazem I/O bloqueante por conta propria.
"""

import os
import sys
import threading
import webbrowser

# Garante que o pacote kakazim_panel (irmao deste arquivo) seja importavel,
# independente de qual diretorio o OBS usou como cwd ao carregar o script.
_DIRETORIO_SCRIPT = os.path.dirname(os.path.abspath(__file__))
if _DIRETORIO_SCRIPT not in sys.path:
    sys.path.insert(0, _DIRETORIO_SCRIPT)

import obspython as obs  # noqa: E402  (precisa vir depois do sys.path.insert)

from kakazim_panel import config, hub, store  # noqa: E402
from kakazim_panel.http_server import ServidorHttp  # noqa: E402
from kakazim_panel.kick import oauth_pessoal as kick_oauth_pessoal  # noqa: E402
from kakazim_panel.twitch import device_auth_pessoal as twitch_device_auth_pessoal  # noqa: E402

config.definir_diretorio_base(_DIRETORIO_SCRIPT)

_servidor_http = ServidorHttp()
_iniciado = False
_ultimo_seed_kick_aplicado = None

# (id da propriedade, rotulo, e se e um campo de senha)
_CAMPOS_TEXTO = [
    ("twitch_client_id", "Twitch: Client ID", False),
    ("twitch_client_secret", "Twitch: Client Secret", True),
    ("twitch_broadcaster_login", "Twitch: login do canal (ex: kakazim)", False),
    ("kick_client_id", "Kick: Client ID", False),
    ("kick_client_secret", "Kick: Client Secret", True),
    ("kick_broadcaster_slug", "Kick: slug do canal (ex: kakazim)", False),
    ("kick_relay_url", "Kick: URL do relay (kakazim-bot no Railway)", False),
    ("kick_relay_secret", "Kick: segredo do relay (PAINEL_RELAY_SECRET)", True),
    ("cs2_status_url", "Automação CS2: URL de status", False),
]


def script_description():
    return (
        "<h2>Painel da live (Kakazim)</h2>"
        "<p>Sobe um servidor local com estatísticas, feed de atividade e chat "
        "unificado de Kick + Twitch, pra usar como Browser Source no OBS.</p>"
        "<p>Preencha as credenciais abaixo, aplique, clique em "
        '"Autorizar Twitch" (conta principal, leitura/stats) e em '
        '"Autorizar Twitch (bot)" (conta separada que manda mensagem no chat) '
        "uma vez cada e depois adicione "
        "<code>http://localhost:&lt;porta&gt;</code> como Browser Source.</p>"
        "<p>Pra caixa de chat direto do painel (embaixo do Chat), autorize também sua "
        'conta PESSOAL (não o bot) em "Autorizar minha conta Twitch (pessoal, pra chat)" '
        'e "Autorizar minha conta Kick (pessoal, pra chat)" - as duas passam por serviços '
        "que já ficam sempre de pé (Twitch direto, Kick via kakazim-bot no Railway), sem "
        "precisar rodar nada extra no seu PC. Ver README.md.</p>"
        "<p>Detalhes e passos completos no README.md da pasta deste script.</p>"
    )


def script_defaults(settings):
    obs.obs_data_set_default_int(settings, "porta", config.PADROES["porta"])
    for chave, _rotulo, _senha in _CAMPOS_TEXTO:
        obs.obs_data_set_default_string(settings, chave, config.PADROES[chave])
    obs.obs_data_set_default_int(settings, "kick_seguidores_atual", 0)


def _reiniciar_conexoes(props, prop):
    print("[Painel] Reiniciando conexões (Twitch/Kick/automações)...")
    hub.parar()
    hub.iniciar()
    return True


def _autorizar_twitch_pessoal_chat(props, prop):
    """Botão "Autorizar minha conta Twitch (pessoal, pra chat)" - dispara o
    Device Authorization Grant (kakazim_panel/twitch/device_auth_pessoal.py).
    Mantém o callback rápido (só o passo 1, uma chamada HTTP única) e joga o
    passo 2 (polling até a pessoa confirmar no navegador) pra uma thread -
    callbacks de botão do OBS rodam na thread principal, então nada
    bloqueante pode ficar aqui."""
    try:
        inicio = twitch_device_auth_pessoal.iniciar_device_authorization()
    except Exception as erro:
        print(f"[Painel] Falha ao iniciar autorização pessoal da Twitch (chat): {erro}")
        return True

    minutos = inicio["expires_in"] // 60
    print(
        f'[Painel] Twitch (pessoal, chat): abra {inicio["verification_uri"]} e digite o código '
        f'{inicio["user_code"]} (expira em {minutos} min). Abrindo o navegador...'
    )
    try:
        webbrowser.open(inicio["verification_uri"])
    except Exception as erro_navegador:
        print(f"[Painel] Não consegui abrir o navegador automaticamente ({erro_navegador}) - abra a URL acima na mão.")

    def _aguardar():
        try:
            usuario = twitch_device_auth_pessoal.aguardar_autorizacao(
                inicio["device_code"], inicio["expires_in"], inicio["interval"]
            )
            print(f"[Painel] Twitch (pessoal, chat) autorizada: {usuario['login']}. A caixa de chat do painel já pode usar essa conta.")
        except Exception as erro_autorizacao:
            print(f"[Painel] Autorização pessoal da Twitch (chat) falhou: {erro_autorizacao}")

    threading.Thread(target=_aguardar, daemon=True, name="twitch-device-auth-pessoal").start()
    return True


def script_properties():
    props = obs.obs_properties_create()
    porta_atual = config.obter("porta") or config.PADROES["porta"]

    obs.obs_properties_add_int(props, "porta", "Porta do painel local", 1024, 65535, 1)

    for chave, rotulo, senha in _CAMPOS_TEXTO:
        tipo = obs.OBS_TEXT_PASSWORD if senha else obs.OBS_TEXT_DEFAULT
        obs.obs_properties_add_text(props, chave, rotulo, tipo)

    botao_login_twitch = obs.obs_properties_add_button(
        props, "abrir_twitch_login", "🔗 Autorizar Twitch (abre no navegador)", lambda p, pr: True
    )
    obs.obs_property_button_set_type(botao_login_twitch, obs.OBS_BUTTON_URL)
    obs.obs_property_button_set_url(botao_login_twitch, f"http://localhost:{porta_atual}/twitch/login")

    botao_login_twitch_bot = obs.obs_properties_add_button(
        props, "abrir_twitch_login_bot", "🤖 Autorizar Twitch (bot, abre no navegador)", lambda p, pr: True
    )
    obs.obs_property_button_set_type(botao_login_twitch_bot, obs.OBS_BUTTON_URL)
    obs.obs_property_button_set_url(botao_login_twitch_bot, f"http://localhost:{porta_atual}/twitch/login?role=bot")
    obs.obs_property_set_long_description(
        botao_login_twitch_bot,
        "Autoriza a conta separada da Twitch usada só pra mandar mensagem no chat (ex: kakazimbot) - não "
        "precisa ser moderadora de canal nenhum, só ter o escopo user:write:chat autorizado aqui. O botão de "
        "cima continua sendo só pra sua conta principal (leitura/stats). Fique logado como a conta bot no "
        "navegador ANTES de clicar: quem decide qual conta autoriza é a sessão do navegador na tela de "
        "consentimento da Twitch, não este botão - use uma aba anônima ou outro perfil do navegador se já "
        "estiver logado como você mesmo.",
    )

    botao_twitch_pessoal_chat = obs.obs_properties_add_button(
        props,
        "autorizar_twitch_pessoal_chat",
        "💬 Autorizar minha conta Twitch (pessoal, pra chat)",
        _autorizar_twitch_pessoal_chat,
    )
    obs.obs_property_set_long_description(
        botao_twitch_pessoal_chat,
        "Autoriza a SUA conta pessoal da Twitch (não o kakazimbot) só com o escopo de mandar mensagem no "
        "chat, exclusivo pra caixa de texto do painel (embaixo do Chat). Abre uma página da Twitch "
        "(twitch.tv/activate) e um código pra você digitar - acompanhe o console de Scripts (embaixo desta "
        "janela) pro código e o status. Nada mais no projeto usa essa autorização (Enviar Mensagem do Stream "
        "Deck e avisos automáticos continuam no kakazimbot).",
    )

    url_login_kick_pessoal = kick_oauth_pessoal.montar_url_login(porta_atual)
    botao_kick_pessoal_chat = obs.obs_properties_add_button(
        props,
        "abrir_kick_login_pessoal",
        "💬 Autorizar minha conta Kick (pessoal, pra chat, abre no navegador)",
        lambda p, pr: True,
    )
    obs.obs_property_button_set_type(botao_kick_pessoal_chat, obs.OBS_BUTTON_URL)
    obs.obs_property_button_set_url(botao_kick_pessoal_chat, url_login_kick_pessoal)
    obs.obs_property_set_long_description(
        botao_kick_pessoal_chat,
        "Autoriza a SUA conta pessoal da Kick (não o kakazimbot) pra caixa de texto do painel - reaproveita o "
        "mesmo app OAuth do kakazimbot na Kick (ela só permite 2 apps por conta, já em uso) via uma rota nova "
        "no kakazim-bot (sempre de pé no Railway - não depende de nada rodando no seu PC além deste painel "
        "mesmo). Depois de autorizar, o kakazim-bot entrega o token de volta pra este painel sozinho (o "
        "navegador que faz a entrega, já que o Railway não alcança o seu PC diretamente). Fique logado como "
        "sua conta pessoal (Kakabg) no navegador antes de clicar. Ver README.md pro fluxo completo.",
    )

    prop_seed = obs.obs_properties_add_int(
        props, "kick_seguidores_atual", "Kick: definir/resetar total de seguidores", 0, 100_000_000, 1
    )
    obs.obs_property_set_long_description(
        prop_seed,
        "Não existe endpoint oficial da Kick que devolva esse total, então é cadastrado na mão aqui uma vez. "
        "Depois disso o próprio painel incrementa sozinho a cada novo seguidor. Só digite um valor novo aqui "
        "de novo se quiser resetar/corrigir o número (o painel em si, no navegador, sempre mostra o valor "
        "atual e correto - esse campo é só pra definir o ponto de partida ou corrigir).",
    )

    botao_painel = obs.obs_properties_add_button(props, "abrir_painel", "🖥️ Abrir o painel no navegador", lambda p, pr: True)
    obs.obs_property_button_set_type(botao_painel, obs.OBS_BUTTON_URL)
    obs.obs_property_button_set_url(botao_painel, f"http://localhost:{porta_atual}")

    obs.obs_properties_add_button(props, "reiniciar", "🔄 Reiniciar conexões (após mudar credenciais)", _reiniciar_conexoes)

    return props


def _ler_config_de_settings(settings):
    valores = {"porta": obs.obs_data_get_int(settings, "porta") or config.PADROES["porta"]}
    for chave, _rotulo, _senha in _CAMPOS_TEXTO:
        valores[chave] = obs.obs_data_get_string(settings, chave)
    return valores


def script_update(settings):
    global _ultimo_seed_kick_aplicado

    porta_anterior = config.obter("porta")
    config.atualizar(_ler_config_de_settings(settings))

    seed_atual = obs.obs_data_get_int(settings, "kick_seguidores_atual")
    if _ultimo_seed_kick_aplicado is not None and seed_atual != _ultimo_seed_kick_aplicado:
        print(f"[Painel] Total de seguidores da Kick redefinido manualmente pra {seed_atual}.")
        hub.definir_total_seguidores_kick(seed_atual)
    _ultimo_seed_kick_aplicado = seed_atual

    nova_porta = config.obter("porta")
    if _iniciado and nova_porta != porta_anterior:
        print(f"[Painel] Porta mudou de {porta_anterior} pra {nova_porta}, reiniciando servidor HTTP...")
        _servidor_http.parar()
        _servidor_http.iniciar()


def script_load(settings):
    global _iniciado, _ultimo_seed_kick_aplicado

    config.atualizar(_ler_config_de_settings(settings))
    # Captura o valor do campo "seguidores" como ele estiver ao carregar (seja
    # o default 0 ou algo salvo de uma sessão anterior) - só tratamos como
    # "o usuário quer redefinir" quando esse número mudar depois disso.
    _ultimo_seed_kick_aplicado = obs.obs_data_get_int(settings, "kick_seguidores_atual")

    if _iniciado:
        return

    _servidor_http.iniciar()
    hub.iniciar()
    _iniciado = True


def script_unload():
    global _iniciado
    print("[Painel] Desligando (script_unload)...")
    hub.parar()
    _servidor_http.parar()
    _iniciado = False
