"""Trilha de auditoria: quem liberou o que, quando, em que maquina.

Append-only, JSON Lines. A senha NUNCA entra no log -- so o indice biometrico
e o login. E esse arquivo que responde "quem autorizou o cancelamento das 14h32".
"""

from __future__ import annotations

import json
import os
import socket
import time

from .vault import pasta_dados

ARQUIVO = os.path.join(pasta_dados(), "auditoria.jsonl")

MAQUINA = socket.gethostname()

# Eventos sensiveis o suficiente para levar uma captura de tela junto.
# ATENCAO: a captura e silenciosa no momento (sem aviso na tela) -- exige
# politica de monitoramento de equipamento/ciencia do funcionario formalizada
# pela empresa (LGPD). Ver nota em captura.py.
EVENTOS_COM_CAPTURA = {
    "autorizacao_concedida", "autorizacao_negada", "autorizacao_bloqueada_app",
    "cadastro", "troca_senha", "exclusao",
}


def registra(evento: str, **campos):
    linha = {
        "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
        "maquina": MAQUINA,
        "evento": evento,
    }
    # blindagem: nunca deixar senha vazar pro log
    campos.pop("senha", None)
    linha.update(campos)
    with open(ARQUIVO, "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def registra_com_captura(evento: str, **campos):
    """Como registra(), mas anexa uma captura de tela do momento para os
    eventos em EVENTOS_COM_CAPTURA; fora dessa lista e igual a registra()."""
    if evento in EVENTOS_COM_CAPTURA:
        from . import captura
        caminho = captura.tira_print(evento)
        if caminho:
            campos["captura"] = caminho
    registra(evento, **campos)


def ultimos(n: int = 200) -> list[dict]:
    if not os.path.exists(ARQUIVO):
        return []
    with open(ARQUIVO, encoding="utf-8") as f:
        linhas = f.readlines()[-n:]
    out = []
    for l in linhas:
        try:
            out.append(json.loads(l))
        except json.JSONDecodeError:
            continue
    return list(reversed(out))
