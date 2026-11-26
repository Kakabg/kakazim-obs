"""Doações da LivePix na Atividade recente.

Chegam pelo mesmo relay SSE da Kick (ver hub._ao_receber_evento_relay): o
kakazim-bot recebe o webhook da LivePix, busca o recurso na API e repassa o
objeto como veio ("livepix.message.new" e "livepix.subscription.new").

A API da LivePix pode devolver o objeto direto ou dentro de {"data": ...};
os dois formatos são aceitos. O valor vem em centavos (1000 = R$ 10,00).
"payment.new" não vira linha: toda doação também gera uma "message" (com
ou sem texto), e mostrar os dois duplicaria a mesma doação.
"""


def _objeto(payload):
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def formatar_valor(valor, moeda="BRL"):
    """Centavos -> "R$ 10,00". None quando não dá para ler o valor."""
    try:
        centavos = int(round(float(valor)))
    except (TypeError, ValueError):
        return None
    reais = f"{centavos / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if not moeda or moeda == "BRL":
        return f"R$ {reais}"
    return f"{reais} {moeda}"


def montar_atividade(tipo, payload):
    """Item da Atividade recente para um evento da LivePix, ou None se não vira linha."""
    dados = _objeto(payload)
    usuario = dados.get("username") or dados.get("name") or None

    if tipo == "livepix.message.new":
        valor = formatar_valor(dados.get("amount"), dados.get("currency") or "BRL")
        mensagem = (dados.get("message") or "").strip()
        if valor and mensagem:
            detalhe = f"{valor}: {mensagem}"
        else:
            detalhe = valor or mensagem or None
        return {"plataforma": "livepix", "tipo": "doacao", "usuario": usuario, "detalhe": detalhe}

    if tipo == "livepix.subscription.new":
        return {"plataforma": "livepix", "tipo": "inscricao", "usuario": usuario, "detalhe": "assinatura LivePix"}

    return None
