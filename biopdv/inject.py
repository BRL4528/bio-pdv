"""Digita a senha na janela que esta em foco.

Por que digitar em vez de colar:
  - Ctrl+V deixa a senha no historico da area de transferencia (Win+V).
  - Varios PDV bloqueiam colar em campo de senha.

No Windows usa SendInput com KEYEVENTF_UNICODE: injeta o caractere pelo codigo
UTF-16, entao independe do layout de teclado (ABNT2, US, o que for).
"""

from __future__ import annotations

import sys
import time

WINDOWS = sys.platform.startswith("win")


class InjectorIndisponivel(Exception):
    pass


# --- Windows: SendInput -----------------------------------------------------

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    INPUT_KEYBOARD = 1
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002

    ERROR_ACCESS_DENIED = 5
    ERROR_INVALID_PARAMETER = 87

    # ULONG_PTR acompanha a largura do ponteiro: 8 bytes em x64, 4 em x86.
    ULONG_PTR = (ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8
                 else ctypes.c_ulong)

    # ATENCAO: os tres membros da uniao precisam existir para o ctypes calcular
    # sizeof(INPUT) certo. O maior e o MOUSEINPUT (32 bytes em x64), nao o
    # KEYBDINPUT (24). Dimensionar a uniao pelo KEYBDINPUT da sizeof=32 em vez
    # de 40, e o SendInput REJEITA cbSize errado -- retorna 0 com
    # ERROR_INVALID_PARAMETER, que parece "sem permissao" mas nao e.
    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD)]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT),
                    ("hi", _HARDWAREINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT),
                                  ctypes.c_int)
    _user32.SendInput.restype = wintypes.UINT

    def _evento(codigo: int, key_up: bool) -> _INPUT:
        flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0)
        ki = _KEYBDINPUT(wVk=0, wScan=codigo, dwFlags=flags, time=0,
                         dwExtraInfo=0)
        return _INPUT(type=INPUT_KEYBOARD, u=_INPUTunion(ki=ki))

    def _envia(eventos: list):
        n = len(eventos)
        arr = (_INPUT * n)(*eventos)
        ctypes.set_last_error(0)
        enviados = _user32.SendInput(n, arr, ctypes.sizeof(_INPUT))
        if enviados != n:
            err = ctypes.get_last_error()
            if err == ERROR_ACCESS_DENIED:
                detalhe = ("bloqueado por UIPI. A janela em foco roda com "
                           "privilegio maior que o deste agente -- rode o "
                           "bio-pdv como administrador.")
            elif err == ERROR_INVALID_PARAMETER:
                detalhe = (f"cbSize invalido ({ctypes.sizeof(_INPUT)} bytes). "
                           "Bug de layout da struct INPUT.")
            else:
                detalhe = f"erro {err} do Windows."
            raise InjectorIndisponivel(f"SendInput recusado: {detalhe}")

    def _digita_sendinput(texto: str, atraso: float):
        for ch in texto:
            for code in [ord(c) for c in ch]:  # cobre pares substitutos UTF-16
                _envia([_evento(code, False), _evento(code, True)])
            if atraso:
                time.sleep(atraso)

    def digita(texto: str, atraso: float = 0.004):
        """SendInput e o caminho bom. Se ele recusar, tenta o pynput antes de
        desistir -- os dois usam APIs diferentes e falham por motivos diferentes."""
        try:
            _digita_sendinput(texto, atraso)
            return
        except InjectorIndisponivel as exc:
            try:
                from pynput.keyboard import Controller
                teclado = Controller()
            except Exception:
                raise exc
            try:
                for ch in texto:
                    teclado.type(ch)
                    if atraso:
                        time.sleep(atraso)
            except Exception:
                raise exc  # o erro do SendInput diz mais que o do pynput

    def tecla_enter():
        VK_RETURN = 0x0D
        ki_down = _KEYBDINPUT(wVk=VK_RETURN, wScan=0, dwFlags=0, time=0,
                              dwExtraInfo=0)
        ki_up = _KEYBDINPUT(wVk=VK_RETURN, wScan=0, dwFlags=KEYEVENTF_KEYUP,
                            time=0, dwExtraInfo=0)
        _envia([_INPUT(type=INPUT_KEYBOARD, u=_INPUTunion(ki=ki_down)),
                _INPUT(type=INPUT_KEYBOARD, u=_INPUTunion(ki=ki_up))])

    def janela_em_foco() -> str:
        buf = ctypes.create_unicode_buffer(512)
        hwnd = _user32.GetForegroundWindow()
        _user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value

# --- Linux/macOS: pynput (bancada) ------------------------------------------

else:
    try:
        from pynput.keyboard import Controller, Key
        _teclado = Controller()
    except Exception:
        _teclado = None

    def digita(texto: str, atraso: float = 0.01):
        if _teclado is None:
            raise InjectorIndisponivel(
                "pynput indisponivel (no Linux exige X11 ou permissao de uinput)."
            )
        for ch in texto:
            _teclado.type(ch)
            if atraso:
                time.sleep(atraso)

    def tecla_enter():
        if _teclado is None:
            raise InjectorIndisponivel("pynput indisponivel")
        _teclado.press(Key.enter)
        _teclado.release(Key.enter)

    def janela_em_foco() -> str:
        return ""
