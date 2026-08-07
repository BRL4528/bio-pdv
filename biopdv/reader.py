"""Driver do MorphoSmart CBM.

Layouts ILV conferidos contra o SDK oficial em C (MSOlinuxDistrib-1.3, libMSO).
Transporte: SYNC | size:u32le | ~size:u32le | ILV | "EN" a 38400 8N1.

Regra de ouro: CANCEL (0x70) antes de todo comando. Um enroll/identify pendente
deixa o modulo devolvendo 0xF4 (ILVERR_CMD_INPROGRESS) pra tudo.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass

import serial
from serial.tools import list_ports

VENDOR_ID = 0x079B
KNOWN_PRODUCTS = {0x0024: "MSO 300", 0x0047: "CBM OEM"}
BAUDRATE = 38400

SYNC = b"SYNC"
TAIL = b"EN"
HEADER_LEN = 12

# comandos
ILV_GET_DESCRIPTOR = 0x05
ILV_GET_BASE_CONFIG = 0x07
ILV_ENROLL = 0x21
ILV_IDENTIFY = 0x22
ILV_CREATE_DB = 0x30
ILV_REMOVE_RECORD = 0x36
ILV_CANCEL = 0x70
ILV_ASYNC = 0x71

# ids de campo aninhado
ID_USER_ID = 0x04
ID_ASYNC_EVENT = 0x34
ID_USER_INDEX = 0x36

BASE_IDX = 0
THRESHOLD_FAR = 5  # 0..10, recomendado pela Morpho

STATUS_ERRO = {
    0xFF: "erro generico", 0xFE: "parametro invalido", 0xFA: "timeout",
    0xF8: "usuario ja cadastrado", 0xF7: "base nao existe",
    0xF6: "base ja existe", 0xF5: "comando durante processamento biometrico",
    0xF4: "outro comando em andamento", 0xF2: "sem espaco na base",
    0xE6: "usuario nao encontrado", 0xE5: "abortado",
    0xE4: "mesmo dedo capturado duas vezes", 0xE3: "nao reconhecido",
    0xDB: "dedo falso detectado", 0xDA: "dedo umido",
}

RESULTADO = {
    0: "OK", 1: "HIT", 2: "NO_HIT", 4: "base cheia", 5: "base vazia",
    6: "qualidade ruim", 0x22: "dedo falso", 0x23: "dedo umido",
}

# T_MORPHO_COMMAND_STATUS -- feedback ao vivo
SENSOR = {
    0: "Encoste o dedo no leitor",
    1: "Mova o dedo para cima", 2: "Mova o dedo para baixo",
    3: "Mova o dedo para a esquerda", 4: "Mova o dedo para a direita",
    5: "Pressione com mais firmeza", 6: "Limpe o sensor",
    7: "Pode remover o dedo", 8: "Captura concluida",
}


class ReaderError(Exception):
    pass


class FrameError(ReaderError):
    pass


@dataclass
class BaseConfig:
    dedos: int
    capacidade: int
    cadastradas: int
    livres: int
    campos: int


@dataclass
class Resultado:
    """Retorno de enroll/identify."""
    ok: bool
    indice: int | None = None
    mensagem: str = ""


def _ilv(cmd: int, value: bytes = b"") -> bytes:
    return bytes([cmd]) + struct.pack("<H", len(value)) + value


def _frame(payload: bytes) -> bytes:
    n = len(payload)
    return SYNC + struct.pack("<II", n, ~n & 0xFFFFFFFF) + payload + TAIL


def detecta_portas() -> list[str]:
    """Portas cujo VID e da Morpho, mais candidatas genericas."""
    achadas = [p.device for p in list_ports.comports() if p.vid == VENDOR_ID]
    if achadas:
        return achadas
    # o driver usbserial generico do Linux nao propaga VID/PID
    return [p.device for p in list_ports.comports()
            if "ttyUSB" in p.device or "ttyACM" in p.device or "COM" in p.device]


class MorphoReader:
    """Sessao com o leitor. Use como context manager."""

    def __init__(self, port: str, baudrate: int = BAUDRATE, timeout: float = 1.0):
        self.port = port
        self._ser = serial.Serial(
            port=port, baudrate=baudrate, bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
        )
        for linha in ("dtr", "rts"):
            try:
                setattr(self._ser, linha, True)
            except (OSError, ValueError):
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._ser and self._ser.is_open:
            try:
                self.cancel()
            except Exception:
                pass
            self._ser.close()

    # --- transporte ---------------------------------------------------------

    def _le_frame(self):
        header = self._ser.read(HEADER_LEN)
        if not header:
            return None
        if len(header) < HEADER_LEN or not header.startswith(SYNC):
            raise FrameError(f"header invalido: {header!r}")
        size, comp = struct.unpack_from("<II", header, 4)
        if comp != (~size & 0xFFFFFFFF):
            raise FrameError("complemento do tamanho nao confere")
        body = self._ser.read(size + len(TAIL))
        if len(body) < size + len(TAIL) or not body.endswith(TAIL):
            raise FrameError("payload truncado")
        payload = body[:size]
        cmd = payload[0]
        vlen = struct.unpack_from("<H", payload, 1)[0]
        return cmd, payload[3:3 + vlen]

    def cancel(self):
        """Limpa comando pendente. Nao tem resposta propria."""
        self._ser.reset_input_buffer()
        self._ser.write(_frame(_ilv(ILV_CANCEL)))
        self._ser.flush()
        time.sleep(0.4)
        self._ser.reset_input_buffer()

    def _conversa(self, cmd: int, value: bytes, timeout_s: float, progresso=None):
        """Manda comando, consome eventos 0x71, devolve o value da resposta."""
        self._ser.reset_input_buffer()
        self._ser.write(_frame(_ilv(cmd, value)))
        self._ser.flush()
        limite = time.monotonic() + timeout_s
        ultimo = None
        while time.monotonic() < limite:
            lido = self._le_frame()
            if lido is None:
                continue
            rid, v = lido
            if rid == ILV_ASYNC:
                if progresso and len(v) >= 4:
                    tipo = v[1]
                    if tipo == 1 and len(v) >= 8:
                        c = struct.unpack_from("<i", v, 4)[0]
                        txt = SENSOR.get(c, f"status {c}")
                        if txt != ultimo:
                            progresso(txt, None)
                            ultimo = txt
                    elif tipo == 4 and len(v) >= 8:
                        progresso(None, (v[4], v[5], v[6], v[7]))
                continue
            if rid == cmd:
                return v
        return None

    @staticmethod
    def _erro(v: bytes) -> str:
        nome = STATUS_ERRO.get(v[0], f"status 0x{v[0]:02X}")
        if len(v) >= 5:
            interno = struct.unpack_from("<i", v, 1)[0]
            return f"{nome} (interno {interno})"
        return nome

    # --- comandos -----------------------------------------------------------

    def descritor(self) -> str:
        self.cancel()
        v = self._conversa(ILV_GET_DESCRIPTOR, bytes([0x2F]), 4)
        if v is None:
            raise ReaderError("sem resposta ao GET_DESCRIPTOR")
        if v[0] != 0:
            raise ReaderError(self._erro(v))
        return v[1:].decode("latin-1", "replace")

    def base_config(self) -> BaseConfig:
        self.cancel()
        v = self._conversa(ILV_GET_BASE_CONFIG, bytes([BASE_IDX]), 4)
        if v is None:
            raise ReaderError("sem resposta ao GET_BASE_CONFIG")
        if v[0] != 0:
            raise ReaderError(self._erro(v))
        dedos = v[1]
        mx, cur, livre, ncampos = struct.unpack_from("<IIII", v, 2)
        return BaseConfig(dedos, mx, cur, livre, ncampos)

    def enroll(self, user_id: str, timeout: int = 25, dedos: int = 1,
               aquisicoes: int = 3, progresso=None) -> Resultado:
        """Cadastra um dedo na base embarcada. Devolve o indice atribuido."""
        self.cancel()
        tipo = 0 if aquisicoes == 3 else 1
        val = (
            bytes([BASE_IDX])
            + struct.pack("<H", timeout)
            + bytes([0, tipo, dedos, 1, 0])
            + _ilv(ID_USER_ID, user_id.encode("latin-1", "replace") + b"\x00")
            + _ilv(ID_ASYNC_EVENT, struct.pack("<I", 1 | 4))
        )
        v = self._conversa(ILV_ENROLL, val, timeout + 20, progresso)
        if v is None:
            return Resultado(False, mensagem="Tempo esgotado sem resposta do leitor.")
        if v[0] != 0:
            return Resultado(False, mensagem=self._erro(v))
        res = v[1] if len(v) > 1 else 0
        if res not in (0, 1):
            return Resultado(False, mensagem=RESULTADO.get(res, f"resultado {res}"))
        idx = struct.unpack_from("<I", v, 2)[0] if len(v) >= 6 else None
        return Resultado(True, indice=idx, mensagem="Cadastro concluido")

    def identify(self, timeout: int = 20, progresso=None) -> Resultado:
        """Compara o dedo com a base. HIT devolve o indice."""
        self.cancel()
        val = (
            bytes([BASE_IDX])
            + struct.pack("<H", timeout)
            + struct.pack("<H", THRESHOLD_FAR)
            + bytes([0])
            + _ilv(ID_ASYNC_EVENT, struct.pack("<I", 1))
        )
        v = self._conversa(ILV_IDENTIFY, val, timeout + 10, progresso)
        if v is None:
            return Resultado(False, mensagem="Tempo esgotado.")
        if v[0] != 0:
            return Resultado(False, mensagem=self._erro(v))
        res = v[1]
        if res != 1:
            return Resultado(False, mensagem=RESULTADO.get(res, f"resultado {res}"))
        return Resultado(True, indice=struct.unpack_from("<I", v, 2)[0],
                         mensagem="Reconhecido")

    def remove_record(self, indice: int) -> Resultado:
        """Apaga UM registro da base embarcada (ILV_REMOVE_RECORD 0x36)."""
        self.cancel()
        val = bytes([BASE_IDX]) + _ilv(ID_USER_INDEX, struct.pack("<I", indice))
        v = self._conversa(ILV_REMOVE_RECORD, val, 8)
        if v is None:
            return Resultado(False, mensagem="Sem resposta do leitor.")
        if v[0] != 0:
            return Resultado(False, mensagem=self._erro(v))
        return Resultado(True, indice=indice, mensagem="Registro removido")
