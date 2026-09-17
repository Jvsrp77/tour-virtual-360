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

    # no Windows o os.replace recusa a troca se alguem tiver o arquivo aberto;
    # sem a trava na LEITURA, visitantes lendo derrubavam 38 de 40 gravacoes
    ("tira a trava da leitura do tour", "app.py",
     "    with trava_do_imovel(alvo):\n        with open(caminho, \"r\", encoding=\"utf-8\") as f:\n            tour = json.load(f)",
     "    with open(caminho, \"r\", encoding=\"utf-8\") as f:\n        tour = json.load(f)",
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

    # a linha do caminho /api/ aparece duas vezes no arquivo (aqui e no cabecalho
    # de cache); a ancora leva a linha seguinte para nao ficar ambigua
    ("sessao deixa de ser exigida", "app.py",
     '    if request.path.startswith("/api/"):\n'
     '        return jsonify({"ok": False, "erro": "Faça login para continuar.",',
     "    if False:\n"
     '        return jsonify({"ok": False, "erro": "Faça login para continuar.",',
     "TestAcesso"),

    # o defeito exato que derrubou o painel inteiro: quebra de linha crua dentro
    # de uma string JavaScript, que os testes de API nao enxergavam
    ("string JS sem fechar no painel", "static/admin.html",
     "'Excluir o contato de ' + nome + '?\\n\\n'",
     "'Excluir o contato de ' + nome + '?\n\n'",
     "TestPaginas.test_javascript_das_paginas_compila"),

    # iPhone grava HEIC por padrao; sem esta checagem a costura morre minutos
    # depois com "nao consegui abrir o arquivo", culpando o arquivo
    ("heic passa batido no envio", "app.py",
     '    if len(cabeca) >= 12 and cabeca[4:8] == b"ftyp":',
     "    if False:",
     "TestFormatoDeEnvio.test_heic_e_recusado_com_o_caminho_da_solucao"),

    # sem isto o navegador guarda a lista de imoveis por conta propria: o corretor
    # cadastra e a tela continua mostrando os antigos
    ("api pode ficar em cache", "app.py",
     '        resposta.headers["Cache-Control"] = "no-store, must-revalidate"',
     "        pass",
     "TestCacheDaApi.test_api_manda_nao_guardar"),

    # o defeito que a primeira versao da medida tinha: sem exigir borda na foto,
    # parede lisa era acusada e quarto vazio saia pior que sala mobiliada — numero
    # errado dando respaldo para trocar cena boa por pior
    ("escorrido conta parede lisa", "profundidade.py",
     "    fracao = float((rampa & forte).mean())",
     "    fracao = float(rampa.mean())",
     "TestPrevisaoDeEscorrido.test_parede_lisa_nao_e_acusada"),

    # o valor exato que causava o rasgo preto: o visualizador apaga acima de
    # 1,18 e o fundo so reconstruia acima de 1,20, deixando a faixa descoberta
    ("fundo mais exigente que o visor", "fundo.py",
     "SALTO = 1.15",
     "SALTO = 1.20",
     "TestLimiaresDoVao.test_o_fundo_cobre_tudo_que_o_visualizador_apaga"),

    # o ?proximo= existe para a pessoa voltar onde estava; sem a conferencia ele
    # vira ponte para site alheio, com o endereco do corretor na barra
    ("proximo aceita destino externo", "app.py",
     'if (not caminho or not caminho.startswith("/") or caminho.startswith("//")\n'
     '            or "\\\\" in caminho or caminho in ("/entrar", "/")):',
     "if not caminho:",
     "TestVoltaDepoisDoLogin.test_destino_externo_e_recusado"),

    # o defeito que so apareceu na costura de ponta a ponta: escolher "o mais
    # nitido da janela" faz o ruido de nitidez decidir, e o espacamento angular
    # vai de 4,8 a 36 graus onde o uniforme era 18 — costura recusada por
    # deformacao. Contar quadros ou medir nitidez deles nao pega isso.
    ("video escolhe pelo pico de nitidez", "video.py",
     "        escolhido = min(aceitaveis, key=lambda k: abs(andado[k] - alvo))",
     "        escolhido = max(perto, key=lambda k: nitidez[k])",
     "TestVideo.test_video_limpo_sai_com_espacamento_uniforme"),

    # o outro lado da mesma moeda: sem o filtro relativo, o quadro do alvo entra
    # mesmo estando borrado
    ("video aceita quadro borrado", "video.py",
     "NITIDEZ_ACEITAVEL = 0.7",
     "NITIDEZ_ACEITAVEL = 0.0",
     "TestVideo.test_borrao_ainda_e_evitado_apesar_do_espacamento"),

    ("video nao avisa resolucao baixa", "video.py",
     "    if largura >= 2000:\n        return None",
     "    if True:\n        return None",
     "TestVideo.test_resolucao_baixa_avisa_e_4k_nao"),

    # a conferencia so vale se ACUSAR: se ela calar, o corretor volta a receber
    # "as fotos nao tem sobreposicao" sem saber qual foto trocar
    ("conferencia nao ve parede lisa", "stitcher.py",
     '    lisas = [i + 1 for i, f in enumerate(fotos) if f["pontos"] < TEXTURA_MINIMA]',
     "    lisas = []",
     "TestConferenciaDaCaptura.test_parede_lisa_e_apontada_pelo_numero"),

    ("diagnostico nao chega no erro", "stitcher.py",
     "    if not achados:\n        return mensagem",
     "    if True:\n        return mensagem",
     "TestConferenciaDaCaptura.test_diagnostico_entra_na_mensagem_de_erro"),

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
