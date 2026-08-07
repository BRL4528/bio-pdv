#!/usr/bin/env python3
"""Sonda de bancada do MorphoSmart CBM.

Objetivo desta fase: provar que o modulo responde. Nada de biometria ainda.

    python3 probe.py --list                # acha a porta
    python3 probe.py                       # GET_DESCRIPTOR na porta detectada
    python3 probe.py --port COM3           # forca a porta (Windows)
    python3 probe.py --raw 05:01:00:2f     # manda um ILV cru
    python3 probe.py --monitor             # so escuta (pra ver evento assincrono)

Se GET_DESCRIPTOR responder, o link esta de pe e o resto e software.
"""

from __future__ import annotations

import argparse
import sys

import serial
from serial.tools import list_ports

import morpho_ilv as m


def find_ports() -> list:
    """Portas seriais cujo VID e da Morpho."""
    return [p for p in list_ports.comports() if p.vid == m.VENDOR_ID]


def cmd_list() -> int:
    all_ports = list(list_ports.comports())
    if not all_ports:
        print("Nenhuma porta serial encontrada.")
        return 1

    print("Portas seriais visiveis:")
    for p in all_ports:
        tag = ""
        if p.vid == m.VENDOR_ID:
            model = m.KNOWN_PRODUCTS.get(p.pid, f"PID desconhecido 0x{p.pid:04X}")
            tag = f"  <== MORPHO ({model})"
        vid = f"{p.vid:04X}" if p.vid is not None else "----"
        pid = f"{p.pid:04X}" if p.pid is not None else "----"
        print(f"  {p.device:<20} {vid}:{pid}  {p.description}{tag}")

    found = find_ports()
    if not found:
        print(
            "\nModulo NAO encontrado. Confira:\n"
            "  - VBUS/D-/D+/GND do modulo ligados corretamente no plug USB\n"
            "  - alimentacao (o CBM puxa corrente, porta USB fraca nao sustenta)\n"
            "  - Linux: dmesg | tail   deve mostrar 'cdc_acm' anexando ttyACM*\n"
            "  - Windows: Gerenciador de Dispositivos deve criar uma porta COM"
        )
        return 1
    return 0


def read_frame(ser: serial.Serial) -> m.Ilv | None:
    """Le um frame completo: header de 12 bytes, depois payload + 'EN'."""
    header = ser.read(m.HEADER_LEN)
    if not header:
        return None
    size = m.parse_header(header)
    body = ser.read(size + m.TAIL_LEN)
    if len(body) < size + m.TAIL_LEN:
        raise m.FrameError(
            f"payload truncado: esperado {size + m.TAIL_LEN}, veio {len(body)}"
        )
    if not body.endswith(m.TAIL):
        raise m.FrameError(f"tail 'EN' ausente: {body[-2:]!r}")

    payload = body[:size]
    print(f"<-- {m.hexdump(header + body)}")
    return m.parse_payload(payload)


def send(ser: serial.Serial, frame: bytes) -> None:
    print(f"--> {m.hexdump(frame)}")
    ser.reset_input_buffer()
    ser.write(frame)
    ser.flush()


def open_port(port: str, baudrate: int, timeout: float) -> serial.Serial:
    ser = serial.Serial(
        port=port,
        baudrate=baudrate,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=timeout,
    )
    # Equivalente ao SET_CONTROL_LINE_STATE 0x03 que o pyMorphoILV faz na mao.
    # Necessario na via CDC-ACM; na via TTL nao existe linha de controle e o
    # ioctl falha (pty, alguns adaptadores) -- nao e motivo pra abortar.
    for linha in ("dtr", "rts"):
        try:
            setattr(ser, linha, True)
        except (OSError, ValueError):
            pass
    return ser


# O guia oficial documenta "From 9,600 bps to 115,200 bps" pra serial do CBM.
# 38400 primeiro porque e o que o pyMorphoILV usa por padrao.
CANDIDATE_BAUDS = [38400, 9600, 19200, 57600, 115200]


def cmd_scan_baud(port: str, timeout: float = 1.5) -> int:
    """Manda GET_DESCRIPTOR em varios baudrates e mostra o que voltou.

    Na via TTL o baudrate pode ter sido mudado pelo integrador do relogio ponto.
    Qualquer byte de resposta ja e sinal de vida; 'SYNC' no inicio e o alvo.
    """
    frame = m.cmd_get_descriptor()
    acertos = []

    for baud in CANDIDATE_BAUDS:
        try:
            with open_port(port, baud, timeout) as ser:
                ser.reset_input_buffer()
                ser.write(frame)
                ser.flush()
                data = ser.read(m.HEADER_LEN)
        except serial.SerialException as exc:
            print(f"  {baud:>7} : erro ao abrir ({exc})")
            continue

        if not data:
            print(f"  {baud:>7} : silencio")
        elif data.startswith(m.SYNC):
            print(f"  {baud:>7} : *** SYNC! *** {m.hexdump(data)}")
            acertos.append(baud)
        else:
            print(f"  {baud:>7} : {len(data)} bytes de lixo -> {m.hexdump(data)}")

    print()
    if acertos:
        print(f"Use --baud {acertos[0]}")
        return 0

    print(
        "Nada respondeu. Nesta ordem:\n"
        "  1. TX/RX trocados -- inverte os dois fios (nao ha risco nisso)\n"
        "  2. Falta o pull-up: saida do modulo e OPEN-COLLECTOR, poe 4k7\n"
        "     do TX do modulo pro VCC de logica\n"
        "  3. GND nao esta comum entre modulo e adaptador\n"
        "  4. Alimentacao fraca: nao use o regulador do adaptador, o CBM\n"
        "     puxa centenas de mA\n"
        "Se saiu lixo em algum baud, o link existe e e so sincronizar."
    )
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="lista portas e sai")
    ap.add_argument("--port", help="porta serial (COM3, /dev/ttyACM0)")
    ap.add_argument("--baud", type=int, default=m.DEFAULT_BAUDRATE)
    ap.add_argument("--timeout", type=float, default=3.0, help="segundos")
    ap.add_argument("--raw", help="payload ILV em hex, ex: 05:01:00:2f")
    ap.add_argument("--monitor", action="store_true", help="so escuta frames")
    ap.add_argument(
        "--scan-baud",
        action="store_true",
        help="varre baudrates comuns procurando resposta (util na via TTL)",
    )
    args = ap.parse_args()

    if args.list:
        return cmd_list()

    port = args.port
    if not port:
        found = find_ports()
        if not found:
            print(
                "Modulo nao detectado por VID/PID.\n"
                "  - Na via USB: rode --list pra diagnosticar.\n"
                "  - Na via TTL: normal! O adaptador USB-TTL tem VID proprio,\n"
                "    entao passe a porta na mao: --port /dev/ttyUSB0 (ou COM4)."
            )
            return 1
        port = found[0].device
        model = m.KNOWN_PRODUCTS.get(found[0].pid, "modelo desconhecido")
        print(f"Detectado {model} em {port}")

    if args.scan_baud:
        return cmd_scan_baud(port)

    try:
        ser = open_port(port, args.baud, args.timeout)
    except serial.SerialException as exc:
        print(f"Falha ao abrir {port}: {exc}")
        print("Linux: seu usuario precisa estar no grupo dialout.")
        return 1

    with ser:
        if args.monitor:
            print("Escutando (Ctrl+C pra sair)...")
            try:
                while True:
                    try:
                        ilv = read_frame(ser)
                    except m.FrameError as exc:
                        print(f"    frame invalido: {exc}")
                        continue
                    if ilv:
                        print(f"    {ilv}")
            except KeyboardInterrupt:
                return 0

        if args.raw:
            payload = bytes(int(b, 16) for b in args.raw.replace(":", " ").split())
            frame = m.build_frame(payload)
        else:
            frame = m.cmd_get_descriptor()

        send(ser, frame)
        try:
            ilv = read_frame(ser)
        except m.FrameError as exc:
            print(f"Resposta malformada: {exc}")
            return 1

        if ilv is None:
            print(
                "TIMEOUT -- nenhum byte voltou.\n"
                "  - baudrate errado? tente --baud 9600 / 57600 / 115200\n"
                "  - TX/RX invertidos (se estiver na via TTL em vez de USB)"
            )
            return 1

        print(f"\nResposta: {ilv}")
        if ilv.id == m.ID_INVALID_COMMAND:
            print("O modulo respondeu INVALID_COMMAND -- link OK, comando errado.")
        else:
            print("Link de pe. Enquadramento e baudrate confirmados.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
