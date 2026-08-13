"""Sincronizacao de supervisores com o samasc-api.

Duas credenciais diferentes, dois propositos:
  - Login do ERP (nickname/senha, POST /sessions): so quem tem tag=='admin'
    la pode cadastrar/editar/excluir supervisor. Usado ao vivo, nunca fica
    salvo no disco -- pedido de novo a cada abertura da tela de Gestao.
  - Token de dispositivo (X-Pdv-Token): so LEITURA. Cada PDV tem o seu,
    provisionado uma vez por um admin, salvo cifrado em disco (mesma DPAPI do
    cofre.json) para o agente sincronizar sozinho em segundo plano, sem
    ninguem logado.

Sem dependencia nova: urllib.request, igual ao updater.py.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__
from .vault import _cifra, _decifra, pasta_dados

TIMEOUT = 20

ARQUIVO_DISPOSITIVO = os.path.join(pasta_dados(), "dispositivo.json")


class SyncError(Exception):
    pass


class NaoAutorizado(SyncError):
    """401/403 -- credencial invalida, expirada ou sem tag admin."""


@dataclass
class RegistroSupervisor:
    login: str
    nome: str
    senha: str
    ativo: bool
    atualizado_em: str


@dataclass
class RegistroAppAutorizado:
    executavel: str
    descricao: str
    ativo: bool
    atualizado_em: str


# --- configuracao local do dispositivo --------------------------------------


def dispositivo_configurado() -> dict | None:
    if not os.path.exists(ARQUIVO_DISPOSITIVO):
        return None
    with open(ARQUIVO_DISPOSITIVO, encoding="utf-8") as f:
        dados = json.load(f)
    dados["device_token"] = _decifra(dados["device_token"])
    return dados


def _salva_dispositivo(base_url: str, nome: str, device_token: str) -> None:
    tmp = ARQUIVO_DISPOSITIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            {"base_url": base_url.rstrip("/"), "nome": nome,
             "device_token": _cifra(device_token)},
            f, indent=2, ensure_ascii=False,
        )
    os.replace(tmp, ARQUIVO_DISPOSITIVO)


# --- rede ---------------------------------------------------------------


def _requisicao(method: str, url: str, headers: dict, corpo: dict | None = None) -> dict | None:
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=method)
    req.add_header("User-Agent", f"bio-pdv/{__version__}")
    req.add_header("Content-Type", "application/json")
    for chave, valor in headers.items():
        req.add_header(chave, valor)
    if not url.lower().startswith("https://") and "localhost" not in url and "127.0.0.1" not in url:
        raise SyncError(f"recusando origem sem HTTPS: {url}")

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            corpo_resposta = r.read()
            return json.loads(corpo_resposta) if corpo_resposta else None
    except urllib.error.HTTPError as exc:
        mensagem = _mensagem_erro(exc)
        if exc.code in (401, 403):
            raise NaoAutorizado(mensagem) from exc
        raise SyncError(mensagem) from exc
    except urllib.error.URLError as exc:
        raise SyncError(f"sem conexao com o servidor central: {exc.reason}") from exc


def _mensagem_erro(exc: urllib.error.HTTPError) -> str:
    try:
        dados = json.loads(exc.read())
        return dados.get("message") or f"{exc.code} {exc.reason}"
    except Exception:
        return f"{exc.code} {exc.reason}"


# --- login do ERP (so em memoria, nunca gravado) ----------------------------


def login_erp(base_url: str, nickname: str, senha: str) -> tuple[dict, str]:
    """Devolve (access, token). access['tag'] == 'admin' libera a gestao."""
    resposta = _requisicao(
        "POST", f"{base_url.rstrip('/')}/sessions", {},
        {"nickname": nickname, "password": senha},
    )
    return resposta["access"], resposta["token"]


def eh_admin(access: dict) -> bool:
    return access.get("tag") == "admin"


# --- provisionamento do token de leitura da maquina -------------------------


def provisionar_dispositivo(base_url: str, token_admin: str, nome: str) -> None:
    resposta = _requisicao(
        "POST", f"{base_url.rstrip('/')}/pdv-devices",
        {"Authorization": f"Bearer {token_admin}"},
        {"nome": nome},
    )
    _salva_dispositivo(base_url, nome, resposta["token"])


# --- supervisores -------------------------------------------------------


def enviar_supervisor(base_url: str, token_admin: str, login: str, nome: str, senha: str) -> None:
    _requisicao(
        "POST", f"{base_url.rstrip('/')}/pdv-supervisores",
        {"Authorization": f"Bearer {token_admin}"},
        {"login": login, "nome": nome, "senha": senha},
    )


def remover_supervisor(base_url: str, token_admin: str, login: str) -> None:
    _requisicao(
        "DELETE", f"{base_url.rstrip('/')}/pdv-supervisores/{login}",
        {"Authorization": f"Bearer {token_admin}"},
    )


def sincronizar(desde: str | None = None) -> list[RegistroSupervisor]:
    """Pull incremental usando o token de leitura desta maquina.

    desde: atualizado_em (ISO) do ultimo registro visto; None pega tudo.
    """
    dispositivo = dispositivo_configurado()
    if dispositivo is None:
        raise SyncError("este PDV ainda nao foi configurado (sem token de sincronizacao)")

    url = f"{dispositivo['base_url']}/pdv-supervisores"
    if desde:
        url += f"?desde={desde}"

    resposta = _requisicao(
        "GET", url, {"X-Pdv-Token": dispositivo["device_token"]},
    )
    return [RegistroSupervisor(**item) for item in (resposta or [])]


# --- apps autorizados (lista de executaveis que podem receber a senha) -----


def enviar_app_autorizado(base_url: str, token_admin: str, executavel: str, descricao: str) -> RegistroAppAutorizado:
    """Devolve o registro salvo (com o atualizado_em de verdade do servidor)
    para o chamador gravar local na hora, sem depender de uma sincronizacao
    assincrona separada pra refletir na tela."""
    resposta = _requisicao(
        "POST", f"{base_url.rstrip('/')}/pdv-apps-autorizados",
        {"Authorization": f"Bearer {token_admin}"},
        {"executavel": executavel, "descricao": descricao},
    )
    return RegistroAppAutorizado(
        executavel=resposta["executavel"], descricao=resposta["descricao"],
        ativo=resposta["ativo"], atualizado_em=resposta["atualizado_em"])


def remover_app_autorizado(base_url: str, token_admin: str, executavel: str) -> None:
    _requisicao(
        "DELETE", f"{base_url.rstrip('/')}/pdv-apps-autorizados/{executavel}",
        {"Authorization": f"Bearer {token_admin}"},
    )


def sincronizar_apps(desde: str | None = None) -> list[RegistroAppAutorizado]:
    """Pull incremental dos apps autorizados, mesmo token de leitura desta maquina."""
    dispositivo = dispositivo_configurado()
    if dispositivo is None:
        raise SyncError("este PDV ainda nao foi configurado (sem token de sincronizacao)")

    url = f"{dispositivo['base_url']}/pdv-apps-autorizados"
    if desde:
        url += f"?desde={desde}"

    resposta = _requisicao(
        "GET", url, {"X-Pdv-Token": dispositivo["device_token"]},
    )
    campos = {"executavel", "descricao", "ativo", "atualizado_em"}
    return [RegistroAppAutorizado(**{k: v for k, v in item.items() if k in campos})
            for item in (resposta or [])]
