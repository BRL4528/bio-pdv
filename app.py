#!/usr/bin/env python3
"""bio-pdv — ponto de entrada.

    python app.py                 # bandeja + botao flutuante + gestao
    python app.py --gestao        # so a tela de gestao (maquina do admin)
    python app.py --agente        # so o agente do caixa (sem tela de gestao)
    python app.py --porta COM3    # forca a porta do leitor
    python app.py --enter         # apos digitar a senha, manda Enter
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from biopdv import audit, reader as rd
from biopdv.agent import AgentePDV
from biopdv.manager import JanelaGestao, _WorkerSync
from biopdv.vault import Vault

INTERVALO_SYNC_MS = 120_000  # 2 minutos

try:
    from pynput import keyboard as _kb
except Exception:
    _kb = None

ATALHO = "<ctrl>+<alt>+b"


def icone(cor: str = "#2d6cdf") -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(cor))
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.end()
    return QIcon(pm)


def escolhe_porta(preferida: str | None) -> str | None:
    if preferida:
        return preferida
    portas = rd.detecta_portas()
    return portas[0] if portas else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--porta", help="porta do leitor (COM3, /dev/ttyUSB0)")
    ap.add_argument("--gestao", action="store_true", help="so a tela de gestao")
    ap.add_argument("--agente", action="store_true", help="so o agente do caixa")
    ap.add_argument("--enter", action="store_true",
                    help="manda Enter depois de digitar a senha")
    ap.add_argument("--timeout", type=int, default=20,
                    help="segundos aguardando o dedo")
    args = ap.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("bio-pdv")
    app.setQuitOnLastWindowClosed(False)

    porta = escolhe_porta(args.porta)
    if porta is None:
        QMessageBox.critical(
            None, "Leitor nao encontrado",
            "Nenhuma porta serial detectada.\n\n"
            "Windows: confira no Gerenciador de Dispositivos se aparece uma "
            "porta COM para o leitor.\n\n"
            "Linux: rode\n"
            "  sudo modprobe usbserial\n"
            "  echo \"079b 0047\" | sudo tee "
            "/sys/bus/usb-serial/drivers/generic/new_id\n"
            "  sudo chmod 666 /dev/ttyUSB0")
        return 1

    vault = Vault()
    audit.registra("inicio", porta=porta, modo=(
        "gestao" if args.gestao else "agente" if args.agente else "completo"))

    # Sincronizacao em segundo plano: roda em TODOS os modos (inclusive
    # --agente puro, sem tela de gestao aberta) para que senha trocada num
    # PDV chegue aos outros sem precisar abrir nada. Silenciosa: se o PDV
    # ainda nao foi configurado (sem token) ou esta sem rede, so tenta de
    # novo no proximo ciclo -- nao interrompe o caixa.
    _worker_sync_ref = [None]

    def _sincroniza_em_segundo_plano():
        anterior = _worker_sync_ref[0]
        if anterior is not None and anterior.isRunning():
            return
        worker = _WorkerSync(vault.ultima_sincronizacao, vault.ultima_sincronizacao_apps)
        worker.concluido.connect(
            lambda registros, apps: (vault.aplica_sincronizacao(registros),
                                     vault.aplica_apps_autorizados(apps)))
        worker.start()
        _worker_sync_ref[0] = worker

    timer_sync = QTimer()
    timer_sync.timeout.connect(_sincroniza_em_segundo_plano)
    timer_sync.start(INTERVALO_SYNC_MS)
    _sincroniza_em_segundo_plano()

    janela = None
    if not args.agente:
        janela = JanelaGestao(porta, vault)

    def abre_gestao():
        if janela is None:
            return
        janela.atualiza()
        janela.showNormal()
        janela.raise_()
        janela.activateWindow()

    agente = None
    if not args.gestao:
        agente = AgentePDV(porta, vault, enter_no_fim=args.enter,
                           timeout=args.timeout)

    # --- bandeja ------------------------------------------------------------
    tray = QSystemTrayIcon(icone(), app)
    tray.setToolTip("bio-pdv — liberacao por digital")
    menu = QMenu()

    if agente:
        a_liberar = QAction("Liberar senha agora", menu)
        a_liberar.triggered.connect(agente.aciona)
        menu.addAction(a_liberar)
        menu.addSeparator()

    if janela:
        a_gestao = QAction("Gerenciar supervisores", menu)
        a_gestao.triggered.connect(abre_gestao)
        menu.addAction(a_gestao)
        # clique simples ou duplo na bandeja abre a gestao -- sem isso o usuario
        # nao acha a interface (no Windows o icone fica no estouro da bandeja)
        tray.activated.connect(
            lambda motivo: abre_gestao() if motivo in (
                QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)

    if agente:
        a_bolha = QAction("Mostrar/ocultar botao flutuante", menu)
        a_bolha.triggered.connect(
            lambda: agente.botao.setVisible(not agente.botao.isVisible()))
        menu.addAction(a_bolha)

    menu.addSeparator()
    a_sair = QAction("Sair", menu)
    a_sair.triggered.connect(app.quit)
    menu.addAction(a_sair)
    tray.setContextMenu(menu)
    tray.show()

    # --- atalho global ------------------------------------------------------
    ouvinte = None
    if agente and _kb is not None:
        try:
            # dispara na thread do Qt, nunca na thread do listener (QTimer ja
            # importado no topo do modulo)
            ouvinte = _kb.GlobalHotKeys(
                {ATALHO: lambda: QTimer.singleShot(0, agente.aciona)})
            ouvinte.daemon = True
            ouvinte.start()
        except Exception as exc:
            print(f"Atalho global indisponivel: {exc}")

    # Abre a gestao quando faz sentido: modo --gestao, ou primeira execucao
    # (cofre vazio). Senao o app "some" na bandeja e o usuario nao acha nada.
    if janela and (args.gestao or not vault.listar()):
        abre_gestao()
        if not args.gestao and not vault.listar():
            QMessageBox.information(
                janela, "Primeira execucao",
                "Nenhum supervisor cadastrado ainda.\n\n"
                "Cadastre o primeiro nesta tela. Depois o programa fica no "
                "icone da bandeja (perto do relogio) — clique nele para "
                "voltar aqui.")
    elif agente:
        tray.showMessage(
            "bio-pdv ativo",
            f"Bolha flutuante na tela e atalho {ATALHO.replace('<','').replace('>','').upper()}. "
            "Clique neste icone para gerenciar supervisores.",
            icone(), 6000)

    try:
        return app.exec()
    finally:
        if ouvinte is not None:
            ouvinte.stop()


if __name__ == "__main__":
    sys.exit(main())
