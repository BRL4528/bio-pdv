#!/usr/bin/env python3
"""Empacota dist/bio-pdv/ e publica a release no GitHub.

    python publicar-release.py 1.1.0 --notas "Corrige a digitacao no Windows"

Faz, nesta ordem:
  1. confere que biopdv/__init__.py declara a mesma versao
  2. zipa dist/bio-pdv/
  3. calcula o SHA-256 e escreve o manifest.json
  4. cria a release e sobe o zip + manifest + instalador (precisa do gh CLI
     autenticado)

O zip + manifest.json alimentam o auto-updater interno do app (troca em
silencio, sem instalador). O bio-pdv-setup.exe (Inno Setup, ve --instalador)
e o que uma pessoa baixa na pagina de Releases e instala com duplo clique — e
o unico asset obrigatorio pra quem so quer instalar do zero. Sem o gh
instalado, o script para no passo 3 e voce sobe os arquivos na mao.
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


def repo_padrao() -> str:
    """De onde sai o repositorio quando nao vem por --repo.

    Ordem: BIOPDV_REPO -> remote do git -> o REPO compilado no updater.
    """
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=RAIZ, timeout=10,
        ).stdout.strip()
        m = re.search(r"github\.com[:/]+([^/]+/[^/.]+)", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    try:
        sys.path.insert(0, RAIZ)
        from biopdv.updater import REPO
        return REPO
    except Exception:
        return ""


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
    ap.add_argument("--repo", default="",
                    help="ex: BRL4528/bio-pdv (padrao: remote do git / updater)")
    ap.add_argument("--rascunho", action="store_true",
                    help="cria como rascunho, para revisar antes de publicar")
    ap.add_argument("--instalador", default="",
                    help="caminho do bio-pdv-setup.exe (Inno Setup); se "
                         "omitido, procura em Output/bio-pdv-setup.exe")
    args = ap.parse_args()

    versao = args.versao.lstrip("vV")
    repo = args.repo or os.environ.get("BIOPDV_REPO", "") or repo_padrao()

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

    instalador = args.instalador or os.path.join(RAIZ, "Output", "bio-pdv-setup.exe")
    tem_instalador = os.path.isfile(instalador)
    if args.instalador and not tem_instalador:
        sys.exit(f"instalador nao encontrado: {instalador}\n"
                  "Compile instalador.iss no Inno Setup antes (ou rode sem "
                  "--instalador se so quer atualizar o auto-updater).")
    if not tem_instalador:
        print(f"      [aviso] {instalador} nao existe — a release vai sair sem")
        print("      o instalador de duplo clique, so com zip+manifest (auto-updater).")

    if not shutil.which("gh"):
        alvo = (f"https://github.com/{repo}/releases/new"
                if repo else "https://github.com/<seu-usuario>/<repo>/releases/new")
        print("\n[3/3] gh CLI nao encontrado — suba os arquivos na mao.")
        print(f"\n  1. Abra: {alvo}")
        print(f"  2. Tag  : v{versao}")
        print(f"  3. Anexe os arquivos:")
        print(f"       {caminho_zip}          (obrigatorio — auto-updater)")
        print(f"       {caminho_manifesto}    (obrigatorio — auto-updater)")
        if tem_instalador:
            print(f"       {instalador}  (o que as pessoas baixam pra instalar)")
        print("\nSem o manifest.json o app RECUSA a atualizacao: e dele que sai")
        print("o SHA-256 usado para conferir o pacote.")
        print("\nPara automatizar da proxima vez:  winget install GitHub.cli")
        return 0

    print(f"[3/3] Publicando em {repo or '(remote atual)'} ...")
    arquivos = [caminho_zip, caminho_manifesto]
    if tem_instalador:
        arquivos.append(instalador)
    cmd = ["gh", "release", "create", f"v{versao}",
           *arquivos,
           "--title", f"bio-pdv {versao}",
           "--notes", args.notas or f"Versao {versao}"]
    if repo:
        cmd += ["--repo", repo]
    if args.rascunho:
        cmd += ["--draft"]

    r = subprocess.run(cmd)
    if r.returncode != 0:
        return r.returncode

    print(f"\nPronto. Os caixas veem a {versao} em 'Atualizar'.")
    if tem_instalador:
        print(f"Instalacao do zero: baixe bio-pdv-setup.exe na pagina de Releases.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
