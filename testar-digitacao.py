#!/usr/bin/env python3
"""Diagnostico da digitacao, isolado do leitor biometrico.

Rode no Windows onde o agente falhou:

    python testar-digitacao.py

Ele confere o tamanho da struct INPUT, mostra a janela em foco e, depois de
5 segundos, digita um texto de teste onde voce deixar o cursor. Abra o Bloco de
Notas e clique nele durante a contagem.
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__file__))

from biopdv import inject  # noqa: E402

TEXTO = "bio-pdv-OK-123"


def main() -> int:
    print("=" * 56)
    print(" bio-pdv — diagnostico da digitacao")
    print("=" * 56)
    print(f"Plataforma           : {sys.platform}")

    if not inject.WINDOWS:
        print("Fora do Windows: este teste vale pouco (usa pynput).")
    else:
        import ctypes
        tam = ctypes.sizeof(inject._INPUT)
        esperado = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        arq = "x64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "x86"
        ok = "OK" if tam == esperado else "ERRADO"
        print(f"Arquitetura          : {arq}")
        print(f"sizeof(INPUT)        : {tam} (esperado {esperado}) -> {ok}")
        print(f"sizeof(KEYBDINPUT)   : {ctypes.sizeof(inject._KEYBDINPUT)}")
        print(f"sizeof(MOUSEINPUT)   : {ctypes.sizeof(inject._MOUSEINPUT)}")
        if tam != esperado:
            print("\n>>> O SendInput vai recusar com cbSize errado. Pare aqui.")
            return 1
        try:
            elevado = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            elevado = False
        print(f"Rodando como admin   : {'sim' if elevado else 'nao'}")

    print("\nDeixe o cursor num campo de texto (Bloco de Notas serve).")
    for i in range(5, 0, -1):
        print(f"  digitando em {i}...", end="\r", flush=True)
        time.sleep(1)
    print(" " * 30, end="\r")

    janela = inject.janela_em_foco()
    print(f"Janela em foco       : {janela or '(desconhecida)'}")

    try:
        inject.digita(TEXTO)
    except inject.InjectorIndisponivel as exc:
        print(f"\nFALHOU: {exc}")
        print("\nSe disser UIPI: feche e abra o bio-pdv como administrador")
        print("(botao direito no atalho -> Executar como administrador).")
        return 1

    print(f"\nEnviado: {TEXTO!r}")
    print("Apareceu no campo? Entao a digitacao esta funcionando.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
