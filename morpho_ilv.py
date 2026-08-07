"""Protocolo ILV do MorphoSmart (MSO 300 / CBM OEM) sobre porta serial.

O CBM se apresenta como CDC-ACM: no Windows vira uma porta COM (driver
usbser.sys nativo), no Linux vira /dev/ttyACM*. Nao precisa do SDK licenciado
da IDEMIA -- e serial 38400 8N1 falando ILV por cima.

Enquadramento (conferido contra alromh87/pyMorphoILV):

    "SYNC" | size:u32le | ~size:u32le | payload | "EN"

O payload e um ILV:  id:u8 | len:u16le | value[len]

Detalhe importante: ILV aninha. Quando `len` de um comando passa de 6, os
bytes seguintes ao 6o sao um novo ILV *dentro* do value do pai -- nao um irmao.
Ver walk_nested().
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# --- identificacao USB ------------------------------------------------------

VENDOR_ID = 0x079B  # Sagem / Safran / Morpho / IDEMIA

KNOWN_PRODUCTS = {
    0x0024: "MSO 300",
    0x0047: "CBM OEM",  # o modulo dos relogios ponto
}

DEFAULT_BAUDRATE = 38400

# --- enquadramento ----------------------------------------------------------

SYNC = b"SYNC"
TAIL = b"EN"
HEADER_LEN = len(SYNC) + 4 + 4  # 12
TAIL_LEN = len(TAIL)

# --- ids de comando ILV -----------------------------------------------------

ID_GET_DESCRIPTOR = 0x05
ID_ENROLL = 0x21
ID_IDENTIFY = 0x22
ID_CREATE_DB = 0x30
ID_DELETE_DB = 0x33
ID_ASYNCHRONOUS_EVENT = 0x34
ID_LATENT_SETTING = 0x39
ID_EXPORT_IMAGE = 0x3D
ID_COMPRESSION = 0x3E
ID_ASYNC_MESSAGE = 0x71

ID_INVALID_COMMAND = 0x50  # o modulo responde isso quando nao entende

COMMAND_NAMES = {
    ID_GET_DESCRIPTOR: "GET_DESCRIPTOR",
    ID_ENROLL: "ENROLL",
    ID_IDENTIFY: "IDENTIFY",
    ID_CREATE_DB: "CREATE_DB",
    ID_DELETE_DB: "DELETE_DB",
    ID_ASYNCHRONOUS_EVENT: "ASYNCHRONOUS_EVENT",
    ID_LATENT_SETTING: "LATENT_SETTING",
    ID_EXPORT_IMAGE: "EXPORT_IMAGE",
    ID_COMPRESSION: "COMPRESSION",
    ID_ASYNC_MESSAGE: "ASYNC_MESSAGE",
    ID_INVALID_COMMAND: "INVALID_COMMAND",
}

# --- codigos de retorno -----------------------------------------------------

ILV_OK = 0x00
ILVERR_CMDE_ABORTED = 0xE5

ILVSTS_OK = 0x00
ILVSTS_HIT = 0x01
ILVSTS_NO_HIT = 0x02
ILVSTS_DB_FULL = 0x04
ILVSTS_DB_EMPTY = 0x05
ILVSTS_FFD = 0x22  # fake finger detected
ILVSTS_MOIST_FINGER = 0x23

STATUS_NAMES = {
    ILVSTS_OK: "OK",
    ILVSTS_HIT: "HIT",
    ILVSTS_NO_HIT: "NO_HIT",
    ILVSTS_DB_FULL: "DB_FULL",
    ILVSTS_DB_EMPTY: "DB_EMPTY",
    ILVSTS_FFD: "FAKE_FINGER",
    ILVSTS_MOIST_FINGER: "MOIST_FINGER",
}


class MorphoError(Exception):
    pass


class FrameError(MorphoError):
    pass


@dataclass
class Ilv:
    """Um bloco ILV cru. `nested` sao os ILVs encontrados dentro do value."""

    id: int
    value: bytes
    nested: list["Ilv"] = field(default_factory=list)

    @property
    def name(self) -> str:
        return COMMAND_NAMES.get(self.id, f"0x{self.id:02X}")

    @property
    def status(self) -> int | None:
        """Primeiro byte do value -- codigo de erro do comando."""
        return self.value[0] if self.value else None

    def __str__(self) -> str:
        head = f"{self.name} len={len(self.value)}"
        if self.value:
            head += f" status=0x{self.status:02X}"
        if self.nested:
            head += " [" + ", ".join(str(n) for n in self.nested) + "]"
        return head


# --- montagem ---------------------------------------------------------------


def build_ilv(ilv_id: int, value: bytes = b"") -> bytes:
    """Monta um ILV: id | len(u16le) | value."""
    if len(value) > 0xFFFE:
        raise MorphoError("value acima de 65534 bytes exige o formato estendido")
    return bytes([ilv_id]) + struct.pack("<H", len(value)) + value


def build_frame(payload: bytes) -> bytes:
    """Envelopa o payload: SYNC | size | ~size | payload | EN."""
    size = len(payload)
    return (
        SYNC
        + struct.pack("<I", size)
        + struct.pack("<I", ~size & 0xFFFFFFFF)
        + payload
        + TAIL
    )


# --- leitura ----------------------------------------------------------------


def parse_header(header: bytes) -> int:
    """Valida o header de 12 bytes e devolve o tamanho do payload."""
    if len(header) < HEADER_LEN:
        raise FrameError(f"header curto: {len(header)} bytes (esperado {HEADER_LEN})")
    if not header.startswith(SYNC):
        raise FrameError(f"SYNC ausente: {header[:4]!r}")
    size = struct.unpack_from("<I", header, 4)[0]
    complement = struct.unpack_from("<I", header, 8)[0]
    if complement != (~size & 0xFFFFFFFF):
        raise FrameError(
            f"complemento invalido: size={size} ~size=0x{complement:08X}"
        )
    return size


def parse_ilv(data: bytes, offset: int = 0) -> tuple[Ilv, int]:
    """Le um ILV em `offset`. Devolve (ilv, offset_do_proximo_irmao)."""
    if offset + 3 > len(data):
        raise FrameError(f"ILV truncado em offset {offset}")
    ilv_id = data[offset]
    length = struct.unpack_from("<H", data, offset + 1)[0]
    start = offset + 3
    if length == 0xFFFF:  # formato estendido de 4 bytes
        length = struct.unpack_from("<I", data, start)[0]
        start += 4
    end = start + length
    if end > len(data):
        raise FrameError(
            f"ILV {ilv_id:#02x} declara {length} bytes mas so ha {len(data) - start}"
        )
    return Ilv(id=ilv_id, value=data[start:end]), end


def walk_nested(ilv: Ilv, first_nested_at: int = 6) -> Ilv:
    """Decodifica ILVs aninhados dentro do value, best-effort.

    Comandos como IDENTIFY (0x22) usam os 6 primeiros bytes do value para
    status + indice, e o que vem depois e um ILV filho. Se o parse falhar a
    gente simplesmente para -- o value cru continua disponivel.
    """
    offset = first_nested_at
    while offset + 3 <= len(ilv.value):
        try:
            child, offset = parse_ilv(ilv.value, offset)
        except FrameError:
            break
        ilv.nested.append(walk_nested(child))
    return ilv


def parse_payload(payload: bytes) -> Ilv:
    """Decodifica o payload de um frame como um ILV (com aninhados)."""
    ilv, _ = parse_ilv(payload, 0)
    return walk_nested(ilv)


# --- comandos ---------------------------------------------------------------


def cmd_get_descriptor() -> bytes:
    """GET_DESCRIPTOR -- o unico comando 100% confirmado. Use pra provar o link.

    Bytes identicos ao getInfo() do pyMorphoILV: 05 01 00 2F
    """
    return build_frame(build_ilv(ID_GET_DESCRIPTOR, bytes([0x2F])))


def decode_identify(ilv: Ilv) -> dict:
    """Interpreta a resposta de IDENTIFY (0x22).

    Layout do value: erro:u8 | ?:u8 | hit:u8 | db_index:u32le
    (erro em value[0], hit em value[1], indice em value[2:6])
    """
    if ilv.id != ID_IDENTIFY:
        raise MorphoError(f"esperado IDENTIFY, veio {ilv.name}")
    error = ilv.value[0] if ilv.value else None
    if error != ILV_OK:
        return {"ok": False, "error": error, "aborted": error == ILVERR_CMDE_ABORTED}
    hit = ilv.value[1] if len(ilv.value) > 1 else None
    result = {"ok": True, "hit": hit, "hit_name": STATUS_NAMES.get(hit, hex(hit or 0))}
    if hit == ILVSTS_HIT and len(ilv.value) >= 6:
        result["db_index"] = struct.unpack_from("<I", ilv.value, 2)[0]
    return result


def hexdump(data: bytes) -> str:
    return ":".join(f"{b:02x}" for b in data)
