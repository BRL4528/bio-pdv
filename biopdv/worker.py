"""Ponte entre o leitor (bloqueante) e a interface (nao pode travar).

Toda operacao biometrica roda numa QThread e reporta progresso por sinal.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from . import reader as rd


class LeitorWorker(QThread):
    """Executa uma operacao do leitor numa thread."""

    progresso = Signal(str)                 # mensagem pro usuario
    captura = Signal(int, int, int, int)    # dedo, total, captura, total
    concluido = Signal(object)              # rd.Resultado
    falhou = Signal(str)

    def __init__(self, porta: str, operacao: str, **kwargs):
        super().__init__()
        self.porta = porta
        self.operacao = operacao
        self.kwargs = kwargs

    def _progresso(self, texto, prog):
        if texto:
            self.progresso.emit(texto)
        if prog:
            self.captura.emit(*prog)

    def run(self):
        try:
            with rd.MorphoReader(self.porta) as leitor:
                if self.operacao == "enroll":
                    res = leitor.enroll(progresso=self._progresso, **self.kwargs)
                elif self.operacao == "identify":
                    res = leitor.identify(progresso=self._progresso, **self.kwargs)
                elif self.operacao == "remove":
                    res = leitor.remove_record(**self.kwargs)
                elif self.operacao == "status":
                    cfg = leitor.base_config()
                    self.concluido.emit(cfg)
                    return
                else:
                    raise ValueError(f"operacao desconhecida: {self.operacao}")
            self.concluido.emit(res)
        except Exception as exc:
            self.falhou.emit(str(exc))
