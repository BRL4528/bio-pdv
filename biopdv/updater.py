"""Atualizacao pelo GitHub Releases.

Fluxo: le a release mais recente pela API -> compara versao -> baixa o .zip ->
confere o SHA-256 -> troca os arquivos e reabre.

MODELO DE CONFIANCA -- leia antes de confiar nisso:
  - O transporte e HTTPS com validacao de certificado. E isso que impede alguem
    na rede de trocar o pacote no meio do caminho.
  - O SHA-256 vem do proprio manifesto, baixado da MESMA origem. Logo ele
    protege contra download corrompido/parcial, NAO contra origem comprometida.
    Quem controlar a conta do GitHub controla os caixas. Proteja essa conta com
    2FA -- e o elo real.
  - Downgrade e recusado: um release nao pode empurrar versao anterior.

No Windows nao da pra sobrescrever um .exe em execucao. Por isso a troca sai num
.bat que espera este processo morrer, copia por cima e reabre.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass

from . import __version__

# Repositorio das releases. Troque para o seu.
REPO = os.environ.get("BIOPDV_REPO", "cooasgo/bio-pdv")

# Token opcional para repositorio privado.
# ATENCAO: token embutido num PC de caixa pode ser extraido de la. Use um token
# somente-leitura e restrito a este repositorio, ou deixe a release publica.
TOKEN = os.environ.get("BIOPDV_TOKEN", "")

API = "https://api.github.com/repos/{repo}/releases/latest"
TIMEOUT = 30
NOME_MANIFESTO = "manifest.json"


class UpdateError(Exception):
    pass


@dataclass
class Atualizacao:
    versao: str
    notas: str
    url_zip: str
    sha256: str
    tamanho: int


# --- versao -----------------------------------------------------------------


def _tupla(versao: str) -> tuple:
    """'v1.2.3' -> (1, 2, 3). Trecho nao numerico vira 0."""
    limpo = versao.strip().lstrip("vV").split("-")[0]
    partes = re.split(r"[._]", limpo)
    out = []
    for p in partes[:4]:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def versao_atual() -> str:
    return __version__


def instalado_como_exe() -> bool:
    """True quando empacotado pelo PyInstaller."""
    return getattr(sys, "frozen", False)


def pasta_instalacao() -> str:
    if instalado_como_exe():
        return os.path.dirname(os.path.abspath(sys.executable))
    # rodando do fonte: a raiz do projeto (pai do pacote biopdv)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- rede -------------------------------------------------------------------


def _abre(url: str, aceita_binario: bool = False):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", f"bio-pdv/{__version__}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if not aceita_binario:
        req.add_header("Accept", "application/vnd.github+json")
    else:
        req.add_header("Accept", "application/octet-stream")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    if not url.lower().startswith("https://"):
        raise UpdateError(f"recusando origem sem HTTPS: {url}")
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def checa() -> Atualizacao | None:
    """Devolve a atualizacao disponivel, ou None se ja esta na mais recente."""
    url = API.format(repo=REPO)
    try:
        with _abre(url) as r:
            dados = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(
                f"Repositorio '{REPO}' sem releases publicadas (ou privado sem "
                "token). Confira BIOPDV_REPO.")
        raise UpdateError(f"GitHub respondeu {exc.code}: {exc.reason}")
    except urllib.error.URLError as exc:
        raise UpdateError(f"Sem conexao com o GitHub: {exc.reason}")

    tag = dados.get("tag_name") or ""
    if not tag:
        raise UpdateError("release sem tag_name")

    if _tupla(tag) <= _tupla(versao_atual()):
        return None  # igual ou anterior -- downgrade nao passa

    ativos = {a.get("name"): a for a in dados.get("assets", [])}

    manifesto = ativos.get(NOME_MANIFESTO)
    if not manifesto:
        raise UpdateError(
            f"a release {tag} nao tem '{NOME_MANIFESTO}'. Sem ele nao da para "
            "conferir a integridade do pacote -- atualizacao recusada.")
    with _abre(manifesto["browser_download_url"]) as r:
        info = json.loads(r.read().decode("utf-8"))

    nome_zip = info.get("arquivo")
    sha = (info.get("sha256") or "").lower().strip()
    if not nome_zip or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise UpdateError("manifesto sem 'arquivo' ou 'sha256' valido")

    pacote = ativos.get(nome_zip)
    if not pacote:
        raise UpdateError(f"manifesto aponta '{nome_zip}', que nao esta na release")

    return Atualizacao(
        versao=tag.lstrip("vV"),
        notas=(dados.get("body") or "").strip() or "(sem notas nesta versao)",
        url_zip=pacote["browser_download_url"],
        sha256=sha,
        tamanho=int(pacote.get("size") or 0),
    )


def baixa(info: Atualizacao, progresso=None) -> str:
    """Baixa e CONFERE o SHA-256. Devolve o caminho do zip validado."""
    destino = os.path.join(tempfile.gettempdir(), f"bio-pdv-{info.versao}.zip")
    h = hashlib.sha256()
    lidos = 0
    with _abre(info.url_zip, aceita_binario=True) as r, open(destino, "wb") as f:
        while True:
            bloco = r.read(65536)
            if not bloco:
                break
            f.write(bloco)
            h.update(bloco)
            lidos += len(bloco)
            if progresso and info.tamanho:
                progresso(int(lidos * 100 / info.tamanho))

    obtido = h.hexdigest()
    if obtido != info.sha256:
        os.remove(destino)
        raise UpdateError(
            "SHA-256 nao confere -- pacote corrompido ou adulterado.\n"
            f"esperado: {info.sha256}\nobtido:   {obtido}")

    if not zipfile.is_zipfile(destino):
        os.remove(destino)
        raise UpdateError("o arquivo baixado nao e um zip valido")
    return destino


# --- aplicacao --------------------------------------------------------------

_BAT = r"""@echo off
chcp 65001 >nul
echo Atualizando o bio-pdv, aguarde...

rem espera o processo {pid} encerrar (o .exe fica travado enquanto roda)
set /a tentativas=0
:esperar
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if errorlevel 1 goto trocar
set /a tentativas+=1
if %tentativas% GTR 60 (
    echo Nao consegui fechar o bio-pdv. Feche manualmente e rode de novo.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto esperar

:trocar
robocopy "{novo}" "{destino}" /E /IS /IT /R:2 /W:1 >nul
rem robocopy: codigo abaixo de 8 e sucesso
if %ERRORLEVEL% GEQ 8 (
    echo Falha ao copiar os arquivos.
    pause
    exit /b 1
)

start "" "{exe}"
rmdir /S /Q "{temp}" 2>nul
exit /b 0
"""


def aplica(caminho_zip: str) -> None:
    """Extrai e agenda a troca. Depois de chamar isto, FECHE o app.

    No Windows escreve um .bat que espera este processo morrer, copia por cima
    e reabre. Em Linux/macOS copia na hora (nao ha trava de arquivo).
    """
    destino = pasta_instalacao()
    temp = tempfile.mkdtemp(prefix="bio-pdv-upd-")
    novo = os.path.join(temp, "novo")
    os.makedirs(novo, exist_ok=True)

    with zipfile.ZipFile(caminho_zip) as z:
        for membro in z.namelist():
            # nao deixa o zip escrever fora da pasta de destino (zip slip)
            alvo = os.path.realpath(os.path.join(novo, membro))
            if not alvo.startswith(os.path.realpath(novo) + os.sep) and \
               alvo != os.path.realpath(novo):
                raise UpdateError(f"zip com caminho suspeito: {membro}")
        z.extractall(novo)

    # se o zip tem uma unica pasta raiz, usa o conteudo dela
    itens = os.listdir(novo)
    if len(itens) == 1 and os.path.isdir(os.path.join(novo, itens[0])):
        novo = os.path.join(novo, itens[0])

    if not sys.platform.startswith("win"):
        shutil.copytree(novo, destino, dirs_exist_ok=True)
        shutil.rmtree(temp, ignore_errors=True)
        return

    exe = sys.executable if instalado_como_exe() else os.path.join(destino, "app.py")
    bat = os.path.join(temp, "atualizar.bat")
    with open(bat, "w", encoding="utf-8") as f:
        f.write(_BAT.format(pid=os.getpid(), novo=novo, destino=destino,
                            exe=exe, temp=temp))

    subprocess.Popen(
        ["cmd", "/c", bat],
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0),
        close_fds=True,
    )
