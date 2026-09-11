# -*- coding: utf-8 -*-
"""
Contas de acesso ao painel.

O tour publicado continua aberto — e o link que o corretor manda ao cliente.
O que fica protegido e o painel: criar, editar e apagar imoveis, e ver leads
e metricas.

As senhas nunca sao guardadas em texto. O werkzeug (que ja vem com o Flask)
faz o hash com salt; aqui so se guarda o resultado.
"""
import io
import os
import json
import secrets
import threading
from datetime import datetime

from werkzeug.security import generate_password_hash, check_password_hash

_TRAVA = threading.Lock()

MIN_SENHA = 8


class ErroUsuario(Exception):
    pass


def _arquivo(pasta_dados):
    return os.path.join(pasta_dados, "usuarios.json")


def _ler(pasta_dados):
    caminho = _arquivo(pasta_dados)
    if not os.path.exists(caminho):
        return {"usuarios": []}
    with io.open(caminho, encoding="utf-8") as f:
        return json.load(f)


def _gravar(pasta_dados, dados):
    caminho = _arquivo(pasta_dados)
    temporario = caminho + ".tmp"
    with io.open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(temporario, caminho)


def ha_usuarios(pasta_dados):
    return bool(_ler(pasta_dados)["usuarios"])


def listar(pasta_dados):
    return [{"nome": u["nome"], "criado_em": u.get("criado_em", "")}
            for u in _ler(pasta_dados)["usuarios"]]


def criar(pasta_dados, nome, senha):
    nome = (nome or "").strip().lower()
    if not nome:
        raise ErroUsuario("Informe um nome de usuário.")
    if len(senha or "") < MIN_SENHA:
        raise ErroUsuario("A senha precisa ter pelo menos %d caracteres." % MIN_SENHA)

    with _TRAVA:
        dados = _ler(pasta_dados)
        if any(u["nome"] == nome for u in dados["usuarios"]):
            raise ErroUsuario("Já existe um usuário com esse nome.")
        dados["usuarios"].append({
            "nome": nome,
            "senha": generate_password_hash(senha),
            "criado_em": datetime.now().isoformat(timespec="seconds"),
        })
        _gravar(pasta_dados, dados)
    return nome


def verificar(pasta_dados, nome, senha):
    nome = (nome or "").strip().lower()
    for u in _ler(pasta_dados)["usuarios"]:
        if u["nome"] == nome:
            return check_password_hash(u["senha"], senha or "")
    # gasta o mesmo tempo de um hash real, para nao entregar quais nomes existem
    check_password_hash(generate_password_hash("descartavel"), senha or "")
    return False


def trocar_senha(pasta_dados, nome, senha_atual, senha_nova):
    if not verificar(pasta_dados, nome, senha_atual):
        raise ErroUsuario("Senha atual incorreta.")
    if len(senha_nova or "") < MIN_SENHA:
        raise ErroUsuario("A senha nova precisa ter pelo menos %d caracteres." % MIN_SENHA)
    with _TRAVA:
        dados = _ler(pasta_dados)
        for u in dados["usuarios"]:
            if u["nome"] == (nome or "").strip().lower():
                u["senha"] = generate_password_hash(senha_nova)
        _gravar(pasta_dados, dados)


def segredo(pasta_dados):
    """
    Chave que assina o cookie de sessao. Fica em disco para que reiniciar o
    servidor nao derrube todo mundo — se fosse sorteada a cada subida, cada
    reinicio invalidaria as sessoes abertas.
    """
    caminho = os.path.join(pasta_dados, "segredo.txt")
    if os.path.exists(caminho):
        with io.open(caminho, encoding="utf-8") as f:
            valor = f.read().strip()
            if len(valor) >= 32:
                return valor
    valor = secrets.token_hex(32)
    with io.open(caminho, "w", encoding="utf-8") as f:
        f.write(valor)
    return valor
