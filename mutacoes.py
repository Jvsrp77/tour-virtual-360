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

    # indice de vertice fora da faixa e o defeito classico de gerador de OBJ
    ("obj numera vertice a partir do zero", "maquete3d.py",
     '                "%d//%d" % (base_v + c + 1, k + 1) for c in cantos))',
     '                "%d//%d" % (base_v + c, k + 1) for c in cantos))',
     "TestExportarObj.test_nenhuma_face_aponta_para_vertice_que_nao_existe"),

    # sem a casca recriada, o modelo abre sem fachada
    ("obj sai sem as paredes externas", "maquete3d.py",
     "    pecas += _caixas_da_casca(geo)",
     "    pecas += []",
     "TestExportarObj.test_a_fachada_existe_no_arquivo"),

    # levar a geometria editavel embora e decisao da dona, nao do visitante
    ("visitante baixa o modelo editavel", "app.py",
     '    "api.api_embed", "maquete", "api.api_maquete",',
     '    "api.api_embed", "maquete", "api.api_maquete", "api.api_maquete_obj",',
     "TestExportarObj.test_visitante_ve_a_maquete_mas_nao_leva_o_modelo"),

    # Pular a conferencia nao derruba o caso do zip CORROMPIDO: ali a extracao
    # falha sozinha e a pasta provisoria e descartada antes de trocar nada — a
    # estrutura protege. Quem depende da conferencia e o zip VALIDO que nao e
    # backup: sem ela, ele extrai limpo e substitui os dados por qualquer coisa.
    ("restaura sem conferir a copia antes", "backup.py",
     "    ok, recado, _ = conferir_copia(origem)",
     "    ok, recado, _ = (True, '', 0)",
     "TestRestaurarBackup.test_zip_que_nao_e_backup_e_recusado"),

    # restaurar a copia errada nao pode ser caminho sem volta
    ("restaurar apaga o que existia", "backup.py",
     "        shutil.move(destino, guardado)",
     "        shutil.rmtree(destino, ignore_errors=True)",
     "TestRestaurarBackup.test_o_que_existia_fica_guardado_e_nao_apagado"),

    # zip qualquer nao e copia: restaurar apagaria os dados por nada
    ("aceita zip que nao e backup", "backup.py",
     "    if not parece:",
     "    if False:",
     "TestRestaurarBackup.test_zip_que_nao_e_backup_e_recusado"),

    # arquivo que so se descobre quebrado ao abrir deixa o corretor sem saber
    ("modelo importado entra sem conferencia", "app.py",
     "        medidas, avisos = modelo3d.conferir(texto, len(bruto))",
     "        medidas, avisos = modelo3d.medir(texto), []",
     "TestImportarModelo.test_modelo_em_centimetros_e_aceito_com_aviso"),

    # sem leitor proprio de OBJ a pagina abre vazia: o three.js embarcado nao traz
    ("pagina perde o leitor de OBJ", "static/maquete.html",
     "  function lerObj(texto, cores){",
     "  function lerObjDesativado(texto, cores){",
     "TestImportarModelo.test_a_pagina_traz_o_proprio_leitor_de_obj"),

    # escaneamento sem geometria nao pode ser gravado
    ("aceita obj sem geometria", "modelo3d.py",
     "    if not vertices or not faces:",
     "    if False:",
     "TestImportarModelo.test_arquivo_sem_geometria_e_recusado_antes_de_gravar"),

    # a tela cresce o Y para BAIXO: trocar o sinal inverte o manche, o mesmo
    # defeito do W, so que no celular
    ("manche com o eixo invertido", "static/maquete.html",
     "    let frente = -dy / raio, lado = dx / raio;",
     "    let frente = dy / raio, lado = dx / raio;",
     "TestPrimeiraPessoa.test_o_manche_anda_para_onde_o_polegar_aponta"),

    # sem zona morta, dedo pousado empurra a pessoa devagar
    ("manche sem zona morta", "static/maquete.html",
     "    if (Math.hypot(frente, lado) < 0.18) return {frente: 0, lado: 0};",
     "    if (false) return {frente: 0, lado: 0};",
     "TestPrimeiraPessoa.test_polegar_pousado_nao_faz_andar_sozinho"),

    # o defeito que o usuario achou: W andava para tras
    ("w anda para tras", "static/maquete.html",
     "    return {x: -sen * frente + cos * lado,",
     "    return {x: sen * frente + cos * lado,",
     "TestPrimeiraPessoa.test_w_anda_para_onde_a_camera_olha"),

    # teleportar para cima de um movel prende a pessoa
    ("pino teleporta sem conferir se cabe", "static/maquete.html",
     "          if (livre(x, z)){",
     "          if (true){",
     "TestPrimeiraPessoa.test_o_pino_teleporta_de_dentro_em_vez_de_sair"),

    # colisao que nunca barra deixa atravessar o imovel inteiro
    ("primeira pessoa atravessa parede", "static/maquete.html",
     "      if (x > b.x0 - RAIO_CORPO && x < b.x1 + RAIO_CORPO",
     "      if (false && x < b.x1 + RAIO_CORPO",
     "TestPrimeiraPessoa.test_a_parede_barra_o_corpo"),

    # de dentro, parede cortada deixa ver o comodo vizinho por cima
    ("visita de dentro com parede cortada", "static/maquete.html",
     '    $("corte").value = 270;',
     '    $("corte").value = $("corte").value;',
     "TestPrimeiraPessoa.test_de_dentro_as_paredes_ficam_inteiras"),

    # olho em altura diferente da do tour: deixa de ser o que a cena 360 viu
    ("olho em altura diferente do tour", "static/maquete.html",
     "  const OLHO = 1.50;",
     "  const OLHO = 1.70;",
     "TestPrimeiraPessoa.test_o_olho_fica_na_altura_da_camera_do_tour"),

    # sem o casamento por nome, o pino da maquete nao abre cena nenhuma
    ("pino da maquete perde a cena", "app.py",
     '        ponto["cena_id"] = por_nome.get(ponto.get("nome"))',
     '        ponto["cena_id"] = None',
     "TestMaquete.test_cada_ponto_aponta_para_a_cena_tirada_dali"),

    # link velho com cena apagada nao pode abrir tela preta
    ("visor usa cena pedida sem conferir", "static/viewer.html",
     "  const inicial = (pedida && existe(pedida))",
     "  const inicial = (pedida)",
     "TestLinkDireitoParaCena.test_cena_inexistente_cai_na_inicial_em_vez_de_tela_preta"),

    # perspectiva faz parede longe parecer menor: planta baixa mentiria
    ("planta baixa em perspectiva", "static/maquete.html",
     "    if (!cameraOrto) cameraOrto = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 400);",
     "    if (!cameraOrto) cameraOrto = new THREE.PerspectiveCamera(42, 1, 0.1, 400);",
     "TestMaquete.test_a_planta_baixa_usa_projecao_ortografica"),

    # o defeito de verdade: titulo com aspas fechava o atributo onclick no meio
    ("excluir volta a passar titulo no onclick", "static/imoveis.html",
     '        <button class="perigo" onclick="remover(\'${i.id}\')">Excluir</button>',
     '        <button class="perigo" onclick="remover(\'${i.id}\', ${JSON.stringify(i.titulo)})">Excluir</button>',
     "TestBotoesDoCartao.test_todo_onclick_do_cartao_e_javascript_valido"),
    # botao apagado sem explicacao e lido como quebrado — foi reportado assim
    ("ver desabilitado sem dizer o motivo", "static/imoveis.html",
     "          : 'disabled title=",
     "          : 'disabled data-x=",
     "TestBotoesDoCartao.test_o_ver_desligado_diz_por_que"),

    # agendado com console, o vigia morre no CTRL_CLOSE_EVENT: 0xC000013A
    ("vigia agendado com console", "servico.py",
     '    candidato = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")',
     "    candidato = sys.executable",
     "TestVigiaSemConsole.test_agenda_com_interpretador_sem_console"),

    # sob pythonw o sys.stdout e None: o flush estoura e o site nem atende
    ("servidor esvazia sem protecao", "servidor.py",
     "    except (AttributeError, ValueError, OSError):",
     "    except OSError:",
     "TestVigiaSemConsole.test_o_servidor_sobe_sem_console"),

    # prometer maquete onde nao ha geometria e vender o que nao existe
    ("maquete finge existir sem geometria", "app.py",
     "    if not os.path.exists(caminho):     # imovel de fotos nao tem geometria",
     "    if False:                           # imovel de fotos nao tem geometria",
     "TestMaquete.test_imovel_de_fotos_responde_que_nao_tem"),

    # exigir conta aqui esconderia do comprador a tela que ajuda a vender
    ("maquete deixa de ser publica", "app.py",
     '"api.api_embed", "maquete", "api.api_maquete",',
     '"api.api_embed",',
     "TestMaquete.test_a_maquete_e_publica_como_o_tour"),

    # o painel renomeia o imovel; a geometria foi gravada uma vez so
    ("maquete mostra nome velho do imovel", "app.py",
     '    dados["titulo"] = tour.get("titulo") or dados.get("nome", "")',
     '    dados["titulo"] = dados.get("nome", "")',
     "TestMaquete.test_o_titulo_do_imovel_manda_no_da_geometria"),

    # conferencia que nunca reprova nada nao e conferencia: meia hora de render
    # em 8k ja foi jogada fora por camera dentro da cama
    ("conferencia da planta nunca reprova", "cena_apartamento.py",
     "        if pior < 0.02:",
     "        if False:",
     "TestPlantasSinteticas.test_a_conferencia_acusa_camera_dentro_de_movel"),

    # a profundidade exata precisa falar a MESMA lingua do visualizador
    ("tracador usa outra escala de profundidade", "cena_apartamento.py",
     "        d = (1.0 / np.maximum(pequeno, 1e-3) - 0.125) / 1.542",
     "        d = (1.0 / np.maximum(pequeno, 1e-3) - 0.2) / 2.0",
     "TestPlantasSinteticas.test_a_formula_do_visor_nao_mudou_sozinha"),

    # comodo fora da casca vira parede no lugar do comodo
    ("comodo sai para fora do imovel", "plantas.py",
     '        ("Cozinha",         wx1,  wx2,  0.00, wz1,   "cozinha",   "porcelanato"),',
     '        ("Cozinha",         wx1,  wx2 + 4.0, 0.00, wz1, "cozinha", "porcelanato"),',
     "TestPlantasSinteticas.test_os_comodos_cabem_dentro_do_imovel"),

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
    # --- tirar a maquete de dentro da tela: link, imagem e tela cheia ---

    # enquadrar sem descontar o centro aponta a camera para fora do imovel:
    # o link chegaria com a promessa de mostrar a cozinha e mostraria o vazio
    ("link do comodo aponta para fora do imovel", "static/maquete.html",
     "orbita.alvo.set((z.x0 + z.x1) / 2 - im.larg / 2, 0.9,",
     "orbita.alvo.set((z.x0 + z.x1) / 2, 0.9,",
     "TestCompartilharAMaquete.test_o_link_abre_a_maquete_olhando_para_aquele_comodo"),

    ("camera entra na parede em comodo pequeno", "static/maquete.html",
     "Math.max(4, Math.max(z.x1 - z.x0, z.z1 - z.z0) * 2.6)",
     "Math.max(z.x1 - z.x0, z.z1 - z.z0) * 2.6",
     "TestCompartilharAMaquete.test_a_camera_nao_para_dentro_da_parede_de_comodo_pequeno"),

    # comodo que nao existe tem de deixar a maquete como estava, e nao cair
    # no primeiro da lista fingindo que achou
    ("comodo inventado cai no primeiro da lista", "static/maquete.html",
     ".find(q => q.nome === nome)",
     ".find(q => true)",
     "TestCompartilharAMaquete.test_comodo_inventado_no_endereco_nao_desmonta_a_vista"),

    # sem o buffer preservado o toDataURL do WebGL devolve PNG transparente:
    # o botao pareceria funcionar e o arquivo sairia vazio
    ("imagem salva sai em branco", "static/maquete.html",
     "preserveDrawingBuffer: true",
     "preserveDrawingBuffer: false",
     "TestCompartilharAMaquete.test_a_vista_pode_virar_imagem"),

    ("planta e maquete baixam com o mesmo nome", "static/maquete.html",
     '(planta ? "-planta" : "-maquete")',
     '""',
     "TestCompartilharAMaquete.test_a_planta_e_a_maquete_nao_se_sobrescrevem"),

    # nome de arquivo com acento ainda chega quebrado em anexo de e-mail
    ("acento sobrevive no nome do arquivo", "static/maquete.html",
     '.normalize("NFD")',
     '.normalize("NFC")',
     "TestCompartilharAMaquete.test_cada_imovel_baixa_com_o_proprio_nome"),

    # metragem so na lista lateral fica de fora da imagem que vai ao anuncio
    ("rotulo no chao perde a metragem", "static/maquete.html",
     "return z.m2 ? z.nome",
     "return false ? z.nome",
     "TestCompartilharAMaquete.test_o_rotulo_no_chao_diz_a_metragem"),

    ("tela cheia deixa a maquete esticada", "static/maquete.html",
     'addEventListener("fullscreenchange", () => setTimeout(redimensionar, 60));',
     'addEventListener("fullscreenchange", () => {});',
     "TestCompartilharAMaquete.test_tela_cheia_recalcula_a_camera"),
    # --- a maquete abrindo sem internet, sem 3D, e sabendo do sol ---

    # a pagina carregava o three.js duas vezes e a segunda vinha do cdnjs:
    # rede de empresa com CDN bloqueado deixava a maquete numa versao que
    # ninguem nunca exercitou
    ("three.js volta a vir da internet", "static/maquete.html",
     "<script>\n(function(){",
     '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>\n<script>\n(function(){',
     "TestBibliotecaPropria"),

    # sem o guarda, notebook sem aceleracao grafica fica com a tela preta e
    # nenhuma palavra de explicacao
    ("pagina monta sem conferir o 3D", "static/maquete.html",
     "if (!iniciar3d()) return;",
     "iniciar3d();",
     "TestSemAceleracao3D.test_a_pagina_desiste_de_montar_quando_nao_da"),

    # ha navegador que LANCA ao perguntar pelo contexto em vez de devolver
    # null; devolver true ali levaria direto ao erro que o guarda evita
    ("navegador que explode passa por bom", "static/maquete.html",
     "    }catch(e){ return false; }",
     "    }catch(e){ return true; }",
     "TestSemAceleracao3D.test_navegador_que_explode_ao_perguntar_nao_derruba_a_pagina"),

    ("recado fica fora do palco", "static/maquete.html",
     '    $("recado").hidden = false;',
     '    $("recado").hidden = true;',
     "TestSemAceleracao3D.test_o_recado_aparece_no_palco_e_nao_so_no_texto_lateral"),

    # o erro classico: a formula do livro poe o sol do meio-dia ao SUL, que
    # vale para a Europa e esta invertido no Brasil inteiro
    ("sol do meio-dia ao sul, como na Europa", "static/maquete.html",
     "        (-Math.sin(alt) * Math.sin(lat)) / baixo));",
     "        (Math.sin(alt) * Math.sin(lat)) / baixo));",
     "TestSolDoImovel.test_ao_meio_dia_no_brasil_o_sol_esta_ao_NORTE"),

    ("sol nasce a oeste", "static/maquete.html",
     "    if (H > 0) az = 360 - az;",
     "    if (H < 0) az = 360 - az;",
     "TestSolDoImovel.test_o_sol_nasce_a_leste_e_se_poe_a_oeste"),

    # janela ao sul nao pega sol direto nenhum dia do ano, visto do Brasil
    ("sol entra por tras da parede", "static/maquete.html",
     "      if (d > 80) continue;",
     "      if (d > 100) continue;",
     "TestSolDoImovel.test_janela_ao_sul_no_brasil_nao_pega_sol_nenhum_dia"),

    # orientacao que ninguem informou nao pode virar "norte por padrao"
    ("imovel sem orientacao e tratado como ao norte", "static/maquete.html",
     "    if (frente === null || frente === undefined) return null;\n    const perto = 0.2;",
     "    const perto = 0.2;",
     "TestSolDoImovel.test_sem_orientacao_a_pagina_nao_chuta"),

    ("comodo herda a janela do vizinho", "static/maquete.html",
     "    const perto = 0.36, minimo = 0.2;",
     "    const perto = 5, minimo = 0.2;",
     "TestSolDoImovel.test_cada_comodo_recebe_a_janela_da_propria_parede"),

    ("a luz da cena ignora a hora", "static/maquete.html",
     "    const alt = Math.max(s.altura, 6) * grau;",
     "    const alt = 45 * grau;",
     "TestSolDoImovel.test_a_luz_da_cena_segue_a_hora"),

    # a orientacao e publica para LER e privada para escrever: ela muda o que
    # o anuncio afirma sobre o imovel
    ("qualquer um gira o imovel alheio", "app.py",
     '"maquete", "api.api_maquete",',
     '"maquete", "api.api_maquete", "api.api_orientacao",',
     "TestOrientacaoDoImovel.test_visitante_nao_reorienta_imovel_alheio"),

    # zero e "a frente olha para o norte", que e informacao; None e "ninguem
    # disse". Confundir os dois anuncia sol em imovel que ninguem orientou
    ("frente ao norte vira nao informado", "app.py",
     "    valor = tour.get(\"frente\")\n    if valor is None:",
     "    valor = tour.get(\"frente\")\n    if not valor:",
     "TestOrientacaoDoImovel.test_a_frente_ao_norte_nao_se_confunde_com_nao_informado"),
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
