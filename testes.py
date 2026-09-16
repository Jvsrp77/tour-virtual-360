# -*- coding: utf-8 -*-
"""
Testes automatizados.

  python testes.py

Cada teste aqui existe porque o defeito correspondente ACONTECEU de verdade
durante o desenvolvimento, e so foi pego por verificacao manual. O objetivo nao
e cobrir cada linha: e impedir que estes voltem sem ninguem notar.

Roda numa pasta de dados descartavel (TOUR_DADOS), nunca sobre os dados reais.
Nao precisa de servidor: usa o cliente de teste do proprio Flask.
"""
import io
import os
import json
import hashlib
import tempfile
import re
import shutil
import subprocess
import threading
import unittest
import warnings

# o cliente de teste do Flask deixa o arquivo estatico aberto ate o coletor
# passar; o aviso nao indica defeito e so atrapalha a leitura da saida
warnings.simplefilter("ignore", ResourceWarning)

# precisa vir antes de importar app: e no import que ele resolve a pasta
_TEMP = tempfile.mkdtemp(prefix="tour-testes-")
os.environ["TOUR_DADOS"] = os.path.join(_TEMP, "data")
os.environ["TOUR_BACKUPS"] = os.path.join(_TEMP, "backups")
os.makedirs(os.environ["TOUR_DADOS"], exist_ok=True)

import app as aplicacao           # noqa: E402
import usuarios                   # noqa: E402
import backup                     # noqa: E402
import stitcher                   # noqa: E402
import video                      # noqa: E402
import nivelamento                # noqa: E402


def _imagem(largura, altura):
    """Uma imagem de teste com textura suficiente para o detector achar linhas."""
    import numpy as np
    import cv2
    img = np.full((altura, largura, 3), 200, np.uint8)
    for x in range(0, largura, max(8, largura // 40)):
        img[:, x:x + 3] = 40                       # verticais
    for y in range(0, altura, max(8, altura // 20)):
        img[y:y + 2, :] = 90
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    return buf.tobytes()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        aplicacao.app.config["TESTING"] = True
        cls.app = aplicacao.app

    def conta(self, nome, senha="senhadeteste1", imobiliaria=""):
        try:
            usuarios.criar(aplicacao.PASTA_DADOS, nome, senha, imobiliaria or nome)
        except usuarios.ErroUsuario:
            pass
        c = self.app.test_client()
        r = c.post("/api/entrar", json={"usuario": nome, "senha": senha})
        self.assertTrue(r.get_json()["ok"], "login de %s falhou" % nome)
        return c

    def imovel(self, cliente, titulo="Imóvel"):
        r = cliente.post("/api/imoveis", json={"titulo": titulo})
        return r.get_json()["id"]


class TestAcesso(Base):
    """
    A matriz que pegou o furo mais grave: a conta B apagava o imovel da conta A.

    DELETE /api/imoveis/<id> esta registrada no app, nao no Blueprint, e escapava
    da checagem de posse do before_request. Sem este teste, uma refatoracao
    reabre isso em silencio.
    """

    def setUp(self):
        self.dona = self.conta("dona", imobiliaria="Imobiliária Dona")
        self.outra = self.conta("outra", imobiliaria="Imobiliária Outra")
        self.visitante = self.app.test_client()
        self.iid = self.imovel(self.dona, "Casa da dona")

    def test_publico_abre_o_tour(self):
        for rota in ("/tour/%s" % self.iid, "/andar/%s" % self.iid,
                     "/api/imoveis/%s/tour" % self.iid, "/saude"):
            self.assertEqual(self.visitante.get(rota).status_code, 200, rota)

    def test_publico_nao_abre_o_painel(self):
        self.assertEqual(self.visitante.get("/imoveis").status_code, 302)
        self.assertEqual(self.visitante.get("/painel/%s" % self.iid).status_code, 302)

    def test_publico_nao_le_a_api(self):
        for rota in ("/api/imoveis", "/api/imoveis/%s/leads" % self.iid,
                     "/api/imoveis/%s/metricas" % self.iid,
                     "/api/imoveis/%s/exportar" % self.iid):
            self.assertEqual(self.visitante.get(rota).status_code, 401, rota)

    def test_publico_nao_escreve(self):
        self.assertEqual(self.visitante.post("/api/imoveis", json={"titulo": "x"}).status_code, 401)
        self.assertEqual(self.visitante.delete("/api/imoveis/%s" % self.iid).status_code, 401)

    def test_dona_faz_tudo_no_proprio(self):
        for rota in ("/imoveis", "/painel/%s" % self.iid,
                     "/api/imoveis/%s/leads" % self.iid,
                     "/api/imoveis/%s/metricas" % self.iid,
                     "/api/imoveis/%s/exportar" % self.iid):
            self.assertEqual(self.dona.get(rota).status_code, 200, rota)

    def test_outra_conta_nao_alcanca(self):
        self.assertEqual(self.outra.get("/painel/%s" % self.iid).status_code, 302)
        for rota in ("/api/imoveis/%s/leads" % self.iid,
                     "/api/imoveis/%s/exportar" % self.iid):
            self.assertEqual(self.outra.get(rota).status_code, 404, rota)

    def test_outra_conta_NAO_apaga_o_imovel_alheio(self):
        self.assertEqual(self.outra.delete("/api/imoveis/%s" % self.iid).status_code, 404)
        self.assertTrue(aplicacao.imovel_existe(self.iid), "o imóvel foi apagado!")

    def test_lista_so_mostra_os_proprios(self):
        titulos = [i["titulo"] for i in self.outra.get("/api/imoveis").get_json()["imoveis"]]
        self.assertNotIn("Casa da dona", titulos)

    def test_tour_publico_nao_vaza_contatos(self):
        self.visitante.post("/api/imoveis/%s/leads" % self.iid,
                            json={"nome": "Fulano", "telefone": "9999"})
        corpo = self.visitante.get("/api/imoveis/%s/tour" % self.iid).get_data(as_text=True)
        self.assertNotIn("Fulano", corpo)
        self.assertNotIn("leads_capturados", corpo)
        # mas a dona ve
        leads = self.dona.get("/api/imoveis/%s/leads" % self.iid).get_json()["leads"]
        self.assertEqual(leads[0]["nome"], "Fulano")


class TestPaginas(unittest.TestCase):
    """
    O JavaScript das paginas nao tinha teste nenhum, e isso cobrou o preco: um
    \n\n virou quebra de linha crua dentro de uma string, a string ficou sem
    fechar, e o painel INTEIRO parou de funcionar. Os 24 testes passaram, porque
    exercitam a API e nao a pagina. So apareceu porque alguem foi abrir a tela.

    Aqui o proprio Node conferre a sintaxe. Escrever um verificador em Python
    tropecaria na primeira expressao regular com aspas dentro — e o painel tem
    uma: /[&<>"']/g.
    """

    PADRAO = re.compile(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", re.S | re.I)
    HANDLER = re.compile(r'on(?:click|change|input|submit)="\s*([A-Za-z_$][\w$]*)\s*\(')
    DEFINE = re.compile(r'(?:function\s+([A-Za-z_$][\w$]*)'
                        r'|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=)')

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node") or shutil.which("nodejs")
        cls.paginas = sorted(f for f in os.listdir("static") if f.endswith(".html"))

    def _blocos(self, nome):
        with io.open(os.path.join("static", nome), encoding="utf-8") as f:
            return self.PADRAO.findall(f.read())

    def test_javascript_das_paginas_compila(self):
        if not self.node:
            self.skipTest("node não encontrado: a sintaxe do JavaScript não foi conferida")
        self.assertTrue(self.paginas, "nenhuma página em static/")
        for nome in self.paginas:
            for i, bloco in enumerate(self._blocos(nome)):
                caminho = os.path.join(_TEMP, "%s-%d.mjs" % (nome.replace(".", "_"), i))
                with io.open(caminho, "w", encoding="utf-8", newline="") as f:
                    f.write(bloco)
                r = subprocess.run([self.node, "--check", caminho],
                                   capture_output=True, text=True, errors="ignore")
                self.assertEqual(r.returncode, 0,
                                 "%s, bloco %d:\n%s" % (nome, i, (r.stderr or "")[:600]))

    def test_handlers_do_html_tem_funcao(self):
        """onclick apontando para funcao que nao existe so aparece ao clicar."""
        for nome in self.paginas:
            with io.open(os.path.join("static", nome), encoding="utf-8") as f:
                html = f.read()
            js = " ".join(self.PADRAO.findall(html))
            definidas = {a or b for a, b in self.DEFINE.findall(js)}
            faltando = sorted(h for h in set(self.HANDLER.findall(html))
                              if h not in definidas)
            self.assertEqual(faltando, [], "%s chama função inexistente: %s"
                             % (nome, faltando))


class TestLeads(Base):
    """
    O contato precisa SAIR do arquivo: sem exportar, sem marcar atendido e sem
    excluir, o sistema perde para uma planilha — e a exclusao e exigencia da
    LGPD, nao conveniencia.
    """

    def setUp(self):
        self.dona = self.conta("leads", imobiliaria="Imobiliária Leads")
        self.iid = self.imovel(self.dona, "Com contatos")
        self.visitante = self.app.test_client()
        self.visitante.post("/api/imoveis/%s/leads" % self.iid,
                            json={"nome": "Maria", "telefone": "(11) 98765-4321",
                                  "email": "maria@exemplo.com",
                                  "consentimento": "Autorizo o contato."})
        self.lead = self.dona.get("/api/imoveis/%s/leads" % self.iid).get_json()["leads"][0]

    def test_guarda_o_consentimento_e_nasce_pendente(self):
        self.assertTrue(self.lead["id"])
        self.assertFalse(self.lead["atendido"])
        self.assertIn("Autorizo", self.lead["consentimento"])

    def test_marcar_atendido_e_reabrir(self):
        rota = "/api/imoveis/%s/leads/%s" % (self.iid, self.lead["id"])
        self.assertTrue(self.dona.put(rota, json={"atendido": True}).get_json()["lead"]["atendido"])
        self.assertFalse(self.dona.put(rota, json={"atendido": False}).get_json()["lead"]["atendido"])

    def test_excluir_apaga_de_verdade(self):
        rota = "/api/imoveis/%s/leads/%s" % (self.iid, self.lead["id"])
        self.assertEqual(self.dona.delete(rota).status_code, 200)
        self.assertEqual(self.dona.get("/api/imoveis/%s/leads" % self.iid)
                         .get_json()["leads"], [])

    def test_csv_abre_no_excel_em_portugues(self):
        r = self.dona.get("/api/imoveis/%s/leads.csv" % self.iid)
        self.assertEqual(r.status_code, 200)
        bruto = r.get_data()
        self.assertTrue(bruto.startswith(bytes([0xEF, 0xBB, 0xBF])),
                        "sem BOM o Excel estraga acento")
        texto = bruto.decode("utf-8-sig")
        self.assertIn(";", texto.splitlines()[0], "vírgula joga tudo numa coluna só")
        self.assertIn("Maria", texto)
        self.assertIn("attachment", r.headers.get("Content-Disposition", ""))

    def test_contatos_so_para_a_dona(self):
        outra = self.conta("leads_outra")
        for cliente, esperado in ((self.visitante, 401), (outra, 404)):
            self.assertEqual(cliente.get("/api/imoveis/%s/leads.csv" % self.iid).status_code,
                             esperado)
            self.assertEqual(
                cliente.delete("/api/imoveis/%s/leads/%s" % (self.iid, self.lead["id"]))
                .status_code, esperado)


class TestConcorrencia(Base):
    """
    Dois defeitos diferentes, ambos vistos de verdade:

    1. 40 escritas simultaneas perdiam 27 antes das travas por imovel existirem:
       duas requisicoes liam o mesmo tour.json e a segunda apagava a primeira.
    2. No Windows, o os.replace da gravacao atomica falha com WinError 5 se
       alguem estiver LENDO o arquivo naquele instante — e leitura nao pega
       trava, de proposito. Por isso o teste roda visitantes lendo ao mesmo
       tempo: sem eles o defeito so aparecia em 1 execucao a cada 3.
    """

    def test_escritas_simultaneas_nao_se_perdem(self):
        dona = self.conta("concorrencia")
        iid = self.imovel(dona, "Concorrência")
        quantas = 40

        # visitantes lendo o tour enquanto os contatos chegam: e o handle aberto
        # deles que faz o os.replace falhar no Windows
        parar = threading.Event()

        def lendo():
            c = self.app.test_client()
            while not parar.is_set():
                c.get("/api/imoveis/%s/tour" % iid)

        leitores = [threading.Thread(target=lendo, daemon=True) for _ in range(4)]
        for t in leitores:
            t.start()
        self.addCleanup(parar.set)

        codigos, falhas = [], []

        def envia(n):
            try:
                c = self.app.test_client()
                r = c.post("/api/imoveis/%s/leads" % iid,
                           json={"nome": "visitante %d" % n, "telefone": str(n)})
                codigos.append(r.status_code)
            except Exception as e:
                falhas.append("%s: %s" % (type(e).__name__, e))

        threads = [threading.Thread(target=envia, args=(n,)) for n in range(quantas)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        parar.set()
        leads = dona.get("/api/imoveis/%s/leads" % iid).get_json()["leads"]
        if len(leads) != quantas:
            import collections
            nomes = {l["nome"] for l in leads}
            print("\n    codigos HTTP:", dict(collections.Counter(codigos)))
            print("    excecoes:", falhas or "nenhuma")
            print("    faltando:", sorted(n for n in
                  ("visitante %d" % i for i in range(quantas)) if n not in nomes))
        self.assertEqual(len(leads), quantas,
                         "%d de %d contatos se perderam" % (quantas - len(leads), quantas))


class TestCobertura(Base):
    """
    Toda imagem importada recebia haov=360, mesmo sem ser equirretangular: um
    panorama 3:1 do celular era espalhado pela volta inteira e esticava 1,8 vez.
    """

    def test_2x1_vira_360_completo(self):
        haov, vaov = (360.0, 180.0) if stitcher.eh_equirretangular(4000, 2000) else (0, 0)
        self.assertEqual((haov, vaov), (360.0, 180.0))

    def test_3x1_nao_e_espalhado_pela_volta(self):
        self.assertFalse(stitcher.eh_equirretangular(3000, 1000))
        haov, _ = stitcher.cobertura_parcial(3000, 1000)
        self.assertLess(haov, 260.0, "3:1 não pode virar volta inteira")
        self.assertGreater(haov, 120.0)

    def test_upload_parcial_avisa_e_nao_finge_360(self):
        dona = self.conta("cobertura")
        iid = self.imovel(dona, "Cobertura")
        r = dona.post("/api/imoveis/%s/cenas/importar360" % iid,
                      data={"fotos": (io.BytesIO(_imagem(3000, 1000)), "p.jpg"),
                            "nome": "Parcial"},
                      content_type="multipart/form-data")
        j = r.get_json()
        self.assertTrue(j["ok"], j)
        cena = j["cenas"][0]
        self.assertFalse(cena["panorama_completo"])
        self.assertLess(cena["haov"], 300.0)
        self.assertTrue(j["avisos"], "deveria avisar que não é 360 completo")


class TestForaDoContexto(Base):
    """
    montar_cena lia `g.imovel` para gerar a miniatura, e quebrava na thread da
    fila com "Working outside of application context" aos 92% da costura.
    """

    def test_montar_cena_funciona_em_thread_sem_flask(self):
        dona = self.conta("thread")
        iid = self.imovel(dona, "Thread")
        arquivo = "cena_teste.jpg"
        with io.open(os.path.join(aplicacao.pasta_cenas(iid), arquivo), "wb") as f:
            f.write(_imagem(1024, 512))

        resultado = {}

        def trabalho():
            try:
                resultado["cena"] = aplicacao.montar_cena(
                    "Teste", arquivo, 1024, 512, "equirretangular", imovel_id=iid)
            except Exception as e:
                resultado["erro"] = "%s: %s" % (type(e).__name__, e)

        t = threading.Thread(target=trabalho)
        t.start()
        t.join()
        self.assertNotIn("erro", resultado, resultado.get("erro"))
        self.assertTrue(resultado["cena"]["miniatura"])
        self.assertTrue(resultado["cena"]["esboco"])


class TestSerializavel(Base):
    """
    nivelamento.medir devolvia a direcao de prumo como ndarray, e o json.dump do
    tour estourava com "Object of type ndarray is not JSON serializable" depois
    de todo o trabalho pesado ja ter sido feito.
    """

    def test_nivelar_devolve_so_o_que_vai_para_json(self):
        import numpy as np
        import cv2
        dados = np.frombuffer(_imagem(1024, 512), np.uint8)
        img = cv2.imdecode(dados, cv2.IMREAD_COLOR)
        _, info = stitcher._nivelar(img)
        self.assertNotIn("direcao", info)
        json.dumps(info)          # estoura se algum ndarray tiver sobrado


class TestBackup(Base):
    """Backup que nunca foi restaurado e esperanca, nao copia de seguranca."""

    def _impressao(self, base):
        h = {}
        for raiz, pastas, arquivos in os.walk(base):
            pastas[:] = [p for p in pastas if p != "uploads"]
            for nome in arquivos:
                c = os.path.join(raiz, nome)
                chave = os.path.relpath(c, base).replace(os.sep, "/")
                with io.open(c, "rb") as f:
                    h[chave] = hashlib.sha256(f.read()).hexdigest()
        return h

    def test_restaura_identico_ao_original(self):
        dona = self.conta("backup")
        self.imovel(dona, "Para copiar")

        antes = self._impressao(aplicacao.PASTA_DADOS)
        self.assertEqual(backup.criar(silencioso=True), 0)
        copias = sorted(f for f in os.listdir(backup.PASTA_BACKUPS) if f.endswith(".zip"))
        self.assertTrue(copias, "nenhuma cópia foi criada")

        guardado = aplicacao.PASTA_DADOS + "-guardado"
        shutil.move(aplicacao.PASTA_DADOS, guardado)
        try:
            import zipfile
            os.makedirs(aplicacao.PASTA_DADOS, exist_ok=True)
            with zipfile.ZipFile(os.path.join(backup.PASTA_BACKUPS, copias[-1])) as z:
                for interno in z.namelist():
                    if interno != "_backup.json":
                        z.extract(interno, aplicacao.PASTA_DADOS)
            depois = self._impressao(aplicacao.PASTA_DADOS)
            self.assertEqual(sorted(antes), sorted(depois), "faltou ou sobrou arquivo")
            for chave in antes:
                self.assertEqual(antes[chave], depois[chave], "conteúdo diferente: %s" % chave)
        finally:
            shutil.rmtree(aplicacao.PASTA_DADOS, ignore_errors=True)
            shutil.move(guardado, aplicacao.PASTA_DADOS)


class TestContas(Base):
    def test_senha_nao_fica_em_texto(self):
        usuarios.criar(aplicacao.PASTA_DADOS, "segredo_teste", "minhasenha123", "X")
        with io.open(os.path.join(aplicacao.PASTA_DADOS, "usuarios.json"),
                     encoding="utf-8") as f:
            bruto = f.read()
        self.assertNotIn("minhasenha123", bruto)

    def test_senha_curta_e_recusada(self):
        with self.assertRaises(usuarios.ErroUsuario):
            usuarios.criar(aplicacao.PASTA_DADOS, "curta_teste", "123", "X")

    def test_nao_ha_cadastro_aberto(self):
        """Com contas ja existentes, /api/entrar so autentica — nunca cria."""
        self.conta("primeira")
        c = self.app.test_client()
        r = c.post("/api/entrar", json={"usuario": "intruso", "senha": "senhaqualquer1"})
        self.assertEqual(r.status_code, 401)
        self.assertIsNone(usuarios.obter(aplicacao.PASTA_DADOS, "intruso"))


class TestFormatoDeEnvio(Base):
    """
    iPhone grava em HEIC por padrao, e o sistema nao abre HEIC.

    A rota trocava a extensao para .jpg e seguia; a costura morria minutos depois
    com "Não consegui abrir o arquivo", que culpa o arquivo e nao diz o que fazer.
    Quem tem iPhone batia nisso no primeiro uso, e a captura pelo celular e
    justamente o caminho que o produto recomenda.
    """

    def _heic(self):
        """Cabecalho ISO-BMFF com marca heic, como o iPhone grava."""
        return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64

    def _mov(self):
        return b"\x00\x00\x00\x14ftypqt  \x00\x00\x02\x00qt  " + b"\x00" * 64

    def test_heic_e_recusado_com_o_caminho_da_solucao(self):
        caminho = os.path.join(_TEMP, "foto.jpg")       # ja renomeado, como a rota faz
        with io.open(caminho, "wb") as f:
            f.write(self._heic())
        recado = aplicacao.formato_recusado(caminho, "IMG_9629.HEIC")
        self.assertIsNotNone(recado, "HEIC passou batido")
        self.assertIn("HEIC", recado)
        self.assertIn("Mais Compatível", recado, "não diz como resolver no iPhone")

    def test_video_no_campo_de_fotos_e_recusado(self):
        caminho = os.path.join(_TEMP, "video.jpg")
        with io.open(caminho, "wb") as f:
            f.write(self._mov())
        recado = aplicacao.formato_recusado(caminho, "IMG_9629.MOV")
        self.assertIsNotNone(recado)
        self.assertIn("vídeo", recado)

    def test_jpeg_de_verdade_passa(self):
        caminho = os.path.join(_TEMP, "boa.jpg")
        with io.open(caminho, "wb") as f:
            f.write(_imagem(400, 300))
        self.assertIsNone(aplicacao.formato_recusado(caminho, "boa.jpg"))

    def test_a_rota_recusa_antes_de_enfileirar(self):
        """Falhar na hora é o ponto: minutos de costura para nada seria pior."""
        dona = self.conta("heic")
        iid = self.imovel(dona, "Casa HEIC")
        r = dona.post("/api/imoveis/%s/cenas/costurar" % iid,
                      data={"fotos": [(io.BytesIO(self._heic()), "IMG_1.HEIC"),
                                      (io.BytesIO(self._heic()), "IMG_2.HEIC")],
                            "nome": "Quarto"},
                      content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertIn("HEIC", r.get_json()["erro"])


class TestQuandoOferecerCaminhada(unittest.TestCase):
    """
    O visitante so recebe "Andar aqui" onde caminhar fica bom.

    Com UM ponto de captura, andar e extrapolar de um unico ponto de vista: 11%
    da cena fica numa rampa de profundidade que estica a textura na borda dos
    moveis. Nao ha ajuste que conserte — filtro guiado e bilateral cruzado foram
    medidos e falharam, porque o modelo nao estima a silhueta, entrega uma bolha.

    Entao a regra e de produto, nao de software: quem capturou um ponto entrega o
    tour 360, que gira sem distorcao nenhuma. O botao aparece a partir de dois
    pontos posicionados na planta, que e quando existe para onde pular.
    """

    def _regra(self):
        with io.open(os.path.join("static", "viewer.html"), encoding="utf-8") as f:
            return f.read()

    def test_o_botao_exige_dois_pontos_na_planta(self):
        html = self._regra()
        self.assertIn("pontosNavegaveis", html)
        self.assertIn("pontosNavegaveis() >= 2", html,
                      "o botão de caminhar não está exigindo 2 pontos")

    def test_conta_so_cena_com_profundidade_E_posicao(self):
        """
        Profundidade sem posicao na planta nao serve: sao ilhas soltas, sem
        setas entre elas, e o visitante cai de novo no caminhar extrapolado.
        """
        html = self._regra()
        trecho = html[html.index("function pontosNavegaveis"):]
        trecho = trecho[:trecho.index("}")]
        self.assertIn("c.profundidade", trecho)
        self.assertIn("c.posicao", trecho)

    def test_o_painel_explica_a_ausencia(self):
        """Sem explicação, o corretor gera a profundidade e acha que quebrou."""
        with io.open(os.path.join("static", "admin.html"), encoding="utf-8") as f:
            painel = f.read()
        self.assertIn("ainda não vê", painel)
        self.assertIn("posição na planta", painel)


class TestLimiaresDoVao(unittest.TestCase):
    """
    Dois arquivos precisam concordar sobre o que e "degrau de profundidade", e o
    defeito de discordarem e invisivel ate alguem caminhar.

    O visualizador APAGA o triangulo cujo degrau passa de SALTO_MAX; a camada de
    fundo so RECONSTROI o que passa de SALTO. Se o fundo for mais exigente, a
    faixa entre os dois some sem ter nada atras, e o visitante ve rasgo preto.
    Foi o que aconteceu: andar.html em 1,18 e fundo.py em 1,20 deixavam a faixa
    de 18% a 20% descoberta, com a camada gerada e tudo.

    Nao da para compartilhar a constante entre Python e JavaScript, entao o teste
    le as duas do arquivo e compara.
    """

    def _salto_max_do_visualizador(self):
        with io.open(os.path.join("static", "andar.html"), encoding="utf-8") as f:
            m = re.search(r"const\s+SALTO_MAX\s*=\s*([0-9.]+)", f.read())
        self.assertIsNotNone(m, "não achei SALTO_MAX no andar.html")
        return 1.0 + float(m.group(1))

    def test_o_fundo_cobre_tudo_que_o_visualizador_apaga(self):
        import fundo
        apaga = self._salto_max_do_visualizador()
        self.assertLessEqual(
            fundo.SALTO, apaga,
            "fundo.SALTO=%.3f é mais exigente que o visualizador (%.3f): a faixa "
            "entre os dois vira rasgo preto ao caminhar" % (fundo.SALTO, apaga))

    def test_a_margem_nao_e_exagerada(self):
        """
        Margem demais tambem custa: tudo que entra na mascara vira conteudo
        inventado por IA, e o anuncio fica mais gerado do que precisa.
        """
        import fundo
        self.assertGreater(fundo.SALTO, 1.05,
                           "margem larga demais: reconstrói imagem à toa")


class TestAtalhoDeEdicao(Base):
    """
    O tour tem um atalho de volta para o painel, pedido por quem edita.

    O risco e a pagina ser PUBLICA: o atalho nao pode aparecer para o cliente da
    imobiliaria nem para corretor de outra conta. Quem decide isso e /api/imoveis,
    que exige sessao e devolve apenas os imoveis da propria conta — entao o teste
    guarda justamente esse contrato, que e do que o botao depende.
    """

    def setUp(self):
        self.dona = self.conta("atalhodona")
        self.outra = self.conta("atalhooutra")
        self.visitante = self.app.test_client()
        self.iid = self.imovel(self.dona, "Casa com atalho")

    def _ids(self, cliente):
        r = cliente.get("/api/imoveis")
        if r.status_code != 200:
            return None
        return [i["id"] for i in r.get_json()["imoveis"]]

    def test_dona_reconhece_o_proprio_imovel(self):
        self.assertIn(self.iid, self._ids(self.dona))

    def test_visitante_nao_recebe_a_lista(self):
        """Sem 401 aqui, o botao apareceria para o cliente da imobiliária."""
        self.assertEqual(self.visitante.get("/api/imoveis").status_code, 401)
        self.assertIsNone(self._ids(self.visitante))

    def test_outra_imobiliaria_nao_ve_o_id(self):
        self.assertNotIn(self.iid, self._ids(self.outra))

    def test_paginas_publicas_nao_trazem_o_painel_pronto(self):
        """
        O botao nasce escondido e so o JavaScript revela. Se o HTML servido ja
        viesse com ele visivel, o visitante o veria antes de qualquer checagem.
        """
        for pagina in ("viewer.html", "andar.html"):
            with io.open(os.path.join("static", pagina), encoding="utf-8") as f:
                html = f.read()
            self.assertIn('id="btEditar"', html, pagina)
            trecho = html[html.index('id="btEditar"') - 200:
                          html.index('id="btEditar"') + 260]
            self.assertIn("display:none", trecho,
                          "%s: o botão de editar não nasce escondido" % pagina)


class TestVoltaDepoisDoLogin(Base):
    """
    Abrir o link do painel sem sessao mandava para a lista de imoveis, e parecia
    que "o login nao pegou" — a queixa real do usuario. Agora o destino viaja no
    ?proximo=.

    E o perigo que isso cria: destino vindo da URL, se aceito sem conferir,
    transforma a tela de login numa ponte para site alheio, exibindo o endereco
    do proprio corretor na barra. Por isso so caminho local passa.
    """

    def setUp(self):
        self.dona = self.conta("voltar")
        self.iid = self.imovel(self.dona, "Casa")
        self.visitante = self.app.test_client()

    def test_painel_sem_sessao_guarda_o_destino(self):
        r = self.visitante.get("/painel/%s" % self.iid)
        self.assertEqual(r.status_code, 302)
        destino = r.headers["Location"]
        self.assertIn("/entrar", destino)
        self.assertIn("proximo=", destino)
        self.assertIn(self.iid, destino)

    def test_api_sem_sessao_responde_json_e_nao_desvia(self):
        """O painel precisa do 401 para avisar; desvio em XHR passaria mudo."""
        r = self.visitante.get("/api/imoveis/%s/leads" % self.iid)
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.get_json()["login"])

    def test_destino_externo_e_recusado(self):
        for ruim in ("//evil.com/x", "http://evil.com", "/\\evil.com",
                     "https://evil.com/a", "\\\\evil.com"):
            self.assertEqual(aplicacao._proximo_para(ruim), "",
                             "aceitou destino externo: %r" % ruim)

    def test_destino_local_e_aceito_e_escapado(self):
        saida = aplicacao._proximo_para("/painel/abc123")
        self.assertEqual(saida, "?proximo=/painel/abc123")
        # a barra continua barra; o resto que precisar de escape recebe escape
        self.assertIn("%20", aplicacao._proximo_para("/painel/a b"))

    def test_entrar_e_raiz_nao_viram_destino(self):
        self.assertEqual(aplicacao._proximo_para("/entrar"), "")
        self.assertEqual(aplicacao._proximo_para("/"), "")


class TestVideo(unittest.TestCase):
    """
    O video existe para tirar do corretor a chance de errar o passo do giro.
    Se ele escolher quadro tremido, ou espacar por tempo em vez de por giro,
    troca um jeito de errar por outro.
    """

    def _gravar(self, posicoes, tremidos=(), largura=640, altura=400):
        """Video de uma camera deslizando por um cenario texturado, em `posicoes`."""
        import numpy as np
        import cv2
        rnd = np.random.RandomState(3)
        fundo = rnd.randint(0, 255, (altura, 2400, 3)).astype("uint8")
        fundo = np.repeat(np.repeat(fundo[::8, ::8], 8, 0), 8, 1)[:altura, :2400]

        pasta = tempfile.mkdtemp(dir=_TEMP)
        caminho = os.path.join(pasta, "giro.mp4")
        vw = cv2.VideoWriter(caminho, cv2.VideoWriter_fourcc(*"mp4v"),
                             30.0, (largura, altura))
        self.assertTrue(vw.isOpened(), "VideoWriter nao abriu neste sistema")
        for i, x in enumerate(posicoes):
            q = fundo[:, int(x):int(x) + largura].copy()
            if i in tremidos:
                q = cv2.GaussianBlur(q, (0, 0), sigmaX=6)
            vw.write(q)
        vw.release()
        return caminho, pasta

    def _nitidez(self, caminho):
        import numpy as np
        import cv2
        img = cv2.imdecode(np.fromfile(caminho, dtype="uint8"), cv2.IMREAD_GRAYSCALE)
        return float(cv2.Laplacian(img, cv2.CV_64F).var())

    def test_quadros_tremidos_sao_descartados(self):
        import numpy as np
        pos = np.linspace(0, 2400 - 640 - 1, 120)
        caminho, pasta = self._gravar(pos, tremidos=set(range(40, 52)))
        saida = os.path.join(pasta, "q")
        os.makedirs(saida)
        quadros, _ = video.extrair_quadros(caminho, saida)
        self.assertGreaterEqual(len(quadros), video.MINIMO_QUADROS)
        piores = [q for q in quadros if self._nitidez(q) < 300]
        self.assertEqual(piores, [], "escolheu quadro tremido: %s" % piores)

    def test_espacamento_e_por_giro_e_nao_por_tempo(self):
        """
        Quem filma gira em velocidade irregular. Espacar por tempo daria quadros
        amontoados no trecho lento e buraco no trecho rapido.
        """
        import numpy as np
        # giro que acelera: a primeira metade do tempo cobre um quinto do caminho
        t = np.linspace(0, 1, 140)
        pos = (t ** 2) * (2400 - 640 - 1)
        caminho, pasta = self._gravar(pos)
        saida = os.path.join(pasta, "q")
        os.makedirs(saida)
        quadros, _ = video.extrair_quadros(caminho, saida)
        self.assertGreaterEqual(len(quadros), video.MINIMO_QUADROS)
        self.assertLessEqual(len(quadros), video.MAXIMO_QUADROS)

    def test_video_limpo_sai_com_espacamento_uniforme(self):
        """
        O defeito que escapou aos outros testes e so apareceu na costura de ponta
        a ponta: escolhendo "o mais nitido da janela", um video SEM borrao tinha a
        escolha decidida por ruido de nitidez, e o espacamento ia de 4,8 a 36 graus
        onde o uniforme era 18. A costura foi recusada por deformacao enquanto os
        mesmos angulos, entregues direto, costuravam limpo.

        Espacamento torto nao aparece na contagem de quadros nem na nitidez deles:
        so medindo o intervalo.
        """
        import numpy as np
        n = 150
        pos = np.linspace(0, 2400 - 640 - 1, n)     # giro de velocidade constante
        caminho, pasta = self._gravar(pos)
        cap = video._abrir(caminho)
        try:
            nitidez, andado, _ = video._medir(cap, None)
        finally:
            cap.release()
        escolhidos = video._escolher(nitidez, andado,
                                     video.PASSO * video.LARGURA_ANALISE)
        self.assertGreaterEqual(len(escolhidos), video.MINIMO_QUADROS)
        intervalos = np.diff(escolhidos)
        medio = intervalos.mean()
        # giro constante: os intervalos tem que bater com o medio de perto
        self.assertLess(intervalos.max(), medio * 1.6,
                        "vao grande demais: %s" % intervalos.tolist())
        self.assertGreater(intervalos.min(), medio * 0.5,
                           "quadros amontoados: %s" % intervalos.tolist())

    def test_borrao_ainda_e_evitado_apesar_do_espacamento(self):
        """
        A correcao do espacamento nao pode ter custado a fuga do borrao: sao os
        dois motivos de existir do modulo, e um nao vale sem o outro.
        """
        import numpy as np
        n = 150
        pos = np.linspace(0, 2400 - 640 - 1, n)
        borrados = set(range(60, 72))
        caminho, pasta = self._gravar(pos, tremidos=borrados)
        cap = video._abrir(caminho)
        try:
            nitidez, andado, _ = video._medir(cap, None)
        finally:
            cap.release()
        escolhidos = video._escolher(nitidez, andado,
                                     video.PASSO * video.LARGURA_ANALISE)
        dentro = sorted(borrados.intersection(escolhidos))
        self.assertEqual(dentro, [], "escolheu quadro borrado: %s" % dentro)

    def test_camera_parada_e_recusada_com_recado_util(self):
        import numpy as np
        caminho, pasta = self._gravar(np.zeros(40))     # ninguem girou
        saida = os.path.join(pasta, "q")
        os.makedirs(saida)
        with self.assertRaises(video.ErroVideo) as ctx:
            video.extrair_quadros(caminho, saida)
        self.assertIn("gir", str(ctx.exception).lower())

    def test_resolucao_baixa_avisa_e_4k_nao(self):
        self.assertIsNone(video.conferir_largura(2160), "4K nao devia avisar")
        recado = video.conferir_largura(1080)
        self.assertIsNotNone(recado)
        self.assertIn("4K", recado)

    def test_formato_errado_nao_vira_tarefa(self):
        # a rota recusa antes de enfileirar, pela extensao
        self.assertNotIn(".txt", video.EXTENSOES)
        self.assertIn(".mp4", video.EXTENSOES)
        self.assertIn(".mov", video.EXTENSOES)


class TestConferenciaDaCaptura(unittest.TestCase):
    """
    A conferencia diz QUAL foto atrapalhou.

    Antes a recusa era generica ("as fotos nao tem sobreposicao") e o corretor
    nao sabia o que mudar. O risco novo e o oposto: aviso que aparece em captura
    boa ensina a ignorar o aviso, entao o silencio no caso bom vale tanto quanto
    o diagnostico no caso ruim.
    """

    def _liso(self, largura=900, altura=1200):
        import numpy as np
        return np.full((altura, largura, 3), 210, np.uint8)

    def _texturado(self, deslocamento=0, largura=900, altura=1200):
        import numpy as np
        rnd = np.random.RandomState(7)
        fundo = rnd.randint(0, 255, (altura, largura * 3, 3)).astype("uint8")
        fundo = np.repeat(np.repeat(fundo[::6, ::6], 6, 0), 6, 1)[:altura, :largura * 3]
        x = largura // 2 + deslocamento
        return fundo[:, x:x + largura].copy()

    def test_parede_lisa_e_apontada_pelo_numero(self):
        imagens = [self._texturado(0), self._texturado(120), self._liso(),
                   self._texturado(240)]
        achados = " ".join(stitcher.conferir_captura(imagens))
        self.assertIn("textura", achados.lower())
        self.assertIn("Foto 3", achados, "precisa dizer QUAL foto: " + achados)

    def test_captura_boa_nao_gera_aviso(self):
        """Silencio no caso bom: aviso em captura boa ensina a ignorar avisos."""
        imagens = [self._texturado(d) for d in (0, 90, 180, 270)]
        self.assertEqual(stitcher.conferir_captura(imagens), [])

    def test_uma_foto_so_nao_quebra(self):
        self.assertEqual(stitcher.conferir_captura([self._texturado(0)]), [])

    def test_diagnostico_entra_na_mensagem_de_erro(self):
        self.assertIn("vi nas suas fotos",
                      stitcher._com_conferencia("Recusado.", ["a foto 3 está lisa"]))
        self.assertEqual(stitcher._com_conferencia("Recusado.", []), "Recusado.")


def limpar():
    shutil.rmtree(_TEMP, ignore_errors=True)


if __name__ == "__main__":
    try:
        # warnings=None: respeita o filtro acima em vez de reativar tudo
        unittest.main(verbosity=2, exit=False, warnings=None)
    finally:
        limpar()
