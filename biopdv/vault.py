"""Cofre de senhas: indice na base do leitor -> senha do supervisor no PDV.

No Windows a senha e cifrada com DPAPI (CryptProtectData), amarrada a conta do
Windows daquela maquina: copiar o arquivo pra outro PC nao serve de nada.
Fora do Windows cai pra arquivo 0600 com aviso -- suficiente pra bancada.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import string
import sys
import time
from dataclasses import dataclass, asdict

WINDOWS = sys.platform.startswith("win")

try:  # pywin32 so existe no Windows
    import win32crypt  # type: ignore
    TEM_DPAPI = WINDOWS
except ImportError:
    TEM_DPAPI = False


def pasta_dados() -> str:
    if WINDOWS:
        raiz = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(raiz, "bio-pdv")
    else:
        d = os.path.join(os.path.expanduser("~"), ".config", "bio-pdv")
    os.makedirs(d, exist_ok=True)
    return d


ARQUIVO = os.path.join(pasta_dados(), "cofre.json")


@dataclass
class Registro:
    indice: int          # indice na base embarcada do leitor
    nome: str            # nome do supervisor (exibicao)
    login: str           # login dele no PDV
    senha: str           # senha do PDV -- em claro so na memoria
    criado_em: str


def gera_senha(tamanho: int = 14) -> str:
    """Senha aleatoria. So alfanumerico: passa em qualquer layout de teclado
    e em PDV que rejeita simbolo."""
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(tamanho))


def _cifra(texto: str) -> str:
    if TEM_DPAPI:
        blob = win32crypt.CryptProtectData(texto.encode("utf-8"), "bio-pdv",
                                           None, None, None, 0)
        return "dpapi:" + base64.b64encode(blob).decode("ascii")
    return "claro:" + base64.b64encode(texto.encode("utf-8")).decode("ascii")


def _decifra(guardado: str) -> str:
    modo, _, dado = guardado.partition(":")
    bruto = base64.b64decode(dado)
    if modo == "dpapi":
        if not TEM_DPAPI:
            raise RuntimeError("cofre cifrado com DPAPI; abra no Windows original")
        return win32crypt.CryptUnprotectData(bruto, None, None, None, 0)[1].decode("utf-8")
    return bruto.decode("utf-8")


class Vault:
    def __init__(self, caminho: str = ARQUIVO):
        self.caminho = caminho
        self._dados: dict[str, dict] = {}
        self.carrega()

    @property
    def protegido(self) -> bool:
        """True se as senhas estao cifradas com DPAPI (nao so ofuscadas)."""
        return TEM_DPAPI

    def carrega(self):
        if os.path.exists(self.caminho):
            with open(self.caminho, encoding="utf-8") as f:
                self._dados = json.load(f)
        else:
            self._dados = {}

    def salva(self):
        tmp = self.caminho + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._dados, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.caminho)
        if not WINDOWS:
            os.chmod(self.caminho, 0o600)

    # --- operacoes ----------------------------------------------------------

    def indices(self) -> list[int]:
        return sorted(int(k) for k in self._dados)

    def listar(self) -> list[Registro]:
        """Registros SEM a senha decifrada (para a tela de gestao)."""
        out = []
        for k, r in sorted(self._dados.items(), key=lambda kv: int(kv[0])):
            out.append(Registro(int(k), r["nome"], r.get("login", ""), "",
                                r.get("criado_em", "")))
        return out

    def existe_login(self, login: str) -> bool:
        return any(r.get("login") == login for r in self._dados.values())

    def adicionar(self, indice: int, nome: str, login: str, senha: str):
        self._dados[str(indice)] = {
            "nome": nome,
            "login": login,
            "senha": _cifra(senha),
            "criado_em": time.strftime("%Y-%m-%d %H:%M"),
        }
        self.salva()

    def senha_de(self, indice: int) -> Registro | None:
        r = self._dados.get(str(indice))
        if not r:
            return None
        return Registro(indice, r["nome"], r.get("login", ""),
                        _decifra(r["senha"]), r.get("criado_em", ""))

    def trocar_senha(self, indice: int, senha: str) -> bool:
        r = self._dados.get(str(indice))
        if not r:
            return False
        r["senha"] = _cifra(senha)
        self.salva()
        return True

    def remover(self, indice: int) -> bool:
        if str(indice) in self._dados:
            del self._dados[str(indice)]
            self.salva()
            return True
        return False
