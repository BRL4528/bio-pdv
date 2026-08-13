"""Tela de gestao: cadastrar supervisor, ver cadastrados, excluir, auditoria.

Quem pode cadastrar/trocar senha/excluir e definido pelo login no ERP
(samasc-api, POST /sessions): so quem tem tag=='admin' desbloqueia essas
acoes. A sessao vive so em memoria enquanto esta janela estiver aberta --
nao fica salva em disco. Quem nao e admin so consulta a aba Auditoria.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from . import audit, inject, reader as rd, sync, updater
from .sync import NaoAutorizado, SyncError
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


class _WorkerSync(QThread):
    """Pull incremental de supervisores + apps autorizados, fora da thread
    da interface."""

    concluido = Signal(list, list)  # list[RegistroSupervisor], list[RegistroAppAutorizado]
    falhou = Signal(str)

    def __init__(self, desde_supervisores: str | None, desde_apps: str | None):
        super().__init__()
        self.desde_supervisores = desde_supervisores
        self.desde_apps = desde_apps

    def run(self):
        try:
            supervisores = sync.sincronizar(self.desde_supervisores)
            apps = sync.sincronizar_apps(self.desde_apps)
            self.concluido.emit(supervisores, apps)
        except Exception as exc:
            self.falhou.emit(str(exc))


class DialogoLoginAdmin(QDialog):
    """Login no ERP (samasc-api). access['tag']=='admin' libera a gestao."""

    def __init__(self, base_url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Entrar")
        self.setMinimumWidth(360)
        self.access = None
        self.token = None

        self.url = QLineEdit(base_url)
        self.url.setPlaceholderText("https://api.samasc.cooasgo.com.br")
        self.nickname = QLineEdit()
        self.nickname.setPlaceholderText("usuario do ERP")
        self.senha = QLineEdit()
        self.senha.setEchoMode(QLineEdit.Password)

        form = QFormLayout()
        form.addRow("Servidor:", self.url)
        form.addRow("Usuario:", self.nickname)
        form.addRow("Senha:", self.senha)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#b00; font-size:11px;")

        btn_entrar = QPushButton("Entrar")
        btn_entrar.clicked.connect(self._tenta_login)
        cancelar = QDialogButtonBox(QDialogButtonBox.Cancel)
        cancelar.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.status)
        lay.addWidget(btn_entrar)
        lay.addWidget(cancelar)

    def _tenta_login(self):
        base_url = self.url.text().strip()
        if not base_url or not self.nickname.text().strip() or not self.senha.text():
            self.status.setText("Preencha servidor, usuario e senha.")
            return
        try:
            self.access, self.token = sync.login_erp(
                base_url, self.nickname.text().strip(), self.senha.text())
        except NaoAutorizado:
            self.status.setText("Usuario ou senha incorretos.")
            return
        except SyncError as exc:
            self.status.setText(str(exc))
            return
        self.base_url_usado = base_url
        self.accept()


class DialogoConfigurarSincronizacao(QDialog):
    """Provisiona o token de leitura DESTA maquina (uma vez por instalacao)."""

    def __init__(self, base_url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar sincronizacao deste PDV")
        self.setMinimumWidth(400)

        self.url = QLineEdit(base_url)
        self.nickname = QLineEdit()
        self.nickname.setPlaceholderText("usuario admin do ERP")
        self.senha = QLineEdit()
        self.senha.setEchoMode(QLineEdit.Password)
        self.nome_pdv = QLineEdit()
        self.nome_pdv.setPlaceholderText("Ex.: Caixa 3 - Loja Sede")

        form = QFormLayout()
        form.addRow("Servidor:", self.url)
        form.addRow("Usuario admin:", self.nickname)
        form.addRow("Senha:", self.senha)
        form.addRow("Nome deste PDV:", self.nome_pdv)

        aviso = QLabel(
            "Precisa de um login com permissao de administrador no ERP. "
            "Isso e feito uma vez por maquina -- o token gerado fica "
            "guardado localmente e cifrado."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color:#555; font-size:11px;")

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#b00; font-size:11px;")

        btn = QPushButton("Configurar")
        btn.clicked.connect(self._configura)
        cancelar = QDialogButtonBox(QDialogButtonBox.Cancel)
        cancelar.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(aviso)
        lay.addWidget(self.status)
        lay.addWidget(btn)
        lay.addWidget(cancelar)

    def _configura(self):
        base_url = self.url.text().strip()
        nome = self.nome_pdv.text().strip()
        if not base_url or not self.nickname.text().strip() or not self.senha.text() or not nome:
            self.status.setText("Preencha todos os campos.")
            return
        try:
            access, token = sync.login_erp(
                base_url, self.nickname.text().strip(), self.senha.text())
            if not sync.eh_admin(access):
                self.status.setText(
                    "Este usuario nao tem permissao de administrador no ERP.")
                return
            sync.provisionar_dispositivo(base_url, token, nome)
        except (NaoAutorizado, SyncError) as exc:
            self.status.setText(str(exc))
            return
        QMessageBox.information(
            self, "Configurado", f"Este PDV ('{nome}') esta pronto para sincronizar.")
        self.accept()


class DialogoAutorizarApp(QDialog):
    """Cadastra um executavel na lista sincronizada de apps autorizados."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Autorizar aplicativo")
        self.setMinimumWidth(400)

        self.executavel = QLineEdit()
        self.executavel.setPlaceholderText("Ex.: pdvfrente.exe")
        self.btn_detectar = QPushButton("Detectar processo em foco agora")
        self.btn_detectar.clicked.connect(self._inicia_deteccao)
        self.descricao = QLineEdit()
        self.descricao.setPlaceholderText("Ex.: PDV da loja Sede")

        form = QFormLayout()
        form.addRow("Executavel:", self.executavel)
        form.addRow("", self.btn_detectar)
        form.addRow("Descricao:", self.descricao)

        aviso = QLabel(
            "Ao clicar em 'Detectar', esta janela se minimiza e voce tem "
            "alguns segundos para clicar no programa do PDV antes da leitura "
            "acontecer -- sem isso, quem fica em foco e esta propria tela."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color:#555; font-size:11px;")

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self._confirma)
        botoes.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(aviso)
        lay.addWidget(botoes)

    def _inicia_deteccao(self):
        """A janela em foco NO CLIQUE e esta propria -- por isso a deteccao
        de verdade so roda depois de uma contagem, dando tempo da pessoa
        trocar para o PDV. Minimiza esta janela nesse intervalo pra nao
        competir pelo foco."""
        self._contagem = 5
        self.btn_detectar.setEnabled(False)
        self.showMinimized()
        self._passo_contagem()

    def _passo_contagem(self):
        if self._contagem <= 0:
            self.showNormal()
            self.raise_()
            self.activateWindow()
            processo = inject.processo_em_foco()
            self.btn_detectar.setEnabled(True)
            self.btn_detectar.setText("Detectar processo em foco agora")
            if not processo:
                QMessageBox.warning(
                    self, "Nao detectado",
                    "Nao consegui identificar o processo em foco (ou este "
                    "recurso so funciona no Windows). Digite o nome manualmente.")
                return
            self.executavel.setText(processo)
            return
        self.btn_detectar.setText(
            f"Clique no PDV agora -- detectando em {self._contagem}s...")
        self._contagem -= 1
        QTimer.singleShot(1000, self._passo_contagem)

    def _confirma(self):
        if not self.executavel.text().strip():
            QMessageBox.warning(self, "Faltam dados", "Informe o executavel.")
            return
        self.accept()


class DialogoCadastro(QDialog):
    """Coleta nome/login/senha (ou reaproveita um supervisor ja sincronizado)
    e conduz as capturas do dedo NESTE leitor."""

    def __init__(self, porta: str, vault: Vault, base_url: str, token_admin: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cadastrar supervisor")
        self.setMinimumWidth(460)
        self.porta = porta
        self.vault = vault
        self.base_url = base_url
        self.token_admin = token_admin
        self.worker: LeitorWorker | None = None
        self.resultado = None

        self.radio_novo = QRadioButton("Novo supervisor")
        self.radio_vincular = QRadioButton("Vincular supervisor ja cadastrado")
        self.radio_novo.setChecked(True)
        grupo = QButtonGroup(self)
        grupo.addButton(self.radio_novo)
        grupo.addButton(self.radio_vincular)
        grupo.buttonToggled.connect(lambda *_: self._alterna_modo())

        self.existentes = self.vault.nao_vinculados()
        self.combo_existentes = QComboBox()
        for login, nome in self.existentes:
            self.combo_existentes.addItem(f"{nome} ({login})", login)
        if not self.existentes:
            self.radio_vincular.setEnabled(False)
            self.radio_vincular.setToolTip(
                "Nenhum supervisor sincronizado ainda sem digital cadastrada neste leitor.")
        self.combo_existentes.setEnabled(False)

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

        self.form = QFormLayout()
        self.form.addRow("Nome:", self.nome)
        self.form.addRow("Login no PDV:", self.login)
        self.form.addRow("Senha do PDV:", linha_senha)
        self.linha_existentes = QLabel("Supervisor:")
        self.form.addRow(self.linha_existentes, self.combo_existentes)
        self.form.addRow("Capturas:", self.aquisicoes)
        self._alterna_modo()

        aviso = QLabel(
            "No modo Novo, esta senha precisa ser a MESMA cadastrada no PDV "
            "para este login -- pode ser aleatoria, ja que o agente digita "
            "sozinho. No modo Vincular, so a digital e nova; senha e nome ja "
            "vieram sincronizados de outro PDV."
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
        modos = QHBoxLayout()
        modos.addWidget(self.radio_novo)
        modos.addWidget(self.radio_vincular)
        lay.addLayout(modos)
        lay.addLayout(self.form)
        lay.addWidget(aviso)
        lay.addWidget(self.status)
        lay.addWidget(self.btn_iniciar)
        lay.addWidget(botoes)

    def _alterna_modo(self):
        novo = self.radio_novo.isChecked()
        self.nome.setEnabled(novo)
        self.login.setEnabled(novo)
        self.senha.setEnabled(novo)
        self.ver.setEnabled(novo)
        self.combo_existentes.setEnabled(not novo)

    def inicia(self):
        if self.radio_novo.isChecked():
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
            self._login_alvo = login
        else:
            if self.combo_existentes.currentIndex() < 0:
                QMessageBox.warning(self, "Selecione", "Escolha um supervisor da lista.")
                return
            self._login_alvo = self.combo_existentes.currentData()

        self.btn_iniciar.setEnabled(False)
        self.status.setText("Encoste o dedo no leitor...")
        self.worker = LeitorWorker(
            self.porta, "enroll", user_id=self._login_alvo,
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

        if self.radio_novo.isChecked():
            nome, login = self.nome.text().strip(), self.login.text().strip()
            senha = self.senha.text()
            self.vault.adicionar(res.indice, nome, login, senha)
            aviso_sync = ""
            try:
                sync.enviar_supervisor(self.base_url, self.token_admin, login, nome, senha)
            except SyncError as exc:
                aviso_sync = (f"\n\nATENCAO: ficou salvo so neste PDV -- falhou "
                              f"ao sincronizar com o servidor central: {exc}")
            audit.registra_com_captura("cadastro", indice=res.indice, login=login, nome=nome)
            self.resultado = res
            QMessageBox.information(
                self, "Cadastrado",
                f"{nome} cadastrado com sucesso.\n\n"
                f"Indice na base do leitor: {res.indice}\n\n"
                "Confirme que esta senha esta configurada no PDV para este login."
                + aviso_sync)
        else:
            login = self._login_alvo
            self.vault.vincular(res.indice, login)
            nome = self.combo_existentes.currentText()
            audit.registra_com_captura("cadastro", indice=res.indice, login=login,
                                       nome=nome, vinculo=True)
            self.resultado = res
            QMessageBox.information(
                self, "Vinculado",
                f"Digital vinculada a '{nome}' neste PDV.\n\n"
                f"Indice na base do leitor: {res.indice}")

        self.accept()

    def erro(self, msg):
        self.btn_iniciar.setEnabled(True)
        self.status.setText(f"Erro: {msg}")


class JanelaGestao(QMainWindow):
    def __init__(self, porta: str, vault: Vault):
        super().__init__()
        self.porta = porta
        self.vault = vault
        self.access = None
        self.token_admin = None
        dispositivo = sync.dispositivo_configurado()
        self.base_url = dispositivo["base_url"] if dispositivo else ""
        self._worker_sync: _WorkerSync | None = None

        self.setWindowTitle("bio-pdv — Gestao de supervisores")
        self.resize(780, 560)

        abas = QTabWidget()
        abas.addTab(self._aba_supervisores(), "Supervisores")
        abas.addTab(self._aba_apps_autorizados(), "Apps autorizados")
        abas.addTab(self._aba_auditoria(), "Auditoria")
        abas.addTab(self._aba_leitor(), "Leitor")
        abas.addTab(self._aba_atualizacao(), "Atualizar")
        self.setCentralWidget(abas)
        self.atualiza()
        self.atualiza_apps()

    # --- sessao / sincronizacao ----------------------------------------------

    def _aba_supervisores(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        cx_sessao = QGroupBox("Sessao e sincronizacao")
        cl_sessao = QVBoxLayout(cx_sessao)
        self.status_sessao = QLabel(
            "Nao logado — clique em Entrar para cadastrar/editar/excluir supervisores.")
        self.status_sessao.setWordWrap(True)
        self.status_sync = QLabel(
            f"Ultima sincronizacao: {self.vault.ultima_sincronizacao or 'nunca'}")
        linha_sessao = QHBoxLayout()
        btn_entrar = QPushButton("Entrar")
        btn_entrar.clicked.connect(self._entrar)
        btn_sync = QPushButton("Sincronizar agora")
        btn_sync.clicked.connect(self._sincronizar_agora)
        btn_configurar = QPushButton("Configurar este PDV")
        btn_configurar.clicked.connect(self._configurar_dispositivo)
        linha_sessao.addWidget(btn_entrar)
        linha_sessao.addWidget(btn_sync)
        linha_sessao.addWidget(btn_configurar)
        linha_sessao.addStretch()
        cl_sessao.addWidget(self.status_sessao)
        cl_sessao.addWidget(self.status_sync)
        cl_sessao.addLayout(linha_sessao)
        lay.addWidget(cx_sessao)

        self.tabela = QTableWidget(0, 4)
        self.tabela.setHorizontalHeaderLabels(
            ["Indice", "Nome", "Login no PDV", "Cadastrado em"])
        self.tabela.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabela.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tabela.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabela.setEditTriggers(QTableWidget.NoEditTriggers)

        self.btn_novo = QPushButton("Cadastrar supervisor")
        self.btn_novo.clicked.connect(self.cadastrar)
        self.btn_senha = QPushButton("Trocar senha")
        self.btn_senha.clicked.connect(self.trocar_senha)
        btn_testar = QPushButton("Testar digital")
        btn_testar.clicked.connect(self.testar)
        self.btn_excluir = QPushButton("Excluir")
        self.btn_excluir.clicked.connect(self.excluir)
        self.btn_excluir.setStyleSheet("color:#b00;")
        self._acoes_admin = (self.btn_novo, self.btn_senha, self.btn_excluir)
        for b in self._acoes_admin:
            b.setEnabled(False)

        barra = QHBoxLayout()
        for b in (self.btn_novo, self.btn_senha, btn_testar):
            barra.addWidget(b)
        barra.addStretch()
        barra.addWidget(self.btn_excluir)

        lay.addLayout(barra)
        lay.addWidget(self.tabela)
        return w

    def _entrar(self):
        dlg = DialogoLoginAdmin(self.base_url, self)
        if not dlg.exec():
            return
        self.access, self.token_admin = dlg.access, dlg.token
        self.base_url = dlg.base_url_usado
        nome = self.access.get("name", self.access.get("nickname", "?"))
        if sync.eh_admin(self.access):
            self.status_sessao.setText(f"Logado como {nome} (administrador).")
            for b in self._acoes_admin:
                b.setEnabled(True)
            self._adota_pendentes()
        else:
            self.status_sessao.setText(
                f"Logado como {nome} — sem permissao de administrador. "
                "Voce pode consultar a aba Auditoria.")
            for b in self._acoes_admin:
                b.setEnabled(False)

    def _adota_pendentes(self):
        """Envia ao servidor supervisores criados antes de existir sincronizacao."""
        pendentes = self.vault.pendentes_adocao()
        if not pendentes:
            return
        falharam = []
        for reg in pendentes:
            try:
                sync.enviar_supervisor(self.base_url, self.token_admin,
                                       reg.login, reg.nome, reg.senha)
                self.vault.marca_adotado(reg.login)
            except SyncError:
                falharam.append(reg.login)
        if falharam:
            QMessageBox.warning(
                self, "Adocao parcial",
                "Alguns supervisores cadastrados antes da sincronizacao nao "
                f"puderam ser enviados agora: {', '.join(falharam)}. "
                "Vao tentar de novo na proxima sincronizacao.")

    def _configurar_dispositivo(self):
        dlg = DialogoConfigurarSincronizacao(self.base_url, self)
        if dlg.exec():
            dispositivo = sync.dispositivo_configurado()
            if dispositivo:
                self.base_url = dispositivo["base_url"]

    def _sincronizar_agora(self):
        self._worker_sync = _WorkerSync(
            self.vault.ultima_sincronizacao, self.vault.ultima_sincronizacao_apps)
        self._worker_sync.concluido.connect(self._sync_concluida)
        self._worker_sync.falhou.connect(
            lambda m: self.status_sync.setText(f"Falha na sincronizacao: {m}"))
        self._worker_sync.start()

    def _sync_concluida(self, registros, apps):
        self.vault.aplica_sincronizacao(registros)
        self.vault.aplica_apps_autorizados(apps)
        self.status_sync.setText(
            f"Ultima sincronizacao: {self.vault.ultima_sincronizacao} "
            f"({len(registros)} supervisores, {len(apps)} apps atualizados)")
        self.atualiza()
        self.atualiza_apps()

    # --- aba supervisores: acoes ---------------------------------------------

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

    def _exige_admin(self) -> bool:
        if not (self.access and sync.eh_admin(self.access)):
            QMessageBox.warning(
                self, "Sem permissao",
                "Entre com uma conta de administrador do ERP para fazer isso.")
            return False
        return True

    def cadastrar(self):
        if not self._exige_admin():
            return
        dlg = DialogoCadastro(self.porta, self.vault, self.base_url, self.token_admin, self)
        if dlg.exec():
            self.atualiza()

    def trocar_senha(self):
        if not self._exige_admin():
            return
        idx = self._selecionado()
        if idx is None:
            return
        reg = next((r for r in self.vault.listar() if r.indice == idx), None)
        if reg is None:
            return
        nova, ok = self._pede_senha()
        if not ok:
            return
        self.vault.trocar_senha(idx, nova)
        aviso_sync = ""
        try:
            sync.enviar_supervisor(self.base_url, self.token_admin, reg.login, reg.nome, nova)
        except SyncError as exc:
            aviso_sync = f"\n\nATENCAO: falhou ao sincronizar com o servidor central: {exc}"
        audit.registra_com_captura("troca_senha", indice=idx, login=reg.login)
        QMessageBox.information(
            self, "Senha trocada",
            "Senha atualizada no cofre e enviada ao servidor central.\n\n"
            "Atualize a MESMA senha no PDV." + aviso_sync)

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
        if not self._exige_admin():
            return
        idx = self._selecionado()
        if idx is None:
            return
        reg = next((r for r in self.vault.listar() if r.indice == idx), None)
        nome = reg.nome if reg else str(idx)
        login = reg.login if reg else None
        r = QMessageBox.question(
            self, "Excluir supervisor",
            f"Excluir '{nome}' (indice {idx})?\n\n"
            "A digital sai da base deste leitor e o supervisor e desativado "
            "em TODOS os PDVs sincronizados.\nNao ha desfazer.",
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
            aviso_sync = ""
            if login:
                try:
                    sync.remover_supervisor(self.base_url, self.token_admin, login)
                except SyncError as exc:
                    aviso_sync = (f"\n\nATENCAO: removido so deste PDV -- falhou ao "
                                  f"desativar no servidor central: {exc}")
            audit.registra_com_captura("exclusao", indice=idx, nome=nome)
            self.atualiza()
            QMessageBox.information(self, "Excluido", f"'{nome}' removido." + aviso_sync)

        worker.concluido.connect(pronto)
        worker.falhou.connect(
            lambda m: QMessageBox.warning(self, "Erro", m))
        worker.start()
        self._worker_excluir = worker  # segura a referencia

    # --- aba apps autorizados ------------------------------------------------

    def _aba_apps_autorizados(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        aviso = QLabel(
            "Antes de digitar a senha, o agente confere se o programa em foco "
            "esta nesta lista (pelo nome do executavel, nao pelo titulo da "
            "janela -- titulo qualquer programa pode reescrever).\n\n"
            "Lista vazia = checagem desativada (a senha pode ser digitada em "
            "qualquer janela, como antes desta funcao existir)."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color:#555; font-size:11px;")
        lay.addWidget(aviso)

        self.tabela_apps = QTableWidget(0, 3)
        self.tabela_apps.setHorizontalHeaderLabels(
            ["Executavel", "Descricao", "Autorizado em"])
        self.tabela_apps.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabela_apps.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabela_apps.setEditTriggers(QTableWidget.NoEditTriggers)

        self.btn_autorizar_app = QPushButton("Autorizar aplicativo")
        self.btn_autorizar_app.clicked.connect(self._autorizar_app)
        self.btn_remover_app = QPushButton("Remover")
        self.btn_remover_app.setStyleSheet("color:#b00;")
        self.btn_remover_app.clicked.connect(self._remover_app)
        self._acoes_admin = self._acoes_admin + (self.btn_autorizar_app, self.btn_remover_app)
        self.btn_autorizar_app.setEnabled(False)
        self.btn_remover_app.setEnabled(False)

        barra = QHBoxLayout()
        barra.addWidget(self.btn_autorizar_app)
        barra.addStretch()
        barra.addWidget(self.btn_remover_app)

        lay.addLayout(barra)
        lay.addWidget(self.tabela_apps)
        return w

    def atualiza_apps(self):
        apps = self.vault.apps_autorizados()
        self.tabela_apps.setRowCount(len(apps))
        for i, (executavel, descricao) in enumerate(apps):
            atualizado = self.vault._apps.get(executavel, {}).get("atualizado_em", "")
            for col, val in enumerate([executavel, descricao, atualizado]):
                self.tabela_apps.setItem(i, col, QTableWidgetItem(val))

    def _autorizar_app(self):
        if not self._exige_admin():
            return
        dlg = DialogoAutorizarApp(self)
        if not dlg.exec():
            return
        executavel, descricao = dlg.executavel.text().strip(), dlg.descricao.text().strip()
        try:
            registro = sync.enviar_app_autorizado(
                self.base_url, self.token_admin, executavel, descricao)
        except SyncError as exc:
            QMessageBox.warning(
                self, "Falhou ao sincronizar",
                f"Nao consegui autorizar '{executavel}' no servidor central: {exc}\n\n"
                "Nada foi salvo -- tente de novo quando a rede voltar.")
            return
        # Grava local na hora, com o atualizado_em que o servidor devolveu --
        # nao depende de uma sincronizacao assincrona separada pra aparecer
        # na tabela (essa dependencia era o bug: sucesso aparecia mas a
        # tabela so atualizava se o pull seguinte tambem desse certo).
        self.vault.aplica_apps_autorizados([registro])
        self.atualiza_apps()
        audit.registra("app_autorizado", executavel=executavel)
        self._sincronizar_agora()
        QMessageBox.information(
            self, "Autorizado",
            f"'{executavel}' autorizado em todos os PDVs sincronizados.")

    def _remover_app(self):
        if not self._exige_admin():
            return
        linha = self.tabela_apps.currentRow()
        if linha < 0:
            QMessageBox.information(self, "Selecione", "Escolha um app na lista.")
            return
        executavel = self.tabela_apps.item(linha, 0).text()
        r = QMessageBox.question(
            self, "Remover app autorizado",
            f"Remover '{executavel}' da lista em TODOS os PDVs sincronizados?\n\n"
            "Se essa remocao deixar a lista vazia, a checagem volta a ficar "
            "desativada (senha digitada em qualquer janela).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        try:
            sync.remover_app_autorizado(self.base_url, self.token_admin, executavel)
        except SyncError as exc:
            QMessageBox.warning(self, "Falhou ao sincronizar", str(exc))
            return
        # Mesma logica do autorizar: reflete local na hora, sem esperar o
        # proximo pull assincrono.
        descricao_atual = dict(self.vault.apps_autorizados()).get(executavel, "")
        self.vault.aplica_apps_autorizados([sync.RegistroAppAutorizado(
            executavel=executavel, descricao=descricao_atual, ativo=False,
            atualizado_em=time.strftime("%Y-%m-%dT%H:%M:%S"))])
        self.atualiza_apps()
        audit.registra("app_removido", executavel=executavel)
        self._sincronizar_agora()

    # --- aba auditoria ------------------------------------------------------

    def _aba_auditoria(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        barra = QHBoxLayout()
        btn = QPushButton("Atualizar")
        btn.clicked.connect(self.carrega_log)
        btn_captura = QPushButton("Ver captura")
        btn_captura.clicked.connect(self._ver_captura)
        barra.addWidget(btn)
        barra.addWidget(btn_captura)
        barra.addStretch()
        lay.addLayout(barra)

        self.tabela_log = QTableWidget(0, 3)
        self.tabela_log.setHorizontalHeaderLabels(["Quando", "Evento", "Detalhes"])
        self.tabela_log.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tabela_log.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabela_log.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabela_log.doubleClicked.connect(self._ver_captura)
        lay.addWidget(self.tabela_log)

        self.carrega_log()
        return w

    def carrega_log(self):
        eventos = audit.ultimos(300)
        self.tabela_log.setRowCount(len(eventos))
        for i, e in enumerate(eventos):
            extra = " ".join(f"{k}={v}" for k, v in e.items()
                             if k not in ("quando", "evento", "maquina", "captura"))
            item_quando = QTableWidgetItem(e["quando"])
            item_quando.setData(Qt.UserRole, e)
            self.tabela_log.setItem(i, 0, item_quando)
            self.tabela_log.setItem(i, 1, QTableWidgetItem(e["evento"]))
            self.tabela_log.setItem(i, 2, QTableWidgetItem(extra))

    def _ver_captura(self):
        linha = self.tabela_log.currentRow()
        if linha < 0:
            QMessageBox.information(self, "Selecione", "Escolha uma linha na auditoria.")
            return
        evento = self.tabela_log.item(linha, 0).data(Qt.UserRole) or {}
        caminho = evento.get("captura")
        if not caminho:
            QMessageBox.information(self, "Sem captura", "Este evento nao tem captura de tela.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(caminho))

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
