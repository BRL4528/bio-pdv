#!/usr/bin/env python3
"""bio-pdv — digital -> senha, no MorphoSmart CBM.

    python3 bio.py status                  # estado da base embarcada
    python3 bio.py enroll --user bruno     # cadastra o dedo e sorteia a senha
    python3 bio.py identify                # dedo -> senha
    python3 bio.py list                    # o que este PC conhece
    python3 bio.py forget --user bruno     # esquece a senha (nao mexe na base)

A base embarcada do modulo veio do relogio ponto com 188 digitais de terceiros.
Este programa so ADICIONA registros; nunca apaga nem exporta os existentes.

Layouts dos comandos ILV conferidos contra o SDK oficial em C
(github.com/Senthamilarasi/MSOlinuxDistrib-1.3).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import struct
import sys
import time

import morpho_ilv as m
from probe import open_port, read_frame

PORT_PADRAO = "/dev/ttyUSB0"
COFRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "senhas.json")

BASE_IDX = 0          # indice da base embarcada
THRESHOLD_FAR = 5     # 0..10; 5 e o recomendado pela Morpho
ID_CANCEL = 0x70
ID_GET_BASE_CONFIG = 0x07
ID_USER_ID = 0x04
ID_ASYNC_EVENT = 0x34

# T_MORPHO_COMMAND_STATUS -- feedback ao vivo do sensor
CMD_STATUS = {
    0: "aguardando dedo...",
    1: "mova o dedo para cima",
    2: "mova o dedo para baixo",
    3: "mova o dedo para a esquerda",
    4: "mova o dedo para a direita",
    5: "pressione mais firme",
    6: "imagem latente, limpe o sensor",
    7: "pode remover o dedo",
    8: "captura OK",
}

# status byte da resposta (libMSO_Def.h)
ERR = {
    0xFF: "erro generico", 0xFE: "parametro invalido", 0xFA: "timeout",
    0xF8: "usuario ja cadastrado", 0xF7: "base nao existe",
    0xF6: "base ja existe", 0xF5: "comando durante processamento biometrico",
    0xF4: "outro comando em andamento", 0xF2: "sem espaco na base",
    0xE6: "usuario nao encontrado", 0xE5: "abortado",
    0xE4: "mesmo dedo capturado duas vezes", 0xE3: "no-hit",
    0xDB: "dedo falso detectado", 0xDA: "dedo umido",
}

# resultado biometrico (byte 1)
RESULTADO = {1: "HIT", 2: "NO_HIT", 4: "base cheia", 5: "base vazia",
             6: "qualidade ruim", 0x22: "dedo falso", 0x23: "dedo umido"}


# --- cofre local ------------------------------------------------------------


def carrega_cofre() -> dict:
    if not os.path.exists(COFRE):
        return {}
    with open(COFRE) as f:
        return json.load(f)


def salva_cofre(dados: dict) -> None:
    with open(COFRE, "w") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)
    os.chmod(COFRE, 0o600)


def sorteia_senha(tamanho: int = 12) -> str:
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(tamanho))


# --- transporte -------------------------------------------------------------


def cancela(ser) -> None:
    """CANCEL (0x70). Limpa comando pendente -- evita o 0xF4."""
    ser.reset_input_buffer()
    ser.write(m.build_frame(m.build_ilv(ID_CANCEL, b"")))
    ser.flush()
    time.sleep(0.5)
    ser.reset_input_buffer()


def erro_de(v: bytes) -> str:
    st = v[0]
    nome = ERR.get(st, f"0x{st:02X}")
    if len(v) >= 5:
        return f"{nome} (interno {struct.unpack_from('<i', v, 1)[0]})"
    return nome


def conversa(ser, cmd_id: int, value: bytes, timeout_s: float, quieto=False):
    """Manda um comando e consome eventos 0x71 ate a resposta final."""
    ser.reset_input_buffer()
    ser.write(m.build_frame(m.build_ilv(cmd_id, value)))
    ser.flush()
    limite = time.monotonic() + timeout_s
    ultimo = None
    while time.monotonic() < limite:
        ilv = read_frame(ser)
        if ilv is None:
            continue
        v = ilv.value
        if ilv.id == 0x71:
            if quieto or len(v) < 4:
                continue
            tipo = v[1]
            if tipo == 1 and len(v) >= 8:
                c = struct.unpack_from("<i", v, 4)[0]
                txt = CMD_STATUS.get(c, str(c))
                if txt != ultimo:
                    print(f"   · {txt}")
                    ultimo = txt
            elif tipo == 4 and len(v) >= 8:
                dedo, tot_d, cap, tot_c = v[4], v[5], v[6], v[7]
                print(f"   · dedo {dedo}/{tot_d} — captura {cap}/{tot_c}")
            continue
        if ilv.id == cmd_id:
            return ilv
    return None


# --- comandos ---------------------------------------------------------------


def cmd_status(ser) -> int:
    cancela(ser)
    ilv = conversa(ser, ID_GET_BASE_CONFIG, bytes([BASE_IDX]), 4)
    if ilv is None:
        print("Sem resposta.")
        return 1
    v = ilv.value
    if v[0] != 0:
        print(f"Erro: {erro_de(v)}")
        return 1
    dedos = v[1]
    mx, cur, livre, ncampos = struct.unpack_from("<IIII", v, 2)
    print("Base embarcada do modulo:")
    print(f"  dedos por registro : {dedos}")
    print(f"  capacidade         : {mx}")
    print(f"  cadastradas        : {cur}")
    print(f"  livres             : {livre}")
    print(f"  campos adicionais  : {ncampos}")
    cofre = carrega_cofre()
    print(f"\nSenhas conhecidas por este PC: {len(cofre)}")
    return 0


def cmd_enroll(ser, user: str, timeout: int, dedos: int, aquisicoes: int) -> int:
    cofre = carrega_cofre()
    if any(r["user"] == user for r in cofre.values()):
        print(f"'{user}' ja tem senha neste PC. Use --force ou outro nome.")
        return 1

    cancela(ser)
    # V: base | timeout u16le | qualidade u8 | tipo u8 | dedos u8 | grava u8 | exporta u8
    tipo = 0 if aquisicoes == 3 else 1
    val = (
        bytes([BASE_IDX])
        + struct.pack("<H", timeout)
        + bytes([0, tipo, dedos, 1, 0])
        + m.build_ilv(ID_USER_ID, user.encode() + b"\x00")
        + m.build_ilv(ID_ASYNC_EVENT, struct.pack("<I", 1 | 4))
    )

    print(f"\nCadastrando '{user}' — {aquisicoes} captura(s) de {dedos} dedo(s).")
    print(">>> ENCOSTE O DEDO NO SENSOR <<<\n")
    ilv = conversa(ser, m.ID_ENROLL, val, timeout + 15)
    if ilv is None:
        print("\nTimeout sem resposta final.")
        return 1
    v = ilv.value
    if v[0] != 0:
        print(f"\nFalhou: {erro_de(v)}")
        return 1
    res = v[1] if len(v) > 1 else None
    if res not in (0, 1):
        print(f"\nCaptura recusada: {RESULTADO.get(res, res)}")
        return 1
    idx = struct.unpack_from("<I", v, 2)[0] if len(v) >= 6 else None

    senha = sorteia_senha()
    cofre[str(idx)] = {"user": user, "senha": senha, "em": time.strftime("%Y-%m-%d %H:%M")}
    salva_cofre(cofre)

    print(f"\n✅ Cadastrado. Indice na base do modulo: {idx}")
    print(f"   Senha sorteada para '{user}': {senha}")
    print(f"   Guardada em {COFRE} (permissao 600)")
    return 0


def cmd_identify(ser, timeout: int) -> int:
    cancela(ser)
    # V: base | timeout u16le | threshold u16le | qualidade u8
    val = (
        bytes([BASE_IDX])
        + struct.pack("<H", timeout)
        + struct.pack("<H", THRESHOLD_FAR)
        + bytes([0])
        + m.build_ilv(ID_ASYNC_EVENT, struct.pack("<I", 1))
    )
    print("\n>>> ENCOSTE O DEDO NO SENSOR <<<\n")
    ilv = conversa(ser, m.ID_IDENTIFY, val, timeout + 10)
    if ilv is None:
        print("Timeout sem resposta final.")
        return 1
    v = ilv.value
    if v[0] != 0:
        print(f"Falhou: {erro_de(v)}")
        return 1
    res = v[1]
    if res != 1:
        print(f"\n❌ {RESULTADO.get(res, res)} — digital nao reconhecida.")
        return 2
    idx = struct.unpack_from("<I", v, 2)[0]
    cofre = carrega_cofre()
    reg = cofre.get(str(idx))
    print(f"\n✅ HIT — indice {idx} na base do modulo")
    if reg:
        print(f"   Usuario : {reg['user']}")
        print(f"   SENHA   : {reg['senha']}")
    else:
        print("   (indice sem senha neste PC — provavelmente do relogio ponto)")
    return 0


def cmd_list() -> int:
    cofre = carrega_cofre()
    if not cofre:
        print("Nenhuma senha cadastrada neste PC.")
        return 0
    print(f"{'indice':>8}  {'usuario':<16} {'senha':<14} cadastro")
    for idx, r in sorted(cofre.items(), key=lambda kv: int(kv[0])):
        print(f"{idx:>8}  {r['user']:<16} {r['senha']:<14} {r.get('em','')}")
    return 0


def cmd_forget(user: str) -> int:
    cofre = carrega_cofre()
    alvo = [k for k, r in cofre.items() if r["user"] == user]
    if not alvo:
        print(f"'{user}' nao encontrado.")
        return 1
    for k in alvo:
        del cofre[k]
    salva_cofre(cofre)
    print(f"Senha de '{user}' esquecida. (A digital continua na base do modulo.)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("acao", choices=["status", "enroll", "identify", "list", "forget"])
    ap.add_argument("--port", default=PORT_PADRAO)
    ap.add_argument("--user", help="nome do usuario (enroll/forget)")
    ap.add_argument("--timeout", type=int, default=20, help="segundos para o dedo")
    ap.add_argument("--dedos", type=int, default=1, help="dedos por registro")
    ap.add_argument("--aquisicoes", type=int, default=3, choices=[1, 3],
                    help="capturas por dedo no enroll (3 = mais preciso)")
    args = ap.parse_args()

    if args.acao == "list":
        return cmd_list()
    if args.acao == "forget":
        if not args.user:
            ap.error("forget exige --user")
        return cmd_forget(args.user)

    try:
        ser = open_port(args.port, m.DEFAULT_BAUDRATE, timeout=1.0)
    except Exception as exc:
        print(f"Falha ao abrir {args.port}: {exc}")
        return 1

    with ser:
        if args.acao == "status":
            return cmd_status(ser)
        if args.acao == "enroll":
            if not args.user:
                ap.error("enroll exige --user")
            return cmd_enroll(ser, args.user, args.timeout, args.dedos, args.aquisicoes)
        if args.acao == "identify":
            return cmd_identify(ser, args.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
