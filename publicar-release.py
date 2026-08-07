#!/usr/bin/env python3
"""Empacota dist/bio-pdv/ e publica a release no GitHub.

    python publicar-release.py 1.1.0 --notas "Corrige a digitacao no Windows"

Faz, nesta ordem:
  1. confere que biopdv/__init__.py declara a mesma versao
  2. zipa dist/bio-pdv/
  3. calcula o SHA-256 e escreve o manifest.json
  4. cria a release e sobe os dois arquivos (precisa do gh CLI autenticado)

Sem o gh instalado ele para no passo 3 e voce sobe os arquivos na mao.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(RAIZ, "dist", "bio-pdv")
SAIDA = os.path.join(RAIZ, "release")


def versao_do_codigo() -> str:
    init = os.path.join(RAIZ, "biopdv", "__init__.py")
    with open(init, encoding="utf-8") as f:
        m = re.search(r'__version__\s*=\s*"([^"]+)"', f.read())
    if not m:
        sys.exit("nao achei __version__ em biopdv/__init__.py")
    return m.group(1)


def sha256(caminho: str) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(65536), b""):
            h.update(bloco)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("versao", help="ex: 1.1.0")
    ap.add_argument("--notas", default="", help="o que mudou (vai na release)")
    ap.add_argument("--repo", default=os.environ.get("BIOPDV_REPO", ""),
                    help="ex: cooasgo/bio-pdv")
    ap.add_argument("--rascunho", action="store_true",
                    help="cria como rascunho, para revisar antes de publicar")
    args = ap.parse_args()

    versao = args.versao.lstrip("vV")

    codigo = versao_do_codigo()
    if codigo != versao:
        sys.exit(
            f"biopdv/__init__.py diz __version__ = '{codigo}', mas voce pediu "
            f"'{versao}'.\nAtualize o __init__.py primeiro -- e por ele que os "
            "caixas sabem em que versao estao.")

    if not os.path.isdir(DIST):
        sys.exit(f"nao existe {DIST}\nRode build-windows.bat antes.")

    os.makedirs(SAIDA, exist_ok=True)
    nome_zip = f"bio-pdv-{versao}-windows.zip"
    caminho_zip = os.path.join(SAIDA, nome_zip)

    print(f"[1/3] Zipando {DIST} ...")
    if os.path.exists(caminho_zip):
        os.remove(caminho_zip)
    base = caminho_zip[:-4]
    shutil.make_archive(base, "zip", root_dir=os.path.dirname(DIST),
                        base_dir=os.path.basename(DIST))

    print("[2/3] Calculando SHA-256 ...")
    digest = sha256(caminho_zip)
    tamanho = os.path.getsize(caminho_zip)
    manifesto = {
        "versao": versao,
        "arquivo": nome_zip,
        "sha256": digest,
        "tamanho": tamanho,
    }
    caminho_manifesto = os.path.join(SAIDA, "manifest.json")
    with open(caminho_manifesto, "w", encoding="utf-8") as f:
        json.dump(manifesto, f, indent=2)

    print(f"      {nome_zip}  ({tamanho / 1048576:.1f} MB)")
    print(f"      sha256 {digest}")

    if not shutil.which("gh"):
        print("\n[3/3] gh CLI nao encontrado. Suba na mao em:")
        print(f"      https://github.com/{args.repo or '<repo>'}/releases/new")
        print(f"      tag: v{versao}")
        print(f"      anexe: {caminho_zip}")
        print(f"              {caminho_manifesto}")
        print("\nOs DOIS arquivos sao obrigatorios: sem o manifest.json o "
              "app recusa a atualizacao (nao teria como conferir o hash).")
        return 0

    print("[3/3] Publicando no GitHub ...")
    cmd = ["gh", "release", "create", f"v{versao}",
           caminho_zip, caminho_manifesto,
           "--title", f"bio-pdv {versao}",
           "--notes", args.notas or f"Versao {versao}"]
    if args.repo:
        cmd += ["--repo", args.repo]
    if args.rascunho:
        cmd += ["--draft"]

    r = subprocess.run(cmd)
    if r.returncode != 0:
        return r.returncode

    print(f"\nPronto. Os caixas veem a {versao} em 'Atualizar'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
