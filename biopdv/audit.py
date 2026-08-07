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
