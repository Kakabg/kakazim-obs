"""Checklist antes da live (issue #2): confere o microfone e os serviços.

As fontes de áudio são lidas do OBS pelo kakazim_obs.py (num timer da thread
principal, a cada poucos segundos) e chegam aqui como uma lista de dicts:

    {"nome": "Mic", "aparelho": "<device_id>", "mudo": False,
     "ativo": True,   # aparece na cena que está no ar (Programa)
     "global": False} # é o "Mic/Aux" global de Configurações > Áudio

`avaliar` é pura (testável sem OBS) e devolve os itens que o painel mostra,
cada um {"chave", "ok": bool | None, "texto", "dica"}. ok None = sem dado.
"""

import time

# Sem atualização da Twitch/Kick há mais que isso = conexão com problema.
LIMITE_SEM_DADOS_MS = 3 * 60 * 1000


def _microfone(fontes, conhecidos):
    if fontes is None:
        return {"chave": "microfone", "ok": None, "texto": "Microfone: lendo o OBS...", "dica": ""}

    globais = [f for f in fontes if f.get("global")]
    if globais:
        return {
            "chave": "microfone",
            "ok": False,
            "texto": "Mic global ligado",
            "dica": "Desligue o Mic/Aux em Configurações > Áudio: ele vaza em todas as cenas.",
        }

    no_ar = [f for f in fontes if f.get("ativo")]
    if not no_ar:
        return {
            "chave": "microfone",
            "ok": False,
            "texto": "Sem microfone na cena",
            "dica": "A cena que está no ar não tem nenhuma fonte de microfone.",
        }
    if len(no_ar) > 1:
        nomes = ", ".join(f.get("nome") or "?" for f in no_ar)
        return {
            "chave": "microfone",
            "ok": False,
            "texto": "2 microfones na cena",
            "dica": f"Mais de um microfone ligado ao mesmo tempo ({nomes}): dá eco ou voz dobrada.",
        }

    mic = no_ar[0]
    if mic.get("mudo"):
        return {"chave": "microfone", "ok": False, "texto": "Microfone no mudo", "dica": f'A fonte "{mic.get("nome")}" está no mudo.'}

    esperado = conhecidos.get(mic.get("nome"))
    if esperado and mic.get("aparelho") and mic.get("aparelho") != esperado:
        return {
            "chave": "microfone",
            "ok": False,
            "texto": "Microfone trocou de aparelho",
            "dica": f'A fonte "{mic.get("nome")}" está usando outro aparelho. Se foi de propósito, clique para aceitar o novo.',
        }

    return {"chave": "microfone", "ok": True, "texto": "Microfone", "dica": f'Usando a fonte "{mic.get("nome")}".'}


def _conexao(chave, nome, atualizado_em, agora_ms):
    if atualizado_em is None:
        return {"chave": chave, "ok": None, "texto": nome, "dica": f"Ainda sem dados da {nome}."}
    ok = agora_ms - atualizado_em <= LIMITE_SEM_DADOS_MS
    return {
        "chave": chave,
        "ok": ok,
        "texto": nome,
        "dica": f"{nome} conectada." if ok else f"Faz mais de 3 minutos sem notícias da {nome}.",
    }


def avaliar(fontes, conhecidos, estado, bot_ok_em, agora_ms=None):
    """Itens do checklist. `estado` = hub._estado (twitch/kick); `bot_ok_em` = última resposta do kakazim-bot (ms)."""
    agora_ms = agora_ms if agora_ms is not None else int(time.time() * 1000)
    itens = [_microfone(fontes, conhecidos)]
    if bot_ok_em is None:
        itens.append({"chave": "bot", "ok": None, "texto": "Bot", "dica": "Ainda sem resposta do kakazim-bot."})
    else:
        ok = agora_ms - bot_ok_em <= 60 * 1000
        itens.append({"chave": "bot", "ok": ok, "texto": "Bot", "dica": "Kakazim-bot respondendo." if ok else "O kakazim-bot não responde há mais de 1 minuto."})
    itens.append(_conexao("twitch", "Twitch", (estado.get("twitch") or {}).get("atualizadoEm"), agora_ms))
    itens.append(_conexao("kick", "Kick", (estado.get("kick") or {}).get("atualizadoEm"), agora_ms))
    return itens
