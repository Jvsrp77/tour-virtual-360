# -*- coding: utf-8 -*-
"""
Verifica se os testes nao sao cegos.

  python mutacoes.py

Teste que passa em codigo quebrado e pior do que teste nenhum: da confianca sem
dar protecao. Este script quebra cada protecao de proposito — uma por vez, no
arquivo real — roda o teste que deveria pegar aquilo, e desfaz a mudanca.

Se alguma linha disser NAO ACUSOU, o teste correspondente esta decorativo.
"""
import io
import subprocess
import sys

PY = sys.executable

ERRO404 = '        return jsonify({"ok": False, "erro": "Imóvel não encontrado."}), 404'

MUT = [
    ("tira posse do DELETE de imovel", "app.py",
     "if not imovel_existe(imovel) or not pode_ver(imovel):\n" + ERRO404 + "\n    for cena in",
     "if not imovel_existe(imovel):\n" + ERRO404 + "\n    for cena in",
     "TestAcesso.test_outra_conta_NAO_apaga_o_imovel_alheio"),

    ("tira posse da API do imovel", "app.py",
     "if request.endpoint not in ROTAS_PUBLICAS and not pode_ver(g.imovel):",
     "if False:",
     "TestAcesso.test_outra_conta_nao_alcanca"),

    ("tira a trava por imovel", "app.py",
     'if request.method != "GET" and request.endpoint not in ROTAS_PESADAS:',
     "if False:",
     "TestConcorrencia"),

    ("tour publico devolve os leads", "app.py",
     'for campo in ("leads_capturados", "visitas"):',
     "for campo in ():",
     "TestAcesso.test_tour_publico_nao_vaza_contatos"),

    ("espalha foto parcial em 360", "stitcher.py",
     "    haov = min(360.0, vaov * (largura / float(altura)))",
     "    haov = 360.0",
     "TestCobertura"),

    ("ndarray vaza para o JSON", "stitcher.py",
     '        info.pop("direcao", None)',
     "        pass",
     "TestSerializavel"),

    ("sessao deixa de ser exigida", "app.py",
     '    if request.path.startswith("/api/"):',
     "    if False:",
     "TestAcesso"),

    # o defeito exato que derrubou o painel inteiro: quebra de linha crua dentro
    # de uma string JavaScript, que os testes de API nao enxergavam
    ("string JS sem fechar no painel", "static/admin.html",
     "'Excluir o contato de ' + nome + '?\\n\\n'",
     "'Excluir o contato de ' + nome + '?\n\n'",
     "TestPaginas.test_javascript_das_paginas_compila"),

    ("onclick sem funcao no painel", "static/admin.html",
     'onclick="baixarLeads()"',
     'onclick="baixarLeadsQueNaoExiste()"',
     "TestPaginas.test_handlers_do_html_tem_funcao"),
]


def roda(alvo):
    r = subprocess.run([PY, "testes.py", alvo], capture_output=True,
                       text=True, errors="ignore")
    s = (r.stdout or "") + (r.stderr or "")
    return "FAILED" in s or "ERROR" in s or r.returncode != 0


def main():
    print("  %-38s %-16s %s" % ("MUTACAO", "TESTE", "RESULTADO"))
    print("  " + "-" * 76)
    bons = ruins = 0
    for nome, arq, velho, novo, alvo in MUT:
        orig = io.open(arq, encoding="utf-8").read()
        if orig.count(velho) != 1:
            print("  %-38s %-16s ANCORA %d" % (nome, "", orig.count(velho)))
            ruins += 1
            continue
        io.open(arq, "w", encoding="utf-8", newline="").write(orig.replace(velho, novo, 1))
        try:
            falhou = roda(alvo)
        finally:
            io.open(arq, "w", encoding="utf-8", newline="").write(orig)
        curto = alvo.split(".")[-1][:16]
        if falhou:
            print("  %-38s %-16s ACUSOU" % (nome, curto))
            bons += 1
        else:
            print("  %-38s %-16s NAO ACUSOU  <<< teste cego" % (nome, curto))
            ruins += 1
    print()
    print("  %d de %d mutacoes detectadas" % (bons, bons + ruins))
    return 1 if ruins else 0


if __name__ == "__main__":
    raise SystemExit(main())
