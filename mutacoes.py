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
import os
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

    # o defeito exato que eu cometi ao escrever a confianca: tratar o retangulo
    # como centrado na camera. Quem fotografa quase nunca esta no meio do comodo,
    # e isso dava aderencia ZERO em tudo — inclusive na cena conferida com LiDAR
    ("area supoe camera no centro", "area.py",
     "        ate_u = np.where(du > 1e-6, u_mais / du,\n"
     "                         np.where(du < -1e-6, -u_menos / du, np.inf))",
     "        ate_u = np.where(np.abs(du) > 1e-6, u_mais / np.abs(du), np.inf)",
     "TestConfiancaDaArea.test_a_camera_fora_do_centro_nao_derruba_sozinha"),

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

    # calcular o teto e nao aplicar seria pior do que nao ter: daria a
    # impressao de protecao enquanto o visitante anda ate o borrao
    ("passo ignora o teto da cena", "static/andar.html",
     "    const alcance = Math.min(pedido, tetoDePasseio(pt.cena));",
     "    const alcance = pedido;",
     "TestTetoDePasseio.test_o_teto_e_mesmo_aplicado_no_passo"),

    # se o teto nao cair com escorrido ruim, a cena pior anda tanto quanto a boa
    ("teto nao cai em cena ruim", "static/andar.html",
     "  return Math.max(PASSEIO_MINIMO, PASSEIO_CHEIO * (ESCORRIDO_OTIMO / e));",
     "  return PASSEIO_CHEIO;",
     "TestTetoDePasseio.test_cena_medida_pior_anda_menos"),

    # sem o freio, 1 tentativa por segundo ainda da 86 mil por dia
    ("login aceita tentativa sem fim", "app.py",
     "    if falta > 0:",
     "    if False:",
     "TestFreioDeForcaBruta.test_erro_repetido_acaba_travando"),

    # travar e deixar entrar com a senha certa nao seria travar
    ("trava solta quem acerta depois", "app.py",
     "    falta = _espera_da_trava(origem)",
     "    falta = 0.0 if senha else _espera_da_trava(origem)",
     "TestFreioDeForcaBruta.test_travado_nao_entra_nem_com_a_senha_certa"),

    # o aviso nunca pode derrubar o cadastro do contato
    ("aviso derruba o cadastro do lead", "app.py",
     "    except Exception:   # o aviso nunca derruba o cadastro do contato",
     "    except ZeroDivisionError:   # o aviso nunca derruba o cadastro do contato",
     "TestAvisoDeLead.test_o_contato_entra_mesmo_com_o_email_quebrado"),

    # desviar o POST faria o navegador reenviar a senha que ja viajou em claro
    ("senha em claro e desviada em vez de recusada", "app.py",
     '    if request.method not in ("GET", "HEAD"):',
     "    if False:",
     "TestExigirHttps.test_envio_de_senha_em_claro_e_recusado_e_nao_desviado"),

    # se /saude for desviada, o vigia derruba o servidor de 5 em 5 segundos
    ("https derruba a checagem de saude", "app.py",
     '    if request.endpoint == "saude" or request.remote_addr in ("127.0.0.1", "::1"):',
     "    if False:",
     "TestExigirHttps.test_a_saude_continua_respondendo_em_claro"),

    # botao que derruba o site sem ninguem para repor e pior que botao nenhum
    ("recarregar age sem haver vigia", "app.py",
     "    if not ha_vigia():",
     "    if False:",
     "TestRecarregarServidor.test_sem_vigia_a_rota_se_recusa"),

    # sem a marca, o site nunca sabe que ha quem o reponha
    ("vigia deixa de marcar o filho", "servico.py",
     '    ambiente = dict(os.environ, TOUR_VIGIADO="1")',
     "    ambiente = dict(os.environ)",
     "TestRecarregarServidor.test_o_vigia_marca_o_processo_que_ele_repoe"),

    # processo mais novo que o arquivo nao tem publicacao esperando
    ("versao pendente sempre diz que sim", "app.py",
     '    return {"pendente": quando > INICIADO_EM,',
     '    return {"pendente": True,',
     "TestRecarregarServidor.test_a_versao_pendente_e_vista_pelo_horario"),

    # o robo do WhatsApp nao executa script: etiqueta injetada depois nao existe
    ("previa do link some do html servido", "app.py",
     '    html = html.replace("<head>", "<head>',
     '    html = html.replace("<NAO-EXISTE>", "<head>',
     "TestPreviaDoLink.test_as_etiquetas_estao_no_html_e_nao_no_javascript"),

    # titulo e digitado pelo corretor: sem escape ele fecha o atributo
    ("titulo do imovel entra sem escape", "app.py",
     "        '<meta property=\"og:title\" content=\"%s\">' % escape(titulo),",
     "        '<meta property=\"og:title\" content=\"%s\">' % titulo,",
     "TestPreviaDoLink.test_titulo_com_aspas_nao_quebra_a_etiqueta"),

    # caminho relativo nao resolve para o robo, que busca de fora
    ("imagem da previa fica relativa", "app.py",
     '        imagem = "%s/data/%s/scenes/%s" % (raiz, imovel_id, capa)',
     '        imagem = "/data/%s/scenes/%s" % (imovel_id, capa)',
     "TestPreviaDoLink.test_o_endereco_da_imagem_e_absoluto"),

    # botao que nao abre o WhatsApp nao serve para nada
    ("botao de enviar some do painel", "static/admin.html",
     "  <button onclick=\"enviarPorWhatsApp()\"",
     "  <button onclick=\"nada()\"",
     "TestPreviaDoLink.test_o_botao_de_enviar_chama_mesmo_a_funcao"),

    # procurar a palavra "SYSTEM" falhava no Windows em portugues, que diz
    # "SISTEMA": o estado voltava a mentir sobre o modo do agendamento
    ("modo do agendamento depende do idioma", "servico.py",
     '    if "<BootTrigger" in xml:',
     '    if "SYSTEM" in xml.upper():',
     "TestCodigoNoAr.test_o_modo_nao_depende_do_idioma_do_windows"),

    # a consulta que casava com ela mesma: veredito "no ar" sempre
    ("consulta do vigia casa com ela mesma", "servico.py",
     "\"Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' \"",
     "\"Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*' \"",
     "TestCodigoNoAr.test_a_consulta_nao_pode_casar_com_ela_mesma"),

    # redefinir senha sem a antiga pela web seria tomada de conta
    ("redefinicao de senha exposta na web", "app.py",
     "import aviso",
     "import aviso\nfrom usuarios import redefinir_senha  # noqa",
     "TestSenhaEsquecida.test_nenhuma_rota_web_redefine_senha"),
]


def _esquecer_bytecode(arq):
    """
    Apaga o .pyc do arquivo restaurado.

    Sem isto o conserto nao cola, e o modo de falhar e cruel. O Python valida o
    cache pela DATA e pelo TAMANHO do fonte. Varias mutacoes daqui trocam texto
    do mesmo comprimento — "1.15" por "1.20" — e a restauracao acontece no mesmo
    segundo. Tamanho igual, segundo igual: o Python da o cache por valido e
    segue rodando o bytecode SABOTADO, com o fonte certo no disco.

    Aconteceu de verdade: fundo.SALTO lia 1.20 com o arquivo mostrando 1.15, e o
    teste acusava um defeito que nao existia mais. Meia hora atras de um erro
    que estava no cache, nao no codigo.
    """
    pasta = os.path.join(os.path.dirname(os.path.abspath(arq)), "__pycache__")
    base = os.path.splitext(os.path.basename(arq))[0]
    if not os.path.isdir(pasta):
        return
    for nome in os.listdir(pasta):
        if nome.startswith(base + ".") and nome.endswith(".pyc"):
            try:
                os.remove(os.path.join(pasta, nome))
            except OSError:
                pass


def roda(alvo):
    r = subprocess.run([PY, "testes.py", alvo], capture_output=True,
                       text=True, errors="ignore")
    s = (r.stdout or "") + (r.stderr or "")
    return "FAILED" in s or "ERROR" in s or r.returncode != 0


def main():
    print("  %-38s %-16s %s" % ("MUTACAO", "TESTE", "RESULTADO"))
    print("  " + "-" * 76)
    bons = ruins = 0
    for nome, arq, velho, novo_txt, alvo in MUT:
        orig = io.open(arq, encoding="utf-8").read()
        # Se este script for morto no meio (fechar o terminal, cancelar a tarefa),
        # o finally la embaixo nao roda e o arquivo fica com a sabotagem gravada.
        # Aconteceu: o app.py passou a recusar HEIC nunca mais, e na rodada
        # seguinte isso aparecia so como "ANCORA 0", que se le como ancora velha.
        # Ficar calado ai e o pior caso possivel — o fonte quebrado segue para o
        # commit. Entao: se o texto original sumiu e o mutado esta no lugar dele,
        # desfaz e diz em voz alta.
        if orig.count(velho) == 0 and orig.count(novo_txt) == 1:
            orig = orig.replace(novo_txt, velho, 1)
            io.open(arq, "w", encoding="utf-8", newline="").write(orig)
            print("  %-38s %-16s FONTE ESTAVA MUTADO — desfeito" % (nome, ""))
        if orig.count(velho) != 1:
            print("  %-38s %-16s ANCORA %d" % (nome, "", orig.count(velho)))
            ruins += 1
            continue
        io.open(arq, "w", encoding="utf-8", newline="").write(orig.replace(velho, novo_txt, 1))
        try:
            falhou = roda(alvo)
        finally:
            io.open(arq, "w", encoding="utf-8", newline="").write(orig)
            _esquecer_bytecode(arq)
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
