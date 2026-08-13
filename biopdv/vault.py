"""Cofre local: liga o indice do LEITOR DESTA MAQUINA a um supervisor, e
mantem um cache do que o servidor central (samasc-api) sincronizou.

Dois niveis, e a razao de existirem separados:
  - `indices_locais`  (indice -> login): o indice e uma posicao na base
    DAQUELE leitor fisico -- nao tem significado fora dele. Nunca sincroniza.
  - `cache_supervisores` (login -> nome/senha/ativo/atualizado_em): espelho
    do que o servidor central mandou na ultima sincronizacao. Sobrescrito a
    cada pull -- e por isso que trocar a senha centralmente propaga sem
    precisar tocar o leitor de novo em lugar nenhum.

No Windows a senha e cifrada com DPAPI (CryptProtectData), amarrada a conta
do Windows daquela maquina: copiar o arquivo pra outro PC nao serve de nada
-- por isso a senha em si tambem viaja cifrada (AES-256-GCM) e so em claro
por HTTPS entre o app e o samasc-api, nunca em disco.
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
from dataclasses import dataclass

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

VERSAO_ATUAL = 2


@dataclass
class Registro:
    indice: int          # indice na base embarcada do leitor DESTA maquina
    nome: str            # nome do supervisor (exibicao)
    login: str           # login dele no PDV -- chave estavel entre PDVs
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
        self._indices: dict[str, dict] = {}       # indice -> {login, criado_em}
        self._supervisores: dict[str, dict] = {}   # login -> {nome, senha, ativo, atualizado_em, nunca_enviado?}
        self._ultima_sincronizacao: str | None = None
        self.carrega()

    @property
    def protegido(self) -> bool:
        """True se as senhas estao cifradas com DPAPI (nao so ofuscadas)."""
        return TEM_DPAPI

    @property
    def ultima_sincronizacao(self) -> str | None:
        return self._ultima_sincronizacao

    def carrega(self):
        if not os.path.exists(self.caminho):
            self._indices = {}
            self._supervisores = {}
            self._ultima_sincronizacao = None
            return

        with open(self.caminho, encoding="utf-8") as f:
            bruto = json.load(f)

        if bruto.get("versao") == VERSAO_ATUAL:
            self._indices = bruto.get("indices", {})
            self._supervisores = bruto.get("supervisores", {})
            self._ultima_sincronizacao = bruto.get("ultima_sincronizacao")
            return

        # Formato antigo (v1): {indice: {nome, login, senha, criado_em}}.
        # Migra para os dois mapas e marca os supervisores como pendentes de
        # adocao -- a proxima sincronizacao com um admin logado os envia ao
        # servidor central, pra nao perder os cadastros ja feitos.
        self._indices = {}
        self._supervisores = {}
        for indice, registro in bruto.items():
            login = registro.get("login") or f"pdv-legado-{indice}"
            self._indices[indice] = {
                "login": login,
                "criado_em": registro.get("criado_em", ""),
            }
            self._supervisores[login] = {
                "nome": registro.get("nome", login),
                "senha": registro.get("senha", ""),
                "ativo": True,
                "atualizado_em": registro.get("criado_em", ""),
                "nunca_enviado": True,
            }
        self._ultima_sincronizacao = None
        self.salva()

    def salva(self):
        tmp = self.caminho + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "versao": VERSAO_ATUAL,
                "indices": self._indices,
                "supervisores": self._supervisores,
                "ultima_sincronizacao": self._ultima_sincronizacao,
            }, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.caminho)
        if not WINDOWS:
            os.chmod(self.caminho, 0o600)

    # --- leitura para a UI ---------------------------------------------------

    def indices(self) -> list[int]:
        return sorted(int(k) for k in self._indices)

    def listar(self) -> list[Registro]:
        """Registros SEM a senha decifrada, um por indice vinculado NESTA
        maquina (para a tabela da aba Supervisores)."""
        out = []
        for k, link in sorted(self._indices.items(), key=lambda kv: int(kv[0])):
            login = link["login"]
            sup = self._supervisores.get(login, {})
            out.append(Registro(int(k), sup.get("nome", login), login, "",
                                link.get("criado_em", "")))
        return out

    def nao_vinculados(self) -> list[tuple[str, str]]:
        """Logins conhecidos pela sincronizacao mas sem digital cadastrada
        NESTE leitor ainda -- para o combo de "vincular supervisor existente"."""
        vinculados = {link["login"] for link in self._indices.values()}
        return sorted(
            (login, sup["nome"])
            for login, sup in self._supervisores.items()
            if sup.get("ativo", True) and login not in vinculados
        )

    def existe_login(self, login: str) -> bool:
        return login in self._supervisores

    # --- escrita local --------------------------------------------------

    def adicionar(self, indice: int, nome: str, login: str, senha: str):
        """Novo supervisor: grava o vinculo local E o cache (fonte da verdade
        ainda e o servidor -- quem chama isto tambem deve chamar
        sync.enviar_supervisor, exceto em teste/uso 100% offline)."""
        agora = time.strftime("%Y-%m-%d %H:%M")
        self._indices[str(indice)] = {"login": login, "criado_em": agora}
        self._supervisores[login] = {
            "nome": nome, "senha": _cifra(senha), "ativo": True,
            "atualizado_em": agora,
        }
        self.salva()

    def vincular(self, indice: int, login: str) -> bool:
        """Supervisor ja conhecido via sincronizacao: so grava o vinculo
        biometrico local, sem tocar nome/senha (que vieram do servidor)."""
        if login not in self._supervisores:
            return False
        self._indices[str(indice)] = {
            "login": login, "criado_em": time.strftime("%Y-%m-%d %H:%M"),
        }
        self.salva()
        return True

    def senha_de(self, indice: int) -> Registro | None:
        link = self._indices.get(str(indice))
        if not link:
            return None
        sup = self._supervisores.get(link["login"])
        if not sup or not sup.get("ativo", True):
            return None
        return Registro(indice, sup["nome"], link["login"],
                        _decifra(sup["senha"]), link.get("criado_em", ""))

    def trocar_senha(self, indice: int, senha: str) -> bool:
        link = self._indices.get(str(indice))
        if not link or link["login"] not in self._supervisores:
            return False
        sup = self._supervisores[link["login"]]
        sup["senha"] = _cifra(senha)
        sup["atualizado_em"] = time.strftime("%Y-%m-%d %H:%M")
        self.salva()
        return True

    def remover(self, indice: int) -> bool:
        """Remove so o vinculo biometrico DESTA maquina. O supervisor
        continua existindo para os outros PDVs -- exclusao de verdade e
        feita no servidor (sync.remover_supervisor), que propaga."""
        if str(indice) in self._indices:
            del self._indices[str(indice)]
            self.salva()
            return True
        return False

    # --- sincronizacao ----------------------------------------------------

    def aplica_sincronizacao(self, registros: list) -> None:
        """Sobrescreve o cache com o que o servidor mandou. `registros` e
        uma lista de sync.RegistroSupervisor."""
        cursor = self._ultima_sincronizacao
        for r in registros:
            self._supervisores[r.login] = {
                "nome": r.nome, "senha": _cifra(r.senha),
                "ativo": r.ativo, "atualizado_em": r.atualizado_em,
            }
            if cursor is None or r.atualizado_em > cursor:
                cursor = r.atualizado_em
        if cursor is not None:
            self._ultima_sincronizacao = cursor
        self.salva()

    def pendentes_adocao(self) -> list[Registro]:
        """Supervisores criados antes de existir sincronizacao (migrados de
        um cofre.json v1) que ainda precisam ser enviados ao servidor."""
        out = []
        for login, sup in self._supervisores.items():
            if sup.get("nunca_enviado"):
                out.append(Registro(0, sup["nome"], login,
                                    _decifra(sup["senha"]),
                                    sup.get("atualizado_em", "")))
        return out

    def marca_adotado(self, login: str) -> None:
        sup = self._supervisores.get(login)
        if sup:
            sup.pop("nunca_enviado", None)
            self.salva()
