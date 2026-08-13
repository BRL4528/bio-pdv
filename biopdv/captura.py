"""Captura de tela silenciosa para auditoria de eventos sensiveis.

Usa QScreen.grabWindow (PySide6 -- zero dependencia nova, sem PIL/mss). Nao
mostra nada na tela, nao pisca, nao pede permissao: e uma chamada sincrona de
GDI que ja roda no processo do app. Salva so localmente, nunca pela rede --
mesmo espirito do auditoria.jsonl (local, append-only, nunca a senha).

Isso e monitoramento de equipamento da empresa vinculado a um evento
auditavel especifico (liberacao/negacao por digital, cadastro, troca de
senha, exclusao) -- nao gravacao continua. Alinhar com a politica de
monitoramento/ciencia do funcionario (LGPD) e responsabilidade de quem
implanta, nao deste modulo.
"""

from __future__ import annotations

import os
import time

from .vault import pasta_dados

RETENCAO_DIAS = 90

PASTA_CAPTURAS = os.path.join(pasta_dados(), "capturas")


def tira_print(evento: str) -> str | None:
    """Salva um PNG da tela atual e devolve o caminho, ou None se falhar.

    Nunca levanta excecao -- uma captura falha nao pode impedir o fluxo
    principal (liberar a senha, cadastrar o supervisor etc.).
    """
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return None

        tela = app.primaryScreen()
        if tela is None:
            return None

        pixmap = tela.grabWindow(0)
        os.makedirs(PASTA_CAPTURAS, exist_ok=True)
        nome = f"{time.strftime('%Y%m%d_%H%M%S')}_{evento}.png"
        caminho = os.path.join(PASTA_CAPTURAS, nome)
        if not pixmap.save(caminho, "PNG"):
            return None

        _poda_antigas()
        return caminho
    except Exception:
        return None


def _poda_antigas() -> None:
    limite = time.time() - RETENCAO_DIAS * 86400
    try:
        for nome in os.listdir(PASTA_CAPTURAS):
            caminho = os.path.join(PASTA_CAPTURAS, nome)
            if os.path.isfile(caminho) and os.path.getmtime(caminho) < limite:
                os.remove(caminho)
    except OSError:
        pass
