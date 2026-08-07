"""Tela de gestao: cadastrar supervisor, ver cadastrados, excluir, auditoria."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from . import audit, reader as rd, updater
from .vault import Vault, gera_senha
from .worker import LeitorWorker


class _WorkerUpdate(QThread):
    """Rede fora da thread da interface."""

    achou = Signal(object)      # updater.Atualizacao | None
    baixou = Signal(str)        # caminho do zip
    progresso = Signal(int)
    falhou = Signal(str)

    def __init__(self, acao: str, info=None):
        super().__init__()
        self.acao = acao
        self.info = info

    def run(self):
        try:
            if self.acao == "checa":
                self.achou.emit(updater.checa())
            else:
                self.baixou.emit(
                    updater.baixa(self.info, progresso=self.progresso.emit))
        except Exception as exc:
            self.falhou.emit(str(exc))


class DialogoCadastro(QDialog):
    """Coleta nome/login/senha e conduz as 3 capturas do dedo."""

    def __init__(self, porta: str, vault: Vault, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cadastrar supervisor")
        self.setMinimumWidth(460)
        self.porta = porta
        self.vault = vault
        self.worker: LeitorWorker | None = None
        self.resultado = None

        self.nome = QLineEdit()
        self.nome.setPlaceholderText("Ex.: Maria Souza")
        self.login = QLineEdit()
        self.login.setPlaceholderText("login dela no PDV")

        self.senha = QLineEdit(gera_senha())
        self.senha.setEchoMode(QLineEdit.Password)
        btn_gerar = QPushButton("Sortear outra")
        btn_gerar.clicked.connect(lambda: self.senha.setText(gera_senha()))
        self.ver = QCheckBox("Mostrar")
        self.ver.toggled.connect(
            lambda on: self.senha.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        )
        linha_senha = QHBoxLayout()
        linha_senha.addWidget(self.senha, 1)
        linha_senha.addWidget(self.ver)
        linha_senha.addWidget(btn_gerar)

        self.aquisicoes = QSpinBox()
        self.aquisicoes.setRange(1, 3)
        self.aquisicoes.setSingleStep(2)
        self.aquisicoes.setValue(3)
        self.aquisicoes.setToolTip("3 capturas = mais preciso. 1 = mais rapido.")

        form = QFormLayout()
        form.addRow("Nome:", self.nome)
        form.addRow("Login no PDV:", self.login)
        form.addRow("Senha do PDV:", linha_senha)
        form.addRow("Capturas:", self.aquisicoes)

        aviso = QLabel(
            "Esta senha precisa ser a MESMA cadastrada no PDV para este login.\n"
            "Como o agente digita sozinho, ninguem precisa decorar — pode ser aleatoria."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color:#555; font-size:11px;")

        self.status = QLabel("Preencha os dados e clique em Iniciar captura.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            "padding:10px; background:#f0f0f0; border-radius:6px; font-size:13px;")

        self.btn_iniciar = QPushButton("Iniciar captura")
        self.btn_iniciar.clicked.connect(self.inicia)
        botoes = QDialogButtonBox(QDialogButtonBox.Cancel)
        botoes.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(aviso)
        lay.addWidget(self.status)
        lay.addWidget(self.btn_iniciar)
        lay.addWidget(botoes)

    def inicia(self):
        nome = self.nome.text().strip()
        login = self.login.text().strip()
        if not nome or not login:
            QMessageBox.warning(self, "Faltam dados", "Preencha nome e login.")
            return
        if self.vault.existe_login(login):
            QMessageBox.warning(self, "Login repetido",
                                f"Ja existe cadastro para o login '{login}'.")
            return
        if not self.senha.text():
            QMessageBox.warning(self, "Faltam dados", "Defina a senha do PDV.")
            return

        self.btn_iniciar.setEnabled(False)
        self.status.setText("Encoste o dedo no leitor...")
        self.worker = LeitorWorker(
            self.porta, "enroll", user_id=login,
            aquisicoes=self.aquisicoes.value(), timeout=30,
        )
        self.worker.progresso.connect(self.status.setText)
        self.worker.captura.connect(
            lambda d, td, c, tc: self.status.setText(
                f"Dedo {d}/{td} — captura {c}/{tc}. Encoste o dedo.")
        )
        self.worker.concluido.connect(self.terminou)
        self.worker.falhou.connect(self.erro)
        self.worker.start()

    def terminou(self, res):
        self.btn_iniciar.setEnabled(True)
        if not res.ok:
            self.status.setText(f"Falhou: {res.mensagem}")
            return
        nome, login = self.nome.text().strip(), self.login.text().strip()
        self.vault.adicionar(res.indice, nome, login, self.senha.text())
        audit.registra("cadastro", indice=res.indice, login=login, nome=nome)
        self.resultado = res
        QMessageBox.information(
            self, "Cadastrado",
            f"{nome} cadastrado com sucesso.\n\n"
            f"Indice na base do leitor: {res.indice}\n\n"
            "Confirme que esta senha esta configurada no PDV para este login.")
        self.accept()

    def erro(self, msg):
        self.btn_iniciar.setEnabled(True)
        self.status.setText(f"Erro: {msg}")


class JanelaGestao(QMainWindow):
    def __init__(self, porta: str, vault: Vault):
        super().__init__()
        self.porta = porta
        self.vault = vault
        self.setWindowTitle("bio-pdv — Gestao de supervisores")
        self.resize(760, 520)

        abas = QTabWidget()
        abas.addTab(self._aba_supervisores(), "Supervisores")
        abas.addTab(self._aba_auditoria(), "Auditoria")
        abas.addTab(self._aba_leitor(), "Leitor")
        abas.addTab(self._aba_atualizacao(), "Atualizar")
        self.setCentralWidget(abas)
        self.atualiza()

    # --- aba supervisores ---------------------------------------------------

    def _aba_supervisores(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self.tabela = QTableWidget(0, 4)
        self.tabela.setHorizontalHeaderLabels(
            ["Indice", "Nome", "Login no PDV", "Cadastrado em"])
        self.tabela.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabela.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tabela.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabela.setEditTriggers(QTableWidget.NoEditTriggers)

        btn_novo = QPushButton("Cadastrar supervisor")
        btn_novo.clicked.connect(self.cadastrar)
        btn_senha = QPushButton("Trocar senha")
        btn_senha.clicked.connect(self.trocar_senha)
        btn_testar = QPushButton("Testar digital")
        btn_testar.clicked.connect(self.testar)
        btn_excluir = QPushButton("Excluir")
        btn_excluir.clicked.connect(self.excluir)
        btn_excluir.setStyleSheet("color:#b00;")

        barra = QHBoxLayout()
        for b in (btn_novo, btn_senha, btn_testar):
            barra.addWidget(b)
        barra.addStretch()
        barra.addWidget(btn_excluir)

        lay.addLayout(barra)
        lay.addWidget(self.tabela)
        return w

    def atualiza(self):
        regs = self.vault.listar()
        self.tabela.setRowCount(len(regs))
        for i, r in enumerate(regs):
            for col, val in enumerate([str(r.indice), r.nome, r.login, r.criado_em]):
                self.tabela.setItem(i, col, QTableWidgetItem(val))

    def _selecionado(self) -> int | None:
        linha = self.tabela.currentRow()
        if linha < 0:
            QMessageBox.information(self, "Selecione", "Escolha um supervisor na lista.")
            return None
        return int(self.tabela.item(linha, 0).text())

    def cadastrar(self):
        dlg = DialogoCadastro(self.porta, self.vault, self)
        if dlg.exec():
            self.atualiza()

    def trocar_senha(self):
        idx = self._selecionado()
        if idx is None:
            return
        nova, ok = self._pede_senha()
        if not ok:
            return
        self.vault.trocar_senha(idx, nova)
        audit.registra("troca_senha", indice=idx)
        QMessageBox.information(
            self, "Senha trocada",
            "Senha atualizada no cofre.\n\nAtualize a MESMA senha no PDV.")

    def _pede_senha(self) -> tuple[str, bool]:
        dlg = QDialog(self)
        dlg.setWindowTitle("Nova senha")
        campo = QLineEdit(gera_senha())
        ver = QCheckBox("Mostrar")
        campo.setEchoMode(QLineEdit.Password)
        ver.toggled.connect(
            lambda on: campo.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        btn = QPushButton("Sortear outra")
        btn.clicked.connect(lambda: campo.setText(gera_senha()))
        cx = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        cx.accepted.connect(dlg.accept)
        cx.rejected.connect(dlg.reject)
        lay = QVBoxLayout(dlg)
        linha = QHBoxLayout()
        linha.addWidget(campo, 1)
        linha.addWidget(ver)
        linha.addWidget(btn)
        lay.addLayout(linha)
        lay.addWidget(cx)
        return campo.text(), bool(dlg.exec())

    def testar(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Testar digital")
        dlg.setMinimumWidth(380)
        rotulo = QLabel("Encoste o dedo no leitor...")
        rotulo.setWordWrap(True)
        rotulo.setStyleSheet("padding:16px; font-size:14px;")
        cx = QDialogButtonBox(QDialogButtonBox.Close)
        cx.rejected.connect(dlg.reject)
        lay = QVBoxLayout(dlg)
        lay.addWidget(rotulo)
        lay.addWidget(cx)

        worker = LeitorWorker(self.porta, "identify", timeout=20)
        worker.progresso.connect(rotulo.setText)

        def pronto(res):
            if not res.ok:
                rotulo.setText(f"Nao reconhecido: {res.mensagem}")
                return
            reg = self.vault.senha_de(res.indice)
            quem = reg.nome if reg else "(indice sem cadastro neste PC)"
            rotulo.setText(f"Reconhecido!\n\nIndice {res.indice}\n{quem}")
            audit.registra("teste_digital", indice=res.indice,
                           login=reg.login if reg else None)

        worker.concluido.connect(pronto)
        worker.falhou.connect(lambda m: rotulo.setText(f"Erro: {m}"))
        worker.start()
        dlg.exec()

    def excluir(self):
        idx = self._selecionado()
        if idx is None:
            return
        reg = next((r for r in self.vault.listar() if r.indice == idx), None)
        nome = reg.nome if reg else str(idx)
        r = QMessageBox.question(
            self, "Excluir supervisor",
            f"Excluir '{nome}' (indice {idx})?\n\n"
            "A digital sai da base do leitor e a senha sai do cofre.\n"
            "Nao ha desfazer.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return

        worker = LeitorWorker(self.porta, "remove", indice=idx)

        def pronto(res):
            if not res.ok:
                QMessageBox.warning(
                    self, "Falhou no leitor",
                    f"Nao removi da base do leitor: {res.mensagem}\n\n"
                    "O cofre nao foi alterado.")
                return
            self.vault.remover(idx)
            audit.registra("exclusao", indice=idx, nome=nome)
            self.atualiza()
            QMessageBox.information(self, "Excluido", f"'{nome}' removido.")

        worker.concluido.connect(pronto)
        worker.falhou.connect(
            lambda m: QMessageBox.warning(self, "Erro", m))
        worker.start()
        self._worker_excluir = worker  # segura a referencia

    # --- aba auditoria ------------------------------------------------------

    def _aba_auditoria(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family:monospace; font-size:12px;")
        btn = QPushButton("Atualizar")
        btn.clicked.connect(self.carrega_log)
        lay.addWidget(btn)
        lay.addWidget(self.log)
        self.carrega_log()
        return w

    def carrega_log(self):
        linhas = []
        for e in audit.ultimos(300):
            extra = " ".join(f"{k}={v}" for k, v in e.items()
                             if k not in ("quando", "evento", "maquina"))
            linhas.append(f"{e['quando']}  {e['evento']:<16} {extra}")
        self.log.setPlainText("\n".join(linhas) or "(sem eventos)")

    # --- aba leitor ---------------------------------------------------------

    def _aba_leitor(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        cx = QGroupBox("Porta")
        cl = QHBoxLayout(cx)
        self.combo = QComboBox()
        self.combo.addItems(rd.detecta_portas() or ["(nenhuma)"])
        if self.porta:
            self.combo.setCurrentText(self.porta)
        self.combo.currentTextChanged.connect(self._muda_porta)
        cl.addWidget(self.combo, 1)
        btn = QPushButton("Reprocurar")
        btn.clicked.connect(self._reprocura)
        cl.addWidget(btn)
        lay.addWidget(cx)

        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setStyleSheet("font-family:monospace; font-size:12px;")
        btn_st = QPushButton("Consultar base do leitor")
        btn_st.clicked.connect(self.consulta_base)
        lay.addWidget(btn_st)
        lay.addWidget(self.info)

        nota = QLabel(
            "A base embarcada veio do relogio ponto com digitais de terceiros. "
            "Este programa so adiciona e remove os registros que ele mesmo criou."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color:#a60; font-size:11px;")
        lay.addWidget(nota)
        return w

    def _muda_porta(self, texto):
        if texto and not texto.startswith("("):
            self.porta = texto

    def _reprocura(self):
        self.combo.clear()
        self.combo.addItems(rd.detecta_portas() or ["(nenhuma)"])

    # --- aba atualizacao ----------------------------------------------------

    def _aba_atualizacao(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self._info_update = None
        self._worker_upd = None

        cab = QLabel(
            f"<b>Versao instalada:</b> {updater.versao_atual()}<br>"
            f"<b>Origem:</b> github.com/{updater.REPO}"
        )
        cab.setTextFormat(Qt.RichText)
        lay.addWidget(cab)

        self.btn_checar = QPushButton("Procurar atualizacoes")
        self.btn_checar.clicked.connect(self._checar_update)
        lay.addWidget(self.btn_checar)

        self.status_upd = QLabel("Clique para verificar se ha versao nova.")
        self.status_upd.setWordWrap(True)
        self.status_upd.setStyleSheet(
            "padding:10px; background:#f0f0f0; border-radius:6px;")
        lay.addWidget(self.status_upd)

        self.notas_upd = QPlainTextEdit()
        self.notas_upd.setReadOnly(True)
        self.notas_upd.setVisible(False)
        self.notas_upd.setMaximumHeight(160)
        lay.addWidget(self.notas_upd)

        self.barra_upd = QProgressBar()
        self.barra_upd.setVisible(False)
        lay.addWidget(self.barra_upd)

        self.btn_instalar = QPushButton("Baixar e instalar")
        self.btn_instalar.setVisible(False)
        self.btn_instalar.clicked.connect(self._instalar_update)
        lay.addWidget(self.btn_instalar)

        nota = QLabel(
            "O pacote e baixado por HTTPS e o SHA-256 e conferido antes de "
            "instalar. Versao anterior a instalada e recusada.\n\n"
            "Quem controla a conta do GitHub controla os caixas — mantenha 2FA "
            "ligado nessa conta."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color:#a60; font-size:11px;")
        lay.addWidget(nota)
        lay.addStretch()
        return w

    def _checar_update(self):
        self.btn_checar.setEnabled(False)
        self.btn_instalar.setVisible(False)
        self.notas_upd.setVisible(False)
        self.status_upd.setText("Consultando o GitHub...")

        self._worker_upd = _WorkerUpdate("checa")
        self._worker_upd.achou.connect(self._resultado_check)
        self._worker_upd.falhou.connect(self._erro_update)
        self._worker_upd.start()

    def _resultado_check(self, info):
        self.btn_checar.setEnabled(True)
        if info is None:
            self.status_upd.setText(
                f"Voce ja esta na versao mais recente ({updater.versao_atual()}).")
            return
        self._info_update = info
        mb = info.tamanho / (1024 * 1024) if info.tamanho else 0
        self.status_upd.setText(
            f"Versao {info.versao} disponivel  ({mb:.1f} MB).")
        self.notas_upd.setPlainText(info.notas)
        self.notas_upd.setVisible(True)
        self.btn_instalar.setVisible(True)

    def _instalar_update(self):
        info = self._info_update
        if not info:
            return
        r = QMessageBox.question(
            self, "Instalar atualizacao",
            f"Instalar a versao {info.versao}?\n\n"
            "O bio-pdv vai fechar e reabrir sozinho.\n"
            "Nao faca isso com o caixa em atendimento.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return

        self.btn_instalar.setEnabled(False)
        self.btn_checar.setEnabled(False)
        self.barra_upd.setValue(0)
        self.barra_upd.setVisible(True)
        self.status_upd.setText("Baixando...")

        self._worker_upd = _WorkerUpdate("baixa", info)
        self._worker_upd.progresso.connect(self.barra_upd.setValue)
        self._worker_upd.baixou.connect(self._aplicar_update)
        self._worker_upd.falhou.connect(self._erro_update)
        self._worker_upd.start()

    def _aplicar_update(self, caminho_zip: str):
        self.status_upd.setText("Integridade conferida. Instalando...")
        try:
            updater.aplica(caminho_zip)
        except Exception as exc:
            self._erro_update(str(exc))
            return
        audit.registra("atualizacao", versao=self._info_update.versao)
        QMessageBox.information(
            self, "Instalando",
            "O bio-pdv vai fechar agora e reabrir ja atualizado.\n\n"
            "Se nao reabrir em 1 minuto, abra pelo Menu Iniciar.")
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    def _erro_update(self, msg: str):
        self.btn_checar.setEnabled(True)
        self.btn_instalar.setEnabled(True)
        self.barra_upd.setVisible(False)
        self.status_upd.setText(f"Falhou: {msg}")
        audit.registra("atualizacao_falhou", motivo=msg)

    def consulta_base(self):
        worker = LeitorWorker(self.porta, "status")

        def pronto(cfg):
            self.info.setPlainText(
                f"Porta            : {self.porta}\n"
                f"Dedos/registro   : {cfg.dedos}\n"
                f"Capacidade       : {cfg.capacidade}\n"
                f"Cadastradas      : {cfg.cadastradas}\n"
                f"Livres           : {cfg.livres}\n"
                f"Campos adicionais: {cfg.campos}\n\n"
                f"Supervisores neste PC: {len(self.vault.listar())}\n"
                f"Senhas cifradas com DPAPI: {'sim' if self.vault.protegido else 'NAO'}"
            )

        worker.concluido.connect(pronto)
        worker.falhou.connect(lambda m: self.info.setPlainText(f"Erro: {m}"))
        worker.start()
        self._worker_status = worker
