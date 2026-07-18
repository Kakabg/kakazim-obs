"""Helpers HTTP compartilhados, só com biblioteca padrao (urllib) - evita
depender de "requests" pra chamadas simples de REST/OAuth."""

import json
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_PADRAO = 10


class ErroHttp(Exception):
    def __init__(self, status, corpo):
        super().__init__(f"HTTP {status}: {corpo}")
        self.status = status
        self.corpo = corpo


def requisitar(url, method="GET", headers=None, dados_form=None, dados_json=None, timeout=TIMEOUT_PADRAO):
    """Faz uma requisicao HTTP e devolve o corpo decodificado como JSON (ou
    None se a resposta vier vazia). Lanca ErroHttp em respostas 4xx/5xx."""
    headers = dict(headers or {})
    corpo = None

    if dados_form is not None:
        corpo = urllib.parse.urlencode(dados_form).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif dados_json is not None:
        corpo = json.dumps(dados_json).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=corpo, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            bruto = resp.read().decode("utf-8")
    except urllib.error.HTTPError as erro:
        bruto_erro = erro.read().decode("utf-8", errors="replace")
        raise ErroHttp(erro.code, bruto_erro) from erro

    if not bruto:
        return None
    return json.loads(bruto)


def montar_url(base, params):
    filtrados = {k: v for k, v in params.items() if v is not None}
    query = urllib.parse.urlencode(filtrados)
    return f"{base}?{query}" if query else base
