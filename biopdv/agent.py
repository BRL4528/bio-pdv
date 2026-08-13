"""Agente do PDV: botao flutuante + atalho global -> digital -> digita a senha.

O DETALHE QUE DECIDE TUDO: a janela flutuante nao pode roubar o foco. Se roubar,
o campo de senha do PDV perde o cursor e a digitacao vai pro vazio.

  Qt.WindowDoesNotAcceptFocus  -> clicar nao ativa a janela (WS_EX_NOACTIVATE)
  Qt.Tool                      -> nao aparece na barra de tarefas / Alt+Tab
  Qt.WindowStaysOnTopHint      -> fica sobre o PDV em tela cheia
  Qt.FramelessWindowHint       -> sem barra de titulo
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from . import audit, inject
from .vault import Vault
from .worker import LeitorWorker

OCIOSO, LENDO, OK, ERRO = "ocioso", "lendo", "ok", "erro"

CORES = {
    OCIOSO: ("#2d6cdf", "Digital"),
    LENDO: ("#e0a800", "Encoste"),
    OK: ("#28a745", "Liberado"),
    ERRO: ("#dc3545", "Negado"),
}


class BotaoFlutuante(QWidget):
    """Bolha redonda sempre visivel, que nunca rouba o foco."""

    clicado = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(96, 96)
        self.estado = OCIOSO
        self._arrastando = False
        self._offset = QPoint()

        self.rotulo = QLabel("", self)
        self.rotulo.setAlignment(Qt.AlignCenter)
        self.rotulo.setStyleSheet("color:white; font-size:11px; font-weight:600;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.rotulo)
        self.define_estado(OCIOSO)

    def define_estado(self, estado: str, texto: str | None = None):
        self.estado = estado
        cor, padrao = CORES[estado]
        self.rotulo.setText(texto or padrao)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cor = QColor(CORES[self.estado][0])
        p.setBrush(cor)
        p.setPen(QPen(QColor(255, 255, 255, 200), 3))
        p.drawEllipse(4, 4, self.width() - 8, self.height() - 8)

    # arrastar com o botao esquerdo; clique curto dispara
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._arrastando = False
            self._offset = e.globalPosition().toPoint() - self.pos()
            self._inicio = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            novo = e.globalPosition().toPoint()
            if (novo - self._inicio).manhattanLength() > 6:
                self._arrastando = True
            self.move(novo - self._offset)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and not self._arrastando:
            self.clicado.emit()


class AgentePDV:
    """Orquestra: clique/atalho -> identify -> digita a senha no campo em foco."""

    def __init__(self, porta: str, vault: Vault, enter_no_fim: bool = False,
                 timeout: int = 20):
        self.porta = porta
        self.vault = vault
        self.enter_no_fim = enter_no_fim
        self.timeout = timeout
        self.ocupado = False
        self.worker: LeitorWorker | None = None

        self.botao = BotaoFlutuante()
        self.botao.clicado.connect(self.aciona)
        tela = QApplication.primaryScreen().availableGeometry()
        self.botao.move(tela.right() - 130, tela.bottom() - 160)
        self.botao.show()

    # --- fluxo --------------------------------------------------------------

    def aciona(self):
        if self.ocupado:
            return
        self.ocupado = True
        self.botao.define_estado(LENDO, "Encoste")
        janela, processo = "", ""
        try:
            janela = inject.janela_em_foco()
            processo = inject.processo_em_foco()
        except Exception:
            pass
        self._janela_alvo = janela
        self._processo_alvo = processo

        self.worker = LeitorWorker(self.porta, "identify", timeout=self.timeout)
        self.worker.progresso.connect(self._progresso)
        self.worker.concluido.connect(self._concluido)
        self.worker.falhou.connect(self._falhou)
        self.worker.start()

    def _progresso(self, texto: str):
        curto = {"Encoste o dedo no leitor": "Encoste",
                 "Pressione com mais firmeza": "Aperte",
                 "Limpe o sensor": "Limpe",
                 "Pode remover o dedo": "Ok",
                 "Captura concluida": "Lendo"}.get(texto, "Encoste")
        self.botao.define_estado(LENDO, curto)

    def _concluido(self, res):
        self.ocupado = False
        if not res.ok:
            self.botao.define_estado(ERRO, "Negado")
            audit.registra_com_captura("autorizacao_negada", motivo=res.mensagem,
                                       janela=self._janela_alvo)
            self._volta_ocioso(2500)
            return

        reg = self.vault.senha_de(res.indice)
        if reg is None:
            self.botao.define_estado(ERRO, "Sem senha")
            audit.registra("autorizacao_sem_cadastro", indice=res.indice,
                           janela=self._janela_alvo)
            self._volta_ocioso(2500)
            return

        if not self.vault.app_permitido(self._processo_alvo):
            self.botao.define_estado(ERRO, "Bloq. app")
            audit.registra_com_captura(
                "autorizacao_bloqueada_app", indice=res.indice, login=reg.login,
                processo=self._processo_alvo, janela=self._janela_alvo)
            self._volta_ocioso(3500)
            return

        try:
            inject.digita(reg.senha)
            if self.enter_no_fim:
                inject.tecla_enter()
        except inject.InjectorIndisponivel as exc:
            self.botao.define_estado(ERRO, "Bloq.")
            audit.registra("autorizacao_falha_digitacao", indice=res.indice,
                           login=reg.login, motivo=str(exc))
            self._volta_ocioso(4000)
            return

        self.botao.define_estado(OK, reg.nome.split()[0][:8])
        audit.registra_com_captura("autorizacao_concedida", indice=res.indice,
                                   login=reg.login, nome=reg.nome, janela=self._janela_alvo)
        self._volta_ocioso(2500)

    def _falhou(self, msg: str):
        self.ocupado = False
        self.botao.define_estado(ERRO, "Erro")
        audit.registra("autorizacao_erro", motivo=msg)
        self._volta_ocioso(3000)

    def _volta_ocioso(self, ms: int):
        QTimer.singleShot(ms, lambda: self.botao.define_estado(OCIOSO))
