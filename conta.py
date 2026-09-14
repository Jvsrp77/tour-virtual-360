# -*- coding: utf-8 -*-
"""
Contas de imobiliaria, pela linha de comando.

Nao existe cadastro aberto no site de proposito: num produto vendido a
imobiliarias, uma tela publica de "criar conta" so serviria para um estranho
abrir conta no servidor do cliente. A primeira conta nasce no primeiro acesso a
/entrar; as demais saem daqui, na mao de quem opera o servidor.

  python conta.py listar
  python conta.py criar <usuario> "Nome da Imobiliaria"
  python conta.py senha <usuario>
"""
import os
import sys
import getpass

import usuarios

PASTA_DADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def pedir_senha():
    senha = getpass.getpass("  senha (mínimo %d caracteres): " % usuarios.MIN_SENHA)
    if senha != getpass.getpass("  repita: "):
        print("  as senhas não conferem.")
        return None
    return senha


def listar():
    contas = usuarios.listar(PASTA_DADOS)
    if not contas:
        print("  nenhuma conta ainda. A primeira é criada no primeiro acesso a /entrar.")
        return 0
    print("  %-16s %-28s %s" % ("USUÁRIO", "IMOBILIÁRIA", "CRIADA EM"))
    for c in contas:
        print("  %-16s %-28s %s" % (c["nome"], c.get("imobiliaria", ""),
                                    c.get("criado_em", "")[:10]))
    return 0


def criar(argv):
    if not argv:
        print("  uso: python conta.py criar <usuario> [\"Nome da Imobiliaria\"]")
        return 1
    nome = argv[0]
    imobiliaria = argv[1] if len(argv) > 1 else ""
    senha = pedir_senha()
    if senha is None:
        return 1
    try:
        usuarios.criar(PASTA_DADOS, nome, senha, imobiliaria)
    except usuarios.ErroUsuario as e:
        print("  %s" % e)
        return 1
    print("  conta '%s' criada. Ela começa sem imóveis." % nome)
    return 0


def senha(argv):
    if not argv:
        print("  uso: python conta.py senha <usuario>")
        return 1
    nome = argv[0]
    atual = getpass.getpass("  senha atual: ")
    nova = pedir_senha()
    if nova is None:
        return 1
    try:
        usuarios.trocar_senha(PASTA_DADOS, nome, atual, nova)
    except usuarios.ErroUsuario as e:
        print("  %s" % e)
        return 1
    print("  senha de '%s' trocada." % nome)
    return 0


def main():
    os.makedirs(PASTA_DADOS, exist_ok=True)
    comando = sys.argv[1] if len(sys.argv) > 1 else "listar"
    if comando == "listar":
        return listar()
    if comando == "criar":
        return criar(sys.argv[2:])
    if comando == "senha":
        return senha(sys.argv[2:])
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
