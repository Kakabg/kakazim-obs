"""Aba "Subs" do card de atividade (GET /api/subs, ver http_server.py).

Junta duas fontes, só quando a aba é aberta (nada de polling) e com cache
de CACHE_S segundos:
- Twitch: lista OFICIAL de subs ativos na Helix (GET /subscriptions, token
  do streamer que o painel já tem com channel:read:subscriptions) - nome,
  tier, gift. A Twitch não dá data de vencimento na Helix: a data vem do
  kakazim-bot - "real" quando veio de um evento de sub/resub (data do
  evento + 30 dias), senão estimativa da conferência diária de lá.
- Kick: não existe endpoint de subs na Kick - vem do kakazim-bot
  (GET /painel/subs), com o vencimento oficial dos webhooks (expires_at).

Se uma das fontes falhar, devolve a outra com um aviso em vez de nada.
"""

import threading
import time

from . import config
from .http_util import ErroHttp, montar_url, requisitar
from .twitch import helix

CACHE_S = 5 * 60
TIER_TWITCH = {"1000": "Tier 1", "2000": "Tier 2", "3000": "Tier 3"}

_lock = threading.Lock()
_cache = {"dados": None, "em": 0.0}


def _subs_twitch_oficiais():
    broadcaster_id = helix.broadcaster_user_id()
    subs, cursor = [], None
    while True:
        params = {"broadcaster_id": broadcaster_id, "first": 100}
        if cursor:
            params["after"] = cursor
        corpo = helix._chamar_helix("subscriptions", params) or {}
        subs.extend(corpo.get("data") or [])
        cursor = (corpo.get("pagination") or {}).get("cursor")
        if not cursor:
            break
    return [s for s in subs if str(s.get("user_id")) != str(broadcaster_id)]


def _dados_do_bot():
    url = montar_url(f"{config.url_base_kakazim_bot()}/painel/subs", {"key": config.obter("kick_relay_secret")})
    try:
        return requisitar(url) or {}
    except ErroHttp as erro:
        raise RuntimeError(f"kakazim-bot respondeu {erro.status} em /painel/subs") from erro


def montar_lista(subs_twitch, dados_bot):
    """Pura (sem rede) - junta as duas fontes e ordena do que vence primeiro.
    Sem data (Twitch sem estimativa nenhuma) vai pro fim."""
    vencimentos = (dados_bot or {}).get("twitchVencimentos")
    if vencimentos is None:
        # kakazim-bot antigo (antes de mandar real/estimado): tudo estimativa.
        vencimentos = {
            uid: {"expiraEm": data, "real": False}
            for uid, data in ((dados_bot or {}).get("twitchEstimativas") or {}).items()
        }
    itens = []

    for sub in subs_twitch or []:
        venc = vencimentos.get(str(sub.get("user_id"))) or {}
        itens.append(
            {
                "plataforma": "twitch",
                "nome": sub.get("user_name") or sub.get("user_login"),
                "tier": TIER_TWITCH.get(str(sub.get("tier")), sub.get("tier")),
                "gift": bool(sub.get("is_gift")),
                "expiraEm": venc.get("expiraEm"),
                "estimativa": not venc.get("real", False),
            }
        )

    for sub in (dados_bot or {}).get("kick") or []:
        itens.append(
            {
                "plataforma": "kick",
                "nome": sub.get("nome"),
                "kickUserId": sub.get("kickUserId"),
                "tier": None,
                "gift": False,
                "expiraEm": sub.get("expiraEm"),
                "estimativa": False,
            }
        )

    itens.sort(key=lambda item: (item["expiraEm"] is None, item["expiraEm"] or ""))
    return itens


def buscar(forcar=False):
    with _lock:
        if not forcar and _cache["dados"] is not None and time.time() - _cache["em"] < CACHE_S:
            return _cache["dados"]

    avisos = []
    subs_twitch, dados_bot = [], {}
    try:
        subs_twitch = _subs_twitch_oficiais()
    except Exception as erro:  # noqa: BLE001 - qualquer falha vira aviso, não derruba a aba
        avisos.append(f"Twitch: {erro}")
    try:
        dados_bot = _dados_do_bot()
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"Kick/estimativas (kakazim-bot): {erro}")

    dados = {"subs": montar_lista(subs_twitch, dados_bot), "avisos": avisos, "atualizadoEm": int(time.time() * 1000)}
    with _lock:
        # Falha total não fica 5 min no cache - a próxima abertura tenta de novo.
        if len(avisos) < 2:
            _cache["dados"], _cache["em"] = dados, time.time()
    return dados
