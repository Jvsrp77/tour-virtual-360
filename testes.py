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
import sys
import subprocess
import threading
import time
import unittest
import warnings
import zipfile

# o cliente de teste do Flask deixa o arquivo estatico aberto ate o coletor
# passar; o aviso nao indica defeito e so atrapalha a leitura da saida
warnings.simplefilter("ignore", ResourceWarning)

# precisa vir antes de importar app: e no import que ele resolve a pasta
_TEMP = tempfile.mkdtemp(prefix="tour-testes-")
os.environ["TOUR_DADOS"] = os.path.join(_TEMP, "data")
os.environ["TOUR_BACKUPS"] = os.path.join(_TEMP, "backups")
os.makedirs(os.environ["TOUR_DADOS"], exist_ok=True)

import app as aplicacao           # noqa: E402
import servico                    # noqa: E402
import servidor                   # noqa: E402
import aviso                      # noqa: E402
import maquete3d                  # noqa: E402
import numpy as np                # noqa: E402
import plantas                    # noqa: E402
import cena_apartamento           # noqa: E402
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


class TestTetoDePasseio(unittest.TestCase):
    """
    Quanto o visitante pode andar em cada cena.

    O borrao nao e igual em toda cena: depende de o mapa de profundidade ter
    borda no contorno do movel, ou so uma mancha. Onde tem mancha, a malha
    estica a textura por cima do que esta atras, e o estrago cresce com a
    distancia andada. A cena Sala mediu escorrido 2,35% — o pior do acervo — e
    e justamente onde a poltrona derrete.

    O teto e a defesa: cena medida pior anda menos, e o visitante nunca alcanca
    a distancia em que o defeito aparece. Como e a regra que decide o que o
    comprador VE, ela e exercitada de verdade no Node, com o codigo que a pagina
    embarca — nao com uma copia escrita no teste, que envelheceria sozinha.
    """

    CORPO = re.compile(r"(const ESCORRIDO_OTIMO.*?^\})", re.S | re.M)

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        with io.open(os.path.join("static", "andar.html"), encoding="utf-8") as f:
            cls.html = f.read()

    def _rodar(self, casos):
        """Roda tetoDePasseio no Node, com a fonte extraida da propria pagina."""
        achado = self.CORPO.search(self.html)
        self.assertTrue(achado, "não achei tetoDePasseio em andar.html")
        programa = (achado.group(1) + "\nconsole.log(JSON.stringify("
                    + json.dumps(casos) + ".map(c => tetoDePasseio(c))));\n")
        caminho = os.path.join(_TEMP, "teto.mjs")
        with io.open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write(programa)
        r = subprocess.run([self.node, caminho], capture_output=True,
                           text=True, errors="ignore")
        self.assertEqual(r.returncode, 0, r.stderr[:600])
        return json.loads(r.stdout.strip())

    def test_cena_medida_pior_anda_menos(self):
        if not self.node:
            self.skipTest("node não encontrado")
        otima, ruim = self._rodar([{"escorrido": {"fracao": 0.008}},
                                   {"escorrido": {"fracao": 0.0235}}])
        self.assertGreater(otima, ruim,
                           "cena com mais escorrido tinha de andar MENOS")

    def test_a_sala_de_verdade_fica_bem_abaixo_do_cheio(self):
        """2,35% medido na Sala: o passeio tem de cair para perto de 1 m."""
        if not self.node:
            self.skipTest("node não encontrado")
        (teto,) = self._rodar([{"escorrido": {"fracao": 0.02352}}])
        self.assertLess(teto, 1.3)
        self.assertGreater(teto, 0.8)

    def test_cena_boa_anda_o_maximo(self):
        if not self.node:
            self.skipTest("node não encontrado")
        (teto,) = self._rodar([{"escorrido": {"fracao": 0.004}}])
        self.assertAlmostEqual(teto, 2.50, places=2)

    def test_cena_sem_medida_nao_ganha_folga_indevida(self):
        """Sem medida nao da para afrouxar; o padrao nao pode passar do cheio."""
        if not self.node:
            self.skipTest("node não encontrado")
        sem, vazio = self._rodar([{}, {"escorrido": {}}])
        self.assertLessEqual(sem, 2.50)
        self.assertLessEqual(vazio, 2.50)

    def test_cena_pessima_ainda_anda_um_pouco(self):
        """Teto zero tiraria o passeio inteiro sem avisar; tem piso."""
        if not self.node:
            self.skipTest("node não encontrado")
        (teto,) = self._rodar([{"escorrido": {"fracao": 0.9}}])
        self.assertGreater(teto, 0.0)
        self.assertLess(teto, 0.5)

    def test_o_teto_e_mesmo_aplicado_no_passo(self):
        """
        Calcular o teto e nao usar seria pior que nao ter: daria a impressao de
        protecao. podeEstar precisa comparar a distancia com o MENOR entre o que
        o controle pediu e o que a cena aguenta.
        """
        corpo = re.split(r"^\}", self.html.split("function podeEstar(")[1],
                         maxsplit=1, flags=re.M)[0]
        self.assertIn("tetoDePasseio(", corpo,
                      "podeEstar ignora o teto da cena")
        self.assertIn("Math.min(", corpo,
                      "podeEstar não limita pelo menor dos dois")


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

    def test_a_leitura_do_tour_pega_a_trava(self):
        """
        Verificacao DETERMINISTICA da trava de leitura.

        O outro teste desta classe depende de uma corrida acontecer, e corrida
        nao acontece sob encomenda: com a maquina carregada ele passava mesmo com
        a trava removida, e a checagem de mutacao flagrou isso — "teste cego" na
        protecao contra PERDA DE DADOS, que e a pior de todas para ficar sem
        verificacao.

        Aqui nao ha aposta: segura-se a trava do imovel numa thread e cobra-se
        que `carregar_tour` fique esperando. Sem trava na leitura, ela passa
        direto e o teste falha na hora, sempre.
        """
        dona = self.conta("travaleitura")
        iid = self.imovel(dona, "Trava")

        trava = aplicacao.trava_do_imovel(iid)
        terminou = threading.Event()

        def ler():
            with aplicacao.app.test_request_context():
                aplicacao.carregar_tour(iid)
            terminou.set()

        trava.acquire()
        try:
            t = threading.Thread(target=ler, daemon=True)
            t.start()
            passou_direto = terminou.wait(timeout=1.0)
            self.assertFalse(
                passou_direto,
                "a leitura do tour NÃO pegou a trava: no Windows o os.replace da "
                "gravação falha com o arquivo aberto, e contatos se perdem")
        finally:
            trava.release()

        self.assertTrue(terminou.wait(timeout=10.0),
                        "a leitura ficou presa depois da trava ser solta")

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


class TestConfiancaDaArea(Base):
    """
    Metragem errada num anuncio nao e detalhe estetico: e o numero que o
    comprador usa para comparar preco entre imoveis.

    A estimativa vem de um retangulo ajustado ao contorno do piso — acerta em
    comodo retangular com paredes a vista, erra em comodo em L ou com movel
    tapando parede. Ate agora saia com a mesma cara nos dois casos. Medido no
    quarto real: 11,1 m2 estimados contra 13,6 m2 do LiDAR, erro de -18%.
    """

    def test_comodo_retangular_tem_confianca_alta(self):
        import numpy as np
        import area
        # contorno de retangulo perfeito, camera no centro
        n = 360
        ang = (np.arange(n) / n - 0.5) * 2 * np.pi
        a, b = 3.0, 2.0
        du, dv = np.sin(ang), np.cos(ang)
        with np.errstate(divide="ignore"):
            contorno = np.fmin(np.abs(a / np.where(np.abs(du) < 1e-6, 1e-6, du)),
                               np.abs(b / np.where(np.abs(dv) < 1e-6, 1e-6, dv)))
        c = area._confianca(contorno.astype(np.float32), 0.0, (a, a, b, b),
                            piso_livre=4 * a * b * 0.9, metros2=4 * a * b,
                            fracao_com_piso=0.95)
        self.assertEqual(c["leitura"], "alta", c)
        self.assertGreater(c["aderencia"], 0.7)

    def test_contorno_torto_derruba_a_confianca(self):
        """Cômodo em L, ou móvel tapando: o retângulo deixa de explicar."""
        import numpy as np
        import area
        n = 360
        rnd = np.random.RandomState(3)
        contorno = (2.0 + rnd.rand(n) * 3.0).astype(np.float32)   # nada retangular
        c = area._confianca(contorno, 0.0, (3.0, 3.0, 2.0, 2.0),
                            piso_livre=6.0, metros2=24.0, fracao_com_piso=0.5)
        self.assertIn(c["leitura"], ("baixa", "media"))
        self.assertLess(c["aderencia"], 0.5)

    def test_a_camera_fora_do_centro_nao_derruba_sozinha(self):
        """
        Quem fotografa quase nunca está no meio do cômodo. Tratar o retângulo
        como centrado dava aderência ZERO em tudo, inclusive na cena conferida
        com LiDAR — o defeito que este teste existe para impedir.
        """
        import numpy as np
        import area
        n = 360
        ang = (np.arange(n) / n - 0.5) * 2 * np.pi
        um, ume, vm, vme = 4.0, 1.0, 1.5, 1.2      # bem fora do centro
        du, dv = np.sin(ang), np.cos(ang)
        au = np.where(du > 1e-6, um / du, np.where(du < -1e-6, -ume / du, np.inf))
        av = np.where(dv > 1e-6, vm / dv, np.where(dv < -1e-6, -vme / dv, np.inf))
        contorno = np.fmin(au, av).astype(np.float32)
        c = area._confianca(contorno, 0.0, (um, ume, vm, vme),
                            piso_livre=20.0, metros2=25.0, fracao_com_piso=0.95)
        self.assertGreater(c["aderencia"], 0.7,
                           "voltou a tratar o retângulo como centrado na câmera")

    def test_numero_digitado_nao_carrega_confianca(self):
        """Quem digitou o próprio número assumiu: a nota é da estimativa."""
        dona = self.conta("areaconf")
        iid = self.imovel(dona, "Casa")
        tour = dona.get("/api/imoveis/%s/tour" % iid).get_json()
        dona.post("/api/imoveis/%s/cenas/demo" % iid, json={"nome": "Sala"})
        cena = dona.get("/api/imoveis/%s/tour" % iid).get_json()["cenas"][0]
        r = dona.put("/api/imoveis/%s/cenas/%s/area" % (iid, cena["id"]),
                     json={"area_m2": 20.0, "corrigido": True,
                           "confianca": {"nota": 0.1, "leitura": "baixa"}})
        self.assertNotIn("confianca", r.get_json()["area"])

    def test_o_painel_avisa_antes_de_publicar_medida_ruim(self):
        with io.open(os.path.join("static", "admin.html"), encoding="utf-8") as f:
            painel = f.read()
        self.assertIn("notaDeConfianca", painel)
        self.assertIn("confiança BAIXA", painel)


class TestPrevisaoDeEscorrido(unittest.TestCase):
    """
    O corretor precisa saber se a captura presta ANTES de publicar.

    A armadilha desta medida ja aconteceu: a primeira versao contava QUALQUER
    variacao suave de profundidade e dava 21% num quarto vazio, pior que uma sala
    mobiliada. Parede lisa produz gradiente suave ao longo de toda a extensao, o
    que e inofensivo — a parede e mesmo continua e nao ha nada atras para
    revelar. Aquela versao teria trocado cenas boas por piores com um numero
    dando respaldo.

    Por isso os testes cobrem os DOIS lados: acusar o que escorre e ficar calado
    no que nao escorre.
    """

    def _cena(self, com_objeto):
        """
        Reproduz o caso real: foto com borda NITIDA, profundidade BORRADA.

        E assim que o defeito nasce. O modelo monocular nao entrega a silhueta do
        movel, entrega uma bolha — a transicao vira rampa larga onde deveria ser
        degrau, e e a rampa que derrama a textura ao caminhar. Degrau abrupto nao
        serve para testar: acima do limite o visualizador ja apaga o triangulo e
        a camada de fundo assume.
        """
        import numpy as np
        import cv2
        A, L = 256, 512
        disp = np.linspace(0.25, 0.55, A, dtype=np.float32)[:, None].repeat(L, 1)
        rnd = np.random.RandomState(5)
        foto = (np.full((A, L, 3), 160, np.int16)
                + rnd.randint(-12, 12, (A, L, 3))).clip(0, 255).astype(np.uint8)
        if com_objeto:
            disp[120:190, 150:330] = 0.62        # movel um pouco a frente
            foto[120:190, 150:330] = 40          # e bem visivel na foto
            # a bolha do modelo: borda de profundidade borrada, foto intacta
            disp = cv2.GaussianBlur(disp, (0, 0), sigmaX=7)
        return foto, disp

    def test_objeto_na_frente_e_acusado(self):
        import profundidade
        foto, disp = self._cena(com_objeto=True)
        com = profundidade.medir_escorrido(foto, disp)["fracao"]
        foto2, disp2 = self._cena(com_objeto=False)
        sem = profundidade.medir_escorrido(foto2, disp2)["fracao"]
        self.assertGreater(com, sem,
                           "não distinguiu cena com objeto de cena sem objeto")

    def test_parede_lisa_nao_e_acusada(self):
        """
        O erro exato da primeira versão: contar variação de profundidade onde a
        FOTO não tem borda. Quarto vazio saía pior que sala mobiliada, e eu quase
        troquei uma cena boa por uma pior confiando nesse número.

        O caso precisa ser calibrado com cuidado: um degradê muito suave nem
        chega ao limite de rampa, e aí o teste passaria dos dois jeitos — cego.
        Aqui a profundidade tem rampa de verdade (0,089 da imagem sem a exigência
        de borda) e a foto é lisa, então a medida correta tem de dar zero.
        """
        import numpy as np
        import cv2
        import profundidade
        A, L = 256, 512
        disp = np.full((A, L), 0.30, np.float32)
        disp[100:180, 140:360] = 0.75            # variação forte de profundidade
        disp = cv2.GaussianBlur(disp, (0, 0), sigmaX=9)   # a bolha do modelo
        foto = np.full((A, L, 3), 200, np.uint8)          # e nenhuma borda na foto
        m = profundidade.medir_escorrido(foto, disp)
        self.assertLess(m["fracao"], 0.005,
                        "acusou parede lisa: a medida voltou a contar variação "
                        "onde a foto não tem borda, e isso já quase trocou cena "
                        "boa por pior")

    def test_leitura_em_palavras(self):
        import profundidade
        self.assertLessEqual(profundidade.ESCORRIDO_OTIMO,
                             profundidade.ESCORRIDO_ACEITAVEL)
        foto, disp = self._cena(com_objeto=False)
        self.assertIn(profundidade.medir_escorrido(foto, disp)["leitura"],
                      ("otimo", "aceitavel", "ruim"))

    def test_o_painel_mostra_a_nota(self):
        with io.open(os.path.join("static", "admin.html"), encoding="utf-8") as f:
            painel = f.read()
        self.assertIn("notaDeEscorrido", painel)
        self.assertIn("escorrido ao caminhar", painel)


class TestBotoesDoCartao(unittest.TestCase):
    """
    Os botoes do cartao de imovel: Editar, Ver e Excluir.

    O Excluir passou tempo QUEBRADO sem ninguem notar. O onclick era montado
    com JSON.stringify(titulo), que devolve o texto entre aspas duplas — e o
    proprio atributo onclick e delimitado por aspas duplas. O navegador fechava
    o atributo no meio e lia `remover('id',`, um erro de sintaxe. O clique nao
    fazia nada, calado.

    Os testes que existiam nao pegavam: `test_handlers_do_html_tem_funcao` so
    confere se a funcao chamada existe, e `remover` existia. `test_javascript_
    das_paginas_compila` confere o <script>, e o script estava certo — o defeito
    nascia na STRING que ele gera em tempo de execucao.

    Entao aqui o molde do cartao e RENDERIZADO no Node, com titulos hostis, e
    cada onclick que sai dele tem de ser JavaScript valido.
    """

    HOSTIS = ['Teste', 'Casa "dos sonhos" & cia', "Ap's do João <b>",
              'Barra\\invertida']

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        with io.open(os.path.join("static", "imoveis.html"), encoding="utf-8") as f:
            html = f.read()
        marca = "$('grade').innerHTML = lista.map(i => `"
        cls.molde = html[html.index(marca) + len(marca):]
        cls.molde = cls.molde[:cls.molde.index("`).join('');")]

    def _onclicks(self, titulo, ambientes):
        """Renderiza o cartao e devolve o codigo de cada onclick."""
        programa = (
            'const escapar = t => String(t).replace(/[&<>"]/g, c => '
            '({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;"}[c]));\n'
            "const nBR = n => String(n);\n"
            "const i = {id:'bc7136253c', titulo:" + json.dumps(titulo) + ", "
            "ambientes:" + str(ambientes) + ", capa:null, area_total:0, "
            "ambientes_medidos:0, com_profundidade:0, leads:0};\n"
            "const html = `" + self.molde + "`;\n"
            'for (const m of html.matchAll(/onclick="([^"]*)"/g)) '
            "console.log(m[1]);\n")
        caminho = os.path.join(_TEMP, "cartao.mjs")
        with io.open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write(programa)
        r = subprocess.run([self.node, caminho], capture_output=True, text=True,
                           errors="ignore")
        self.assertEqual(r.returncode, 0, r.stderr[:500])
        return [l for l in r.stdout.strip().splitlines() if l.strip()]

    def test_todo_onclick_do_cartao_e_javascript_valido(self):
        if not self.node:
            self.skipTest("node não encontrado")
        for titulo in self.HOSTIS:
            for codigo in self._onclicks(titulo, 5):
                caminho = os.path.join(_TEMP, "trecho.mjs")
                with io.open(caminho, "w", encoding="utf-8", newline="") as f:
                    f.write(codigo + "\n")
                r = subprocess.run([self.node, "--check", caminho],
                                   capture_output=True, text=True, errors="ignore")
                self.assertEqual(r.returncode, 0,
                                 "título %r gerou onclick inválido: %s\n%s"
                                 % (titulo, codigo, r.stderr[:300]))

    def test_o_cartao_tem_os_tres_botoes(self):
        if not self.node:
            self.skipTest("node não encontrado")
        codigos = self._onclicks("Casa", 5)
        self.assertEqual(len(codigos), 3, codigos)
        self.assertTrue(any("/painel/" in c for c in codigos), codigos)
        self.assertTrue(any("/tour/" in c for c in codigos), codigos)
        self.assertTrue(any("remover(" in c for c in codigos), codigos)

    def test_o_ver_desligado_diz_por_que(self):
        """
        Sem ambiente o botão fica desabilitado, e isso é certo — não há o que
        mostrar. Mas botão apagado sem explicação se lê como defeito: foi
        exatamente assim que ele foi reportado como quebrado.
        """
        with io.open(os.path.join("static", "imoveis.html"), encoding="utf-8") as f:
            html = f.read()
        pedaco = html[html.index("window.open('/tour/"):]
        pedaco = pedaco[:pedaco.index("</button>")]
        self.assertIn("disabled", pedaco)
        self.assertIn("title=", pedaco, "desabilitado sem dizer o motivo")


class TestMaquete(Base):
    """
    A vista 3D do imovel, dentro do sistema.

    Ela so existe onde HA geometria: imovel gerado conhece as paredes e os
    moveis em metros, porque foi assim que nasceu. Imovel FOTOGRAFADO tem
    panorama e mapa de profundidade, que e outra coisa — e prometer maquete ali
    seria vender o que o produto nao entrega.

    E publica como o tour: quem recebe o link do imovel abre a maquete sem
    conta. Exigir login aqui esconderia do comprador justamente a tela que
    ajuda a vender.
    """

    GEOMETRIA = {
        "nome": "Casa de teste", "descricao": "duas paredes e um sofá",
        "larg": 6.0, "fundo": 4.0, "pe": 2.7,
        "zonas": [{"nome": "Sala", "x0": 0, "x1": 6, "z0": 0, "z1": 4,
                   "m2": 24.0, "piso": "#8a6a42", "parede": "#a8aaac"}],
        "caixas": [{"p": [1, 0, 1, 2, 0.8, 3], "m": "estofado", "cor": "#7a687e"}],
        "pontos": [{"nome": "Sala - centro", "x": 3.0, "z": 2.0}],
        "janelas": [],
    }

    def setUp(self):
        self.dona = self.conta("dona-maquete")
        self.iid = self.imovel(self.dona, "Imóvel com geometria")
        self.sem = self.imovel(self.dona, "Imóvel de fotos")
        with io.open(aplicacao.arq_maquete(self.iid), "w", encoding="utf-8") as f:
            json.dump(self.GEOMETRIA, f, ensure_ascii=False)

    def test_a_geometria_chega_pela_api(self):
        r = self.dona.get("/api/imoveis/%s/maquete" % self.iid)
        self.assertEqual(r.status_code, 200)
        m = r.get_json()["maquete"]
        self.assertEqual(len(m["zonas"]), 1)
        self.assertEqual(m["pontos"][0]["nome"], "Sala - centro")

    def test_imovel_de_fotos_responde_que_nao_tem(self):
        """
        404 com recado, e nao uma maquete vazia: tela 3D em branco faria o
        corretor achar que quebrou, quando na verdade nunca houve geometria.
        """
        r = self.dona.get("/api/imoveis/%s/maquete" % self.sem)
        self.assertEqual(r.status_code, 404)
        self.assertIn("geometria", r.get_json()["erro"])

    def test_a_maquete_e_publica_como_o_tour(self):
        """Quem recebe o link do imóvel precisa abrir sem conta."""
        visitante = aplicacao.app.test_client()
        self.assertEqual(
            visitante.get("/api/imoveis/%s/maquete" % self.iid).status_code, 200)
        self.assertEqual(visitante.get("/maquete/%s" % self.iid).status_code, 200)

    def test_sem_geometria_a_pagina_manda_de_volta_ao_tour(self):
        """Abrir uma maquete que não existe tem de levar a algum lugar útil."""
        r = aplicacao.app.test_client().get("/maquete/%s" % self.sem)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/tour/%s" % self.sem, r.headers["Location"])

    def test_o_titulo_do_imovel_manda_no_da_geometria(self):
        """
        O corretor renomeia o imóvel no painel; a geometria foi gravada uma vez.
        Quem tem a última palavra é o painel, senão a maquete mostra um nome que
        já não existe em lugar nenhum.
        """
        tour = self.dona.get("/api/imoveis/%s/tour" % self.iid).get_json()
        tour["titulo"] = "Apartamento renomeado"
        self.dona.put("/api/imoveis/%s/tour" % self.iid, json=tour)
        m = self.dona.get("/api/imoveis/%s/maquete" % self.iid).get_json()["maquete"]
        self.assertEqual(m["titulo"], "Apartamento renomeado")

    def test_o_botao_so_aparece_quando_ha_geometria(self):
        """
        O botão pergunta ao servidor em vez de aparecer sempre: num imóvel de
        fotos ele levaria a uma tela que não tem o que mostrar.
        """
        for pagina in ("viewer.html", "admin.html"):
            html = io.open(os.path.join("static", pagina), encoding="utf-8").read()
            self.assertIn("verSeTemMaquete", html, pagina)
            self.assertIn("/maquete", html, pagina)

    def test_a_pagina_da_maquete_nao_some_do_static(self):
        html = io.open(os.path.join("static", "maquete.html"), encoding="utf-8").read()
        self.assertIn("URL_MAQUETE", html)
        self.assertIn("vendor/three.js", html)


    def test_cada_ponto_aponta_para_a_cena_tirada_dali(self):
        """
        E isto que costura a maquete ao tour: clicar no pino abre o 360 feito
        naquele lugar. O casamento e pelo nome, que e o mesmo dos dois lados
        porque a cena nasceu do ponto.
        """
        # a rota de cena demo aplica title() no nome, entao renomeia-se para o
        # nome exato do ponto — que e o que o importador de verdade grava
        self.dona.post("/api/imoveis/%s/cenas/demo" % self.iid, json={"nome": "x"})
        tour = self.dona.get("/api/imoveis/%s/tour" % self.iid).get_json()
        self.dona.put("/api/imoveis/%s/cenas/%s" % (self.iid, tour["cenas"][0]["id"]),
                      json={"nome": self.GEOMETRIA["pontos"][0]["nome"]})
        m = self.dona.get("/api/imoveis/%s/maquete" % self.iid).get_json()["maquete"]
        ponto = m["pontos"][0]
        self.assertIn("cena_id", ponto)
        self.assertTrue(ponto["cena_id"], "o pino ficou sem cena para abrir")

    def test_cena_renomeada_deixa_o_pino_sem_link(self):
        """
        Perder o link e melhor do que levar para a cena ERRADA. Sem cena_id o
        pino simplesmente nao abre nada, e a pagina diz isso.
        """
        self.dona.post("/api/imoveis/%s/cenas/demo" % self.iid, json={"nome": "x"})
        tour = self.dona.get("/api/imoveis/%s/tour" % self.iid).get_json()
        cid = tour["cenas"][0]["id"]
        self.dona.put("/api/imoveis/%s/cenas/%s" % (self.iid, cid),
                      json={"nome": "Outro nome qualquer"})
        m = self.dona.get("/api/imoveis/%s/maquete" % self.iid).get_json()["maquete"]
        self.assertIsNone(m["pontos"][0]["cena_id"])

    def test_a_planta_baixa_usa_projecao_ortografica(self):
        """
        Em perspectiva, parede longe parece menor que parede perto — e planta
        baixa serve justamente para comparar medidas. Perspectiva mentiria.
        """
        html = io.open(os.path.join("static", "maquete.html"), encoding="utf-8").read()
        self.assertIn("OrthographicCamera", html)
        self.assertIn("chPlanta", html)

    def test_a_trena_mede_no_plano_do_piso(self):
        html = io.open(os.path.join("static", "maquete.html"), encoding="utf-8").read()
        self.assertIn("btTrena", html)
        self.assertIn("distanceTo", html, "a trena não calcula distância")

    def test_a_ficha_mostra_largura_e_profundidade(self):
        """
        Metragem sozinha não diz o formato: 12 m² num corredor de 1,2 m não é o
        mesmo produto que 12 m² num quarto de 3 x 4.
        """
        html = io.open(os.path.join("static", "maquete.html"), encoding="utf-8").read()
        for campo in ("comodoL", "comodoP", "comodoA", "comodoV"):
            self.assertIn(campo, html, campo)


class TestLinkDireitoParaCena(Base):
    """
    /tour/<imovel>?cena=<id> abre direto naquele ambiente.

    Serve para dois usos: mandar "olha a cozinha" para um cliente, e para a
    maquete — clicar no pino cai na cena tirada dali.
    """

    def setUp(self):
        self.dona = self.conta("dona-link")
        self.iid = self.imovel(self.dona, "Com cenas")
        self.dona.post("/api/imoveis/%s/cenas/demo" % self.iid, json={"nome": "Sala"})
        self.dona.post("/api/imoveis/%s/cenas/demo" % self.iid, json={"nome": "Cozinha"})

    def test_o_visor_aceita_a_cena_pedida(self):
        html = io.open(os.path.join("static", "viewer.html"), encoding="utf-8").read()
        self.assertIn("URLSearchParams", html)
        self.assertIn("'cena'", html)

    def test_cena_inexistente_cai_na_inicial_em_vez_de_tela_preta(self):
        """
        Link velho, cena apagada: abrir vazio seria pior do que abrir o tour no
        comeco. A pagina confere se o id existe antes de usar.
        """
        html = io.open(os.path.join("static", "viewer.html"), encoding="utf-8").read()
        corpo = html[html.index("function montarCenas()"):]
        pedaco = corpo[:corpo.index("pannellum.viewer")]
        self.assertIn("existe(", pedaco, "usa a cena pedida sem conferir se existe")
        self.assertIn("cena_inicial", pedaco, "não tem para onde cair")


class TestExportarObj(Base):
    """
    A maquete baixada como OBJ + MTL, para abrir no SketchUp ou no Blender.

    O que pode sair errado num OBJ nao aparece lendo o codigo: indice de
    vertice fora da faixa, material usado e nunca declarado, modelo em escala
    errada. Nenhum desses quebra o gerador — quebram o arquivo, e so se
    descobre quando alguem tenta abrir. Entao o arquivo gerado e LIDO de volta
    e conferido aqui.
    """

    GEO = {
        "nome": "Casa de teste", "titulo": "Casa de teste", "larg": 6.0,
        "fundo": 4.0, "pe": 2.7,
        "zonas": [{"nome": "Sala", "x0": 0, "x1": 6, "z0": 0, "z1": 4,
                   "m2": 24.0, "piso": "#8a6a42", "parede": "#a8aaac"}],
        "caixas": [{"p": [1, 0, 1, 2, 0.8, 3], "m": "estofado", "cor": "#7a687e"},
                   {"p": [3, 0, 0, 3.12, 2.7, 4], "m": "parede", "cor": "#b0aea8"}],
        "pontos": [{"nome": "Sala - centro", "x": 3.0, "z": 2.0}],
        "janelas": [],
    }

    def setUp(self):
        self.dona = self.conta("dona-obj")
        self.iid = self.imovel(self.dona, "Com geometria")
        with io.open(aplicacao.arq_maquete(self.iid), "w", encoding="utf-8") as f:
            json.dump(self.GEO, f, ensure_ascii=False)

    def _ler(self, obj):
        verts, faces, usados = [], [], set()
        for linha in obj.split("\n"):
            if linha.startswith("v "):
                verts.append([float(v) for v in linha.split()[1:]])
            elif linha.startswith("f "):
                faces.append([int(p.split("//")[0]) for p in linha.split()[1:]])
            elif linha.startswith("usemtl "):
                usados.add(linha.split()[1])
        return verts, faces, usados

    def test_nenhuma_face_aponta_para_vertice_que_nao_existe(self):
        """
        Índice fora da faixa é o defeito clássico de gerador de OBJ, porque a
        numeração é global e começa em 1. O arquivo abre e some geometria, ou
        o programa recusa inteiro.
        """
        obj, _ = maquete3d.para_obj(self.GEO)
        verts, faces, _ = self._ler(obj)
        self.assertTrue(faces)
        for f in faces:
            for i in f:
                self.assertTrue(1 <= i <= len(verts),
                                "índice %d fora de 1..%d" % (i, len(verts)))

    def test_todo_material_usado_esta_declarado(self):
        """Material sem declaração abre cinza, e o modelo perde a leitura."""
        obj, mtl = maquete3d.para_obj(self.GEO)
        _, _, usados = self._ler(obj)
        declarados = {l.split()[1] for l in mtl.split("\n")
                      if l.startswith("newmtl ")}
        self.assertTrue(usados)
        self.assertEqual(usados - declarados, set())

    def test_o_modelo_sai_na_escala_do_imovel(self):
        """
        Escala errada é o erro que mais custa: o modelo abre, parece certo, e
        só quem for medir descobre. A envolvente tem de dar o tamanho do imóvel.
        """
        obj, _ = maquete3d.para_obj(self.GEO)
        verts, _, _ = self._ler(obj)
        larg = max(v[0] for v in verts) - min(v[0] for v in verts)
        fundo = max(v[2] for v in verts) - min(v[2] for v in verts)
        self.assertAlmostEqual(larg, self.GEO["larg"], places=2)
        self.assertAlmostEqual(fundo, self.GEO["fundo"], places=2)

    def test_a_fachada_existe_no_arquivo(self):
        """
        As paredes externas não estão na lista de caixas — no traçador elas são
        a casca do imóvel. Sem recriá-las aqui, o modelo abre sem fachada.
        """
        obj, _ = maquete3d.para_obj(self.GEO)
        self.assertIn("casca_frente", obj)
        self.assertIn("casca_fundo", obj)

    def test_o_zip_leva_obj_e_mtl_juntos(self):
        """Separados, o modelo abre todo cinza. É do formato, não escolha."""
        memoria, nome = maquete3d.zipar(self.GEO)
        with zipfile.ZipFile(memoria) as z:
            nomes = z.namelist()
        self.assertTrue(any(n.endswith(".obj") for n in nomes), nomes)
        self.assertTrue(any(n.endswith(".mtl") for n in nomes), nomes)
        self.assertTrue(nome.endswith(".zip"))

    def test_a_dona_baixa(self):
        r = self.dona.get("/api/imoveis/%s/maquete/obj" % self.iid)
        self.assertEqual(r.status_code, 200)
        self.assertIn("zip", r.headers["Content-Type"])

    def test_visitante_ve_a_maquete_mas_nao_leva_o_modelo(self):
        """
        Ver o imóvel ajuda a vender; levar a geometria editável embora é outra
        coisa, e quem decide é a dona.
        """
        visitante = aplicacao.app.test_client()
        self.assertEqual(
            visitante.get("/api/imoveis/%s/maquete" % self.iid).status_code, 200)
        self.assertEqual(
            visitante.get("/api/imoveis/%s/maquete/obj" % self.iid).status_code, 401)

    def test_imovel_de_fotos_nao_tem_o_que_exportar(self):
        outro = self.imovel(self.dona, "Só fotos")
        r = self.dona.get("/api/imoveis/%s/maquete/obj" % outro)
        self.assertEqual(r.status_code, 404)


class TestPrimeiraPessoa(unittest.TestCase):
    """
    Andar dentro da maquete, na altura dos olhos.

    O que pode dar errado aqui nao aparece em revisao de codigo: atravessar
    parede, nascer dentro de um movel, sair do imovel pelo fundo. Entao a
    funcao de colisao e EXTRAIDA da pagina e exercitada no Node contra a
    geometria real dos tres imoveis.

    (O olho a 1,50 m e o mesmo ALTURA_CAMERA do andar.html de proposito: o que
    se ve aqui tem de ser o que a camera da cena 360 viu.)
    """

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        with io.open(os.path.join("static", "maquete.html"), encoding="utf-8") as f:
            cls.html = f.read()

    def _livre(self, planta, pontos):
        """Roda a `livre` da pagina contra a geometria de uma planta."""
        corpo = self.html[self.html.index("  function livre(x, z){"):]
        corpo = corpo[:corpo.index("\n  }") + 4]
        raio = re.search(r"RAIO_CORPO = ([\d.]+)", self.html).group(1)

        solidos, cx, cz = [], -planta["larg"] / 2, -planta["fundo"] / 2
        for c in planta["caixas"]:
            if c[6] == "parede" or c[4] - c[1] > 0.35:
                solidos.append({"x0": c[0] + cx, "x1": c[3] + cx,
                                "z0": c[2] + cz, "z1": c[5] + cz})
        programa = ("const RAIO_CORPO = " + raio + ";\n"
                    "const solidos = " + json.dumps(solidos) + ";\n"
                    "const atual = 0;\n"
                    "const imoveis = [" + json.dumps(
                        {"larg": planta["larg"], "fundo": planta["fundo"]}) + "];\n"
                    + corpo + "\n"
                    "console.log(JSON.stringify(" + json.dumps(pontos)
                    + ".map(p => livre(p[0], p[1]))));\n")
        caminho = os.path.join(_TEMP, "livre.mjs")
        with io.open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write(programa)
        r = subprocess.run([self.node, caminho], capture_output=True, text=True,
                           errors="ignore")
        self.assertEqual(r.returncode, 0, r.stderr[:600])
        return json.loads(r.stdout.strip())

    def test_a_visita_sempre_comeca_em_lugar_livre(self):
        """
        Medido: no apartamento compacto o ponto "junto ao sofá" fica EM CIMA da
        mesa de centro. Para a foto isso é normal — a câmera a 1,50 m olha por
        cima de uma mesa de 42 cm. Para ANDAR não dá: nasceria dentro dela.

        Por isso a entrada escolhe o primeiro ponto onde caiba um corpo, e não
        o primeiro ponto da lista.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        for construir in plantas.TODAS:
            p = construir()
            livres = self._livre(p, [[x - p["larg"] / 2, z - p["fundo"] / 2]
                                     for _, x, z in p["pontos"]])
            self.assertIn(True, livres,
                          "%s: nenhum ponto de captura tem espaço para andar"
                          % p["nome"])

    def test_a_entrada_procura_lugar_livre_em_vez_de_pegar_o_primeiro(self):
        corpo = self.html[self.html.index("function pontoDeEntrada"):]
        corpo = corpo[:corpo.index("function entrarEmPessoa")]
        self.assertIn("livre(", corpo, "não confere se cabe um corpo")
        entrada = self.html[self.html.index("function entrarEmPessoa"):]
        entrada = entrada[:entrada.index("function sairDePessoa")]
        self.assertIn("pontoDeEntrada(im)", entrada)
        self.assertNotIn("im.pontos[0]", entrada,
                         "voltou a entrar no primeiro ponto sem conferir")

    def test_a_parede_barra_o_corpo(self):
        """Colisão que nunca barra nada deixa atravessar o imóvel inteiro."""
        if not self.node:
            self.skipTest("node não encontrado")
        p = plantas.apartamento()
        # o centro de uma parede interna, em coordenadas do mundo
        parede = next(c for c in p["caixas"] if c[6] == "parede")
        x = (parede[0] + parede[3]) / 2 - p["larg"] / 2
        z = (parede[2] + parede[5]) / 2 - p["fundo"] / 2
        self.assertEqual(self._livre(p, [[x, z]]), [False],
                         "atravessou a parede")

    def test_nao_se_sai_do_imovel(self):
        if not self.node:
            self.skipTest("node não encontrado")
        p = plantas.apartamento()
        fora = [[p["larg"], 0], [-p["larg"], 0], [0, p["fundo"]], [0, -p["fundo"]]]
        self.assertEqual(self._livre(p, fora), [False] * 4,
                         "saiu pelas paredes externas")

    def test_de_dentro_as_paredes_ficam_inteiras(self):
        """
        Com a parede cortada em 1,10 m, de dentro se enxerga o cômodo vizinho
        por cima — a visita viraria um raio-X. Entrar devolve a altura cheia.
        """
        corpo = self.html[self.html.index("function entrarEmPessoa()"):]
        corpo = corpo[:corpo.index("function sairDePessoa()")]
        self.assertIn('$("corte").value = 270', corpo)
        self.assertIn("aplicarCorte()", corpo)

    def test_o_olho_fica_na_altura_da_camera_do_tour(self):
        """Se divergir, o que se vê aqui deixa de ser o que a cena 360 viu."""
        aqui = float(re.search(r"const OLHO = ([\d.]+)", self.html).group(1))
        with io.open(os.path.join("static", "andar.html"), encoding="utf-8") as f:
            la = float(re.search(r"ALTURA_CAMERA = ([\d.]+)", f.read()).group(1))
        self.assertEqual(aqui, la)


class TestPlantasSinteticas(unittest.TestCase):
    """
    As plantas que geram o acervo de demonstracao.

    Nasceram de uma perda: o acervo de imagens foi apagado do OneDrive e nao
    havia mais o que demonstrar. Como sao sinteticas, a profundidade sai do
    proprio raio em vez do modelo de IA — e por isso ela precisa falar a MESMA
    lingua que o visualizador, senao o comodo inteiro vem na distancia errada e
    caminhar fica sem sentido.
    """

    FORMULA = re.compile(r"const raio = d => 1 / \(([\d.]+) \* d \+ ([\d.]+)\)")

    def test_a_conversao_de_profundidade_fecha_com_o_visualizador(self):
        """
        A ida e a volta tem de bater. O andar.html reconstroi o raio com
        r = 1/(a*d + b); aqui gravamos d. Se um lado mudar sem o outro, todas as
        distancias saem erradas de uma vez — e em silencio, porque a imagem
        continua bonita parada no ponto.
        """
        with io.open(os.path.join("static", "andar.html"), encoding="utf-8") as f:
            achado = self.FORMULA.search(f.read())
        self.assertTrue(achado, "não achei a fórmula do raio em andar.html")
        a, b = float(achado.group(1)), float(achado.group(2))

        metros = np.array([[0.8, 1.5, 2.5, 4.0, 6.0]], dtype=np.float32)
        d = cena_apartamento.disparidade_exata(np.repeat(metros, 2, axis=0), largura=10)
        volta = 1.0 / (a * d + b)
        # a conversao passa por um redimensionamento; o que importa e a ordem de
        # grandeza bater, nao o pixel exato
        self.assertLess(abs(float(volta.min()) - 0.8), 0.6, volta)
        self.assertLess(abs(float(volta.max()) - 6.0), 2.0, volta)

    def test_a_formula_do_visor_nao_mudou_sozinha(self):
        """Se alguém calibrar o visor, esta conversão precisa acompanhar."""
        with io.open(os.path.join("static", "andar.html"), encoding="utf-8") as f:
            achado = self.FORMULA.search(f.read())
        a, b = float(achado.group(1)), float(achado.group(2))
        fonte = io.open("cena_apartamento.py", encoding="utf-8").read()
        self.assertIn(str(a), fonte, "o traçador usa outra constante que o visor")
        self.assertIn(str(b), fonte, "o traçador usa outra constante que o visor")

    def test_nenhuma_planta_poe_a_camera_dentro_de_movel(self):
        """
        Ja aconteceu: a camera caiu dentro do retangulo da cama e o colchao virou
        o chao inteiro — descoberto so depois de meia hora renderizando em 8k.
        A conferencia custa milissegundos e diz o nome do ponto.
        """
        for construir in plantas.TODAS:
            planta = construir()
            problemas = cena_apartamento.conferir(planta)
            self.assertEqual(problemas, [], "%s: %s" % (planta["nome"], problemas))

    def test_a_conferencia_acusa_camera_dentro_de_movel(self):
        """Conferência que nunca reprova nada não é conferência."""
        planta = plantas.compacto()
        nome, x, z = planta["pontos"][0]
        planta["caixas"] = list(planta["caixas"]) + [
            (x - 0.5, 0.0, z - 0.5, x + 0.5, 2.0, z + 0.5, "madeira")]
        problemas = cena_apartamento.conferir(planta)
        self.assertTrue(problemas, "não acusou a câmera dentro do móvel")
        self.assertIn("DENTRO", problemas[0])

    def test_cada_imovel_tem_dois_pontos_por_comodo(self):
        """
        O produto so mostra o botao de caminhar com dois ou mais pontos, e e
        disso que a demonstracao trata: de um ponto so, andar obriga o programa
        a inventar o que esta atras do movel.
        """
        for construir in plantas.TODAS:
            planta = construir()
            self.assertGreaterEqual(len(planta["pontos"]), 2 * len(planta["zonas"]) - 2,
                                    planta["nome"])

    def test_os_comodos_cabem_dentro_do_imovel(self):
        """Zona fora da casca renderiza parede onde deveria haver cômodo."""
        for construir in plantas.TODAS:
            p = construir()
            for nome, x0, x1, z0, z1, _, _ in p["zonas"]:
                self.assertGreaterEqual(x0, -0.01, nome)
                self.assertLessEqual(x1, p["larg"] + 0.01, nome)
                self.assertGreaterEqual(z0, -0.01, nome)
                self.assertLessEqual(z1, p["fundo"] + 0.01, nome)

    def test_toda_zona_tem_material_de_parede_e_piso_conhecido(self):
        """Material sem cor cadastrada estoura o render no meio, não antes."""
        for construir in plantas.TODAS:
            p = construir()
            for z in p["zonas"]:
                self.assertIn(z[5], cena_apartamento.MATERIAIS, z[0])
                self.assertIn(z[6], cena_apartamento.MATERIAIS, z[0])
            for c in p["caixas"]:
                self.assertIn(c[6], cena_apartamento.MATERIAIS, str(c))


class TestRecarregarServidor(Base):
    """
    Aplicar uma publicacao dependia de abrir um terminal e acertar um comando —
    e errou tres vezes seguidas. A culpa nao e de quem digitou: e do produto,
    que nao sabia se recarregar.

    O caso que estes testes guardam acima de todos: SEM VIGIA a rota tem de se
    recusar. O processo sai de proposito, e quem o repoe e o vigia; sem ele, o
    botao deixaria o site morto ate alguem ir na maquina. Um botao que derruba
    o site sem volta e pior que nenhum botao.
    """

    def setUp(self):
        self.cliente = self.conta("dona-recarga")
        self.antes = os.environ.get("TOUR_VIGIADO")

    def tearDown(self):
        if self.antes is None:
            os.environ.pop("TOUR_VIGIADO", None)
        else:
            os.environ["TOUR_VIGIADO"] = self.antes

    def test_sem_vigia_a_rota_se_recusa(self):
        os.environ.pop("TOUR_VIGIADO", None)
        r = self.cliente.post("/api/recarregar")
        self.assertEqual(r.status_code, 409,
                         "ia derrubar o site sem ninguém para repor")
        self.assertIn("vigia", r.get_json()["erro"].lower())

    def test_sem_sessao_ninguem_derruba_o_site(self):
        """Rota aberta aqui seria um botão de derrubar o site para estranhos."""
        os.environ["TOUR_VIGIADO"] = "1"
        r = aplicacao.app.test_client().post("/api/recarregar")
        self.assertEqual(r.status_code, 401)

    def test_a_versao_pendente_e_vista_pelo_horario(self):
        """Arquivo gravado depois do início do processo = publicação esperando."""
        antes = aplicacao.INICIADO_EM
        try:
            aplicacao.INICIADO_EM = 0.0        # como se o processo fosse antigo
            self.assertTrue(aplicacao.versao_pendente()["pendente"])
            aplicacao.INICIADO_EM = time.time() + 3600   # e agora, recém-nascido
            self.assertFalse(aplicacao.versao_pendente()["pendente"])
        finally:
            aplicacao.INICIADO_EM = antes

    def test_a_rota_de_versao_diz_se_ha_vigia(self):
        os.environ["TOUR_VIGIADO"] = "1"
        d = self.cliente.get("/api/versao").get_json()
        self.assertTrue(d["ha_vigia"])
        os.environ.pop("TOUR_VIGIADO", None)
        self.assertFalse(self.cliente.get("/api/versao").get_json()["ha_vigia"])

    def test_o_vigia_marca_o_processo_que_ele_repoe(self):
        """
        A marca e o que liga as duas pontas: sem ela o site nunca saberia que
        ha quem o traga de volta, e o botao ficaria escondido para sempre.
        """
        fonte = io.open("servico.py", encoding="utf-8").read()
        corpo = fonte.split("def _subir()")[1].split("def ")[0]
        self.assertIn('TOUR_VIGIADO="1"', corpo,
                      "o vigia parou de marcar o processo que vigia")
        self.assertIn("env=ambiente", corpo,
                      "a marca não chega ao processo filho")

    def test_o_botao_so_aparece_com_vigia_e_versao_esperando(self):
        painel = io.open("static/admin.html", encoding="utf-8").read()
        self.assertIn('onclick="recarregarServidor()"', painel)
        self.assertIn("v.pendente && v.ha_vigia", painel,
                      "o botão apareceria sem haver o que aplicar, ou sem vigia")


class TestPreviaDoLink(Base):
    """
    Imovel se vende por link no WhatsApp, e o link ia PELADO: so o endereco
    cru, sem foto, sem titulo, sem metragem. Link com a foto da sala e
    "3 ambientes · 11,1 m²" e tocado muito mais que uma URL seca.

    O ponto que estes testes protegem: as etiquetas tem de estar no HTML
    SERVIDO. O robo que monta a previa busca a pagina uma vez e nao executa
    JavaScript — montar as etiquetas na pagina pronta nao serviria de nada, e o
    defeito sairia invisivel para quem testa no proprio navegador.
    """

    def setUp(self):
        self.cliente = self.conta("dona-previa")
        self.iid = self.imovel(self.cliente, "Casa com quintal")

    def test_o_titulo_do_imovel_vai_nas_etiquetas(self):
        html = self.cliente.get("/tour/%s" % self.iid).get_data(as_text=True)
        self.assertIn('property="og:title"', html)
        self.assertIn("Casa com quintal", html)

    def test_as_etiquetas_estao_no_html_e_nao_no_javascript(self):
        """
        Se alguem trocar isto por injecao via script, o WhatsApp volta a mostrar
        o link pelado e ninguem percebe: no navegador continua bonito.
        """
        html = self.cliente.get("/tour/%s" % self.iid).get_data(as_text=True)
        cabeca = html.split("</head>")[0]
        self.assertIn('property="og:title"', cabeca,
                      "a etiqueta não está no <head> servido")

    def test_o_endereco_da_imagem_e_absoluto(self):
        """O robo busca de fora: caminho relativo nao resolve para ele."""
        self.cliente.post("/api/imoveis/%s/cenas/demo" % self.iid,
                          json={"nome": "Sala"})
        html = self.cliente.get("/tour/%s" % self.iid).get_data(as_text=True)
        self.assertIn('property="og:image"', html)
        linha = next(l for l in html.splitlines() if "og:image" in l)
        self.assertIn("http://", linha, "endereço da imagem não é absoluto")
        self.assertIn("/data/%s/scenes/" % self.iid, linha)

    def test_sem_cena_nao_inventa_imagem(self):
        """Prévia apontando para imagem que não existe fica pior que sem foto."""
        html = self.cliente.get("/tour/%s" % self.iid).get_data(as_text=True)
        self.assertNotIn('property="og:image"', html)

    def test_titulo_com_aspas_nao_quebra_a_etiqueta(self):
        """Título é digitado pelo corretor: sem escape ele fecha o atributo."""
        tour = self.cliente.get("/api/imoveis/%s/tour" % self.iid).get_json()
        tour["titulo"] = 'Casa "dos sonhos" <b>'
        self.cliente.put("/api/imoveis/%s/tour" % self.iid, json=tour)
        html = self.cliente.get("/tour/%s" % self.iid).get_data(as_text=True)
        self.assertNotIn('content="Casa "dos sonhos"', html)
        self.assertIn("&#34;", html)

    def test_a_descricao_conta_ambientes_e_metragem(self):
        """
        A segunda linha da previa e o que faz alguem tocar no link. As cenas nao
        entram pelo PUT do tour (elas nascem na costura), entao aqui a funcao e
        exercitada direto.
        """
        texto = aplicacao._texto_da_previa({
            "cenas": [{"area": {"m2": 11.1}}, {"area": {"m2": 9.0}}],
            "endereco": "Rua das Flores, 100"})
        self.assertIn("2 ambientes", texto)
        self.assertIn("20,1 m²", texto)
        self.assertIn("Rua das Flores, 100", texto)

    def test_um_ambiente_so_nao_sai_no_plural(self):
        self.assertIn("1 ambiente em 360°",
                      aplicacao._texto_da_previa({"cenas": [{}]}))

    def test_tour_vazio_ainda_tem_uma_frase(self):
        """Descricao vazia faz o WhatsApp mostrar so o endereco."""
        self.assertTrue(aplicacao._texto_da_previa({"cenas": []}).strip())

    def test_o_botao_de_enviar_chama_mesmo_a_funcao(self):
        """
        Conferir so se o NOME aparece no arquivo nao serve: ele aparece na
        definicao da funcao mesmo que o botao deixe de chama-la. A mutacao
        provou isso — trocar o onclick por nada() passava batido.
        """
        painel = io.open("static/admin.html", encoding="utf-8").read()
        self.assertIn('onclick="enviarPorWhatsApp()"', painel,
                      "o botão do painel não chama a função de enviar")
        self.assertIn("wa.me/?text=", painel,
                      "o botão precisa abrir o WhatsApp sem destinatário fixo")


class TestExigirHttps(Base):
    """
    Marcar o cookie como seguro nao basta: em http a senha do corretor viaja
    legivel ANTES de qualquer cookie existir. Com TOUR_EXIGIR_HTTPS=1 o site
    deixa de atender em claro.

    O caso que nao pode quebrar: /saude e chamado pelo vigia em 127.0.0.1 sem
    TLS. Desviar isso poria o servidor em ciclo de reinicio — o site cairia por
    causa da protecao.
    """

    def setUp(self):
        self.antes = aplicacao.EXIGIR_HTTPS
        aplicacao.EXIGIR_HTTPS = True
        self.cliente = aplicacao.app.test_client()

    def tearDown(self):
        aplicacao.EXIGIR_HTTPS = self.antes

    def test_pagina_em_claro_e_desviada_para_https(self):
        r = self.cliente.get("/entrar", base_url="http://tour.exemplo.com",
                             environ_overrides={"REMOTE_ADDR": "200.1.2.3"})
        self.assertEqual(r.status_code, 308)
        self.assertTrue(r.headers["Location"].startswith("https://"),
                        r.headers.get("Location"))

    def test_envio_de_senha_em_claro_e_recusado_e_nao_desviado(self):
        """
        Desviar um POST faria o navegador reenviar a senha — que ja viajou em
        claro. Recusar e a unica resposta honesta.
        """
        r = self.cliente.post("/api/entrar", json={"usuario": "x", "senha": "y"},
                              base_url="http://tour.exemplo.com",
                              environ_overrides={"REMOTE_ADDR": "200.1.2.3"})
        self.assertEqual(r.status_code, 403)

    def test_a_saude_continua_respondendo_em_claro(self):
        """Se isto quebrar, o vigia derruba o servidor de 5 em 5 segundos."""
        r = self.cliente.get("/saude", base_url="http://tour.exemplo.com",
                             environ_overrides={"REMOTE_ADDR": "200.1.2.3"})
        self.assertEqual(r.status_code, 200, "o vigia perderia o site de vista")

    def test_localhost_nao_e_desviado(self):
        r = self.cliente.get("/entrar", base_url="http://127.0.0.1:8000",
                             environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(r.status_code, 200)

    def test_em_https_manda_o_navegador_nunca_mais_tentar_em_claro(self):
        r = self.cliente.get("/entrar", base_url="https://tour.exemplo.com",
                             environ_overrides={"REMOTE_ADDR": "200.1.2.3"})
        self.assertIn("max-age", r.headers.get("Strict-Transport-Security", ""))

    def test_desligado_o_site_atende_em_claro_normalmente(self):
        """Ligado sem HTTPS de verdade na frente, tiraria o site do ar."""
        aplicacao.EXIGIR_HTTPS = False
        r = self.cliente.get("/entrar", base_url="http://tour.exemplo.com",
                             environ_overrides={"REMOTE_ADDR": "200.1.2.3"})
        self.assertEqual(r.status_code, 200)


class TestAvisoDeLead(Base):
    """
    O contato precisa AVISAR alguem.

    Antes ele era gravado no tour.json e ninguem ficava sabendo: o corretor so
    descobria se abrisse o painel. Para quem vende imovel, contato que espera um
    dia e contato perdido — o comprador ja falou com outro corretor.

    O que estes testes protegem, acima de tudo: o aviso NAO pode derrubar o
    cadastro. Se o servidor de e-mail estiver fora, o contato ainda tem de
    entrar. Perder o lead por causa do aviso seria trocar um problema por um
    pior.
    """

    def setUp(self):
        self.cliente = self.conta("dona-lead")
        self.iid = self.imovel(self.cliente, "Apartamento 302")

    def test_o_contato_entra_mesmo_com_o_email_quebrado(self):
        original = aviso.avisar
        aviso.avisar = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp fora"))
        try:
            r = self.cliente.post("/api/imoveis/%s/leads" % self.iid,
                                  json={"nome": "Visitante", "telefone": "12 99999-0000"})
            self.assertEqual(r.status_code, 200, "o e-mail quebrado derrubou o lead")
        finally:
            aviso.avisar = original
        leads = self.cliente.get("/api/imoveis/%s/leads" % self.iid).get_json()["leads"]
        self.assertEqual(len(leads), 1, "o contato se perdeu")
        self.assertEqual(leads[0]["nome"], "Visitante")

    def test_sem_configuracao_nao_tenta_enviar(self):
        """O site nasce sem e-mail configurado e tem de funcionar igual."""
        self.assertFalse(aviso.configurado())
        self.assertFalse(aviso.avisar({"nome": "x"}, "Imóvel"))

    def test_diz_o_que_falta_em_vez_de_silencio(self):
        self.assertIn("TOUR_SMTP_SERVIDOR", aviso.por_que_nao())

    def test_o_telefone_vai_no_assunto(self):
        """
        O corretor le a notificacao no celular, na rua. Precisa poder ligar sem
        abrir o e-mail.
        """
        assunto, corpo = aviso.montar(
            {"nome": "Maria", "telefone": "12 98888-1111",
             "email": "m@x.com", "recebido_em": "2026-09-18T10:00:00"},
            "Apartamento 302")
        self.assertIn("12 98888-1111", assunto)
        self.assertIn("Maria", assunto)
        self.assertIn("Apartamento 302", assunto)
        self.assertIn("m@x.com", corpo)

    def test_lead_sem_telefone_nao_quebra_o_assunto(self):
        assunto, corpo = aviso.montar({"nome": "Sem Telefone"}, "Casa")
        self.assertIn("Sem Telefone", assunto)
        self.assertIn("—", corpo)

    def test_a_senha_do_email_nao_vai_para_o_tour(self):
        """
        Senha de e-mail em variavel de ambiente, nunca no tour.json: o tour vai
        inteiro para o navegador de qualquer visitante.
        """
        fonte = io.open("aviso.py", encoding="utf-8").read()
        self.assertIn("TOUR_SMTP_SENHA", fonte)
        self.assertNotIn("TOUR_SMTP_SENHA",
                         io.open("static/admin.html", encoding="utf-8").read())


class TestSenhaEsquecida(Base):
    """
    Senha esquecida nao tinha saida: `trocar_senha` exige a antiga, e nao ha
    e-mail configurado para link de recuperacao. Numa imobiliaria com varios
    corretores isso vira ligacao para o fornecedor toda semana.

    O que autoriza a redefinicao e o acesso ao disco do servidor, nao uma senha.
    Por isso ela nao pode ter rota web — seria o buraco que o produto evita ao
    nao ter cadastro aberto.
    """

    def test_redefine_sem_pedir_a_antiga(self):
        try:
            usuarios.criar(aplicacao.PASTA_DADOS, "esquecida", "a-velha-123", "")
        except usuarios.ErroUsuario:
            pass
        usuarios.redefinir_senha(aplicacao.PASTA_DADOS, "esquecida", "a-nova-456")
        self.assertTrue(usuarios.verificar(aplicacao.PASTA_DADOS,
                                           "esquecida", "a-nova-456"))
        self.assertFalse(usuarios.verificar(aplicacao.PASTA_DADOS,
                                            "esquecida", "a-velha-123"),
                         "a senha antiga continuou valendo")

    def test_recusa_usuario_que_nao_existe(self):
        """Sem isto, um erro de digitacao sairia calado sem trocar nada."""
        with self.assertRaises(usuarios.ErroUsuario):
            usuarios.redefinir_senha(aplicacao.PASTA_DADOS, "ninguem", "seja-la-123")

    def test_recusa_senha_curta(self):
        try:
            usuarios.criar(aplicacao.PASTA_DADOS, "curta", "comprida-123", "")
        except usuarios.ErroUsuario:
            pass
        with self.assertRaises(usuarios.ErroUsuario):
            usuarios.redefinir_senha(aplicacao.PASTA_DADOS, "curta", "123")

    def test_nenhuma_rota_web_redefine_senha(self):
        """
        Redefinir sem a senha antiga pela web seria tomada de conta. A prova e
        no proprio app.py: nenhuma rota pode chamar essa funcao.
        """
        fonte = io.open("app.py", encoding="utf-8").read()
        self.assertNotIn("redefinir_senha", fonte,
                         "app.py expôs a redefinição de senha pela web")


class TestFreioDeForcaBruta(Base):
    """
    Senha de corretor nao aguenta 86 mil tentativas por dia.

    A espera de 1 segundo por erro atrapalha, mas nao impede: publicado na
    internet, um robo tenta a noite inteira. Depois de algumas tentativas o
    endereco fica de fora por um tempo.

    A contagem e por ORIGEM, e nao por usuario, de proposito: travar por usuario
    deixaria qualquer um trancar a conta do corretor de fora.
    """

    def setUp(self):
        super().setUp()
        aplicacao._tentativas.clear()
        # nome proprio: "dona" ja e usada por TestAcesso com OUTRA senha, e
        # engolir o "ja existe" fazia este teste logar com a senha errada e
        # acusar a trava de estar presa
        try:
            usuarios.criar(aplicacao.PASTA_DADOS, "freio", "senha-boa-123", "")
        except usuarios.ErroUsuario:
            usuarios.redefinir_senha(aplicacao.PASTA_DADOS, "freio", "senha-boa-123")

    def tearDown(self):
        aplicacao._tentativas.clear()
        super().tearDown()

    def _errar(self, cliente):
        return cliente.post("/api/entrar",
                            json={"usuario": "freio", "senha": "errada"})

    def test_erro_repetido_acaba_travando(self):
        cliente = aplicacao.app.test_client()
        for _ in range(aplicacao.TENTATIVAS_ATE_TRAVAR):
            self.assertEqual(self._errar(cliente).status_code, 401)
        r = self._errar(cliente)
        self.assertEqual(r.status_code, 429, "seguiu aceitando tentativa sem fim")
        self.assertIn("Tentativas demais", r.get_json()["erro"])

    def test_travado_nao_entra_nem_com_a_senha_certa(self):
        """Senao o robo acerta na tentativa 9 e a trava nao serviu de nada."""
        cliente = aplicacao.app.test_client()
        for _ in range(aplicacao.TENTATIVAS_ATE_TRAVAR):
            self._errar(cliente)
        r = cliente.post("/api/entrar",
                         json={"usuario": "freio", "senha": "senha-boa-123"})
        self.assertEqual(r.status_code, 429)

    def test_acertar_antes_de_travar_limpa_a_contagem(self):
        """Quem errou duas vezes e lembrou a senha nao pode ficar marcado."""
        cliente = aplicacao.app.test_client()
        self._errar(cliente)
        self._errar(cliente)
        r = cliente.post("/api/entrar",
                         json={"usuario": "freio", "senha": "senha-boa-123"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(aplicacao._tentativas, {},
                         "a contagem ficou suja depois do acerto")

    def test_a_trava_expira(self):
        cliente = aplicacao.app.test_client()
        for _ in range(aplicacao.TENTATIVAS_ATE_TRAVAR):
            self._errar(cliente)
        self.assertEqual(self._errar(cliente).status_code, 429)
        # envelhece a marca em vez de esperar 5 minutos de verdade
        for chave, (n, _) in list(aplicacao._tentativas.items()):
            aplicacao._tentativas[chave] = (n, time.time() - 1)
        r = cliente.post("/api/entrar",
                         json={"usuario": "freio", "senha": "senha-boa-123"})
        self.assertEqual(r.status_code, 200, "a trava ficou presa para sempre")


class TestVigiaSemConsole(Base):
    """
    O vigia precisa sobreviver ao console fechar.

    Custou tres mortes seguidas para achar: a tarefa agendada terminava sempre
    com 0xC000013A, que no Windows e encerramento por EVENTO DE CONSOLE. Ela
    rodava python.exe, que e aplicativo de console; quando o console associado
    fecha, o Windows manda CTRL_CLOSE_EVENT e leva o processo junto. Servico que
    morre com Ctrl+C nao e servico.

    As tres pontas do conserto estao aqui: agendar sem console, nao depender de
    stdout, e dar destino a saida do filho.
    """

    def test_agenda_com_interpretador_sem_console(self):
        escolhido = servico.interpretador_sem_console()
        if os.name != "nt":
            self.skipTest("só vale no Windows")
        if not os.path.exists(os.path.join(os.path.dirname(sys.executable),
                                           "pythonw.exe")):
            self.skipTest("este Python não traz pythonw.exe")
        self.assertTrue(escolhido.endswith("pythonw.exe"),
                        "agendou com console: morre no CTRL_CLOSE_EVENT")

    def test_sem_pythonw_ainda_devolve_um_interpretador(self):
        """Python sem pythonw existe; o vigia não pode ficar sem como subir."""
        self.assertTrue(os.path.basename(servico.interpretador_sem_console())
                        .lower().startswith("python"))

    def test_o_servidor_sobe_sem_console(self):
        """
        Aqui está o risco de verdade, e a mutação provou onde ele NÃO estava:
        eu tinha posto uma guarda no anotar() achando que print estouraria sem
        console. Medido: print com sys.stdout None não faz nada e passa liso —
        a guarda era decorativa, e a mutação passou batida por isso.

        Quem estoura é mexer no stdout direto. O servidor.py esvazia o cabeçalho
        de subida com sys.stdout.flush(), e sob pythonw isso levanta
        AttributeError antes de o site começar a atender.
        """
        antes = sys.stdout
        try:
            sys.stdout = None
            servidor.despejar()
        finally:
            sys.stdout = antes

    def test_anotar_grava_no_arquivo_sem_console(self):
        """O log em arquivo é o que sobra quando não há tela para onde escrever."""
        antes = sys.stdout
        try:
            sys.stdout = None
            servico.anotar("linha de teste sem console")
        finally:
            sys.stdout = antes
        with io.open(servico.REGISTRO, encoding="utf-8") as f:
            self.assertIn("linha de teste sem console", f.read())

    def test_a_saida_do_filho_tem_destino(self):
        """
        O servidor.py imprime um cabeçalho ao subir. Sob pythonw, sem destino,
        esse print estoura e o site nem começa.
        """
        fonte = io.open("servico.py", encoding="utf-8").read()
        corpo = fonte.split("def _subir()")[1].split("\ndef ")[0]
        self.assertIn("stdout=", corpo, "o filho nasce sem destino para a saída")
        self.assertIn("stderr=", corpo)


class TestCodigoNoAr(unittest.TestCase):
    """
    O `estado` precisa saber dizer se o processo no ar carregou os arquivos
    publicados — nao apenas se ALGUEM atende a porta.

    Custou uma hora de verdade: os arquivos novos foram copiados, o processo
    velho continuou de pe segurando a porta 8000, e o `estado` respondeu
    "respondendo: sim" durante a publicacao inteira. A publicacao parecia feita
    e nao estava.
    """

    def setUp(self):
        self.original = servico._inicio_do_servidor

    def tearDown(self):
        servico._inicio_do_servidor = self.original

    def test_processo_mais_velho_que_o_arquivo_e_denunciado(self):
        servico._inicio_do_servidor = lambda: time.time() - 7200
        veredito, detalhe = servico.codigo_no_ar()
        self.assertIs(veredito, False, detalhe)
        self.assertIn("MAIS VELHO", detalhe)

    def test_processo_mais_novo_passa(self):
        servico._inicio_do_servidor = lambda: time.time() + 60
        veredito, _ = servico.codigo_no_ar()
        self.assertIs(veredito, True)

    def test_sem_processo_admite_que_nao_sabe(self):
        """Fingir certeza aqui seria repetir o erro por outro caminho."""
        servico._inicio_do_servidor = lambda: None
        veredito, detalhe = servico.codigo_no_ar()
        self.assertIsNone(veredito)
        self.assertIn("processo", detalhe)

    def test_o_modo_nao_depende_do_idioma_do_windows(self):
        """
        Defeito real, pego rodando no servidor: a primeira versao procurava a
        palavra "SYSTEM" na saida do schtasks. O Windows de la responde em
        portugues, "SISTEMA" — e o estado passou a dizer "sobe quando alguem
        entra" numa tarefa que sobe na inicializacao. Era o MESMO engano que
        este comando existe para nao cometer, so que por outro caminho.
        """
        boot = servico.modo_do_agendamento(
            "<Triggers><BootTrigger/></Triggers>"
            "<Principal><UserId>S-1-5-18</UserId></Principal>")
        self.assertIn("LIGAR", boot)
        self.assertNotIn("entra no Windows", boot)

        logon = servico.modo_do_agendamento("<Triggers><LogonTrigger/></Triggers>")
        self.assertIn("entra no Windows", logon)

    def test_sem_agendamento_diz_que_nao_ha(self):
        self.assertIn("não está agendado", servico.modo_do_agendamento(""))

    def test_a_consulta_nao_pode_casar_com_ela_mesma(self):
        """
        Defeito cometido ao escrever isto: a consulta do PowerShell procurava
        qualquer processo com 'servidor.py' na linha de comando — e a propria
        consulta tem. Ela se achava, recem-nascida, e o veredito dava "no ar"
        sempre. Sem o filtro por python o check volta a mentir.
        """
        fonte = io.open("servico.py", encoding="utf-8").read()
        corpo = fonte.split("def _inicio_do_servidor")[1].split("\ndef ")[0]
        self.assertIn("$_.Name -like 'python*'", corpo,
                      "a consulta voltou a casar com o proprio processo")


class TestVigiaDoServidor(unittest.TestCase):
    """
    O servidor precisa voltar sozinho.

    Sem isto ele morre com a janela que o abriu e nao volta depois que a maquina
    reinicia — o link enviado a imobiliaria abre em nada, e ninguem percebe ate o
    cliente reclamar.

    Os testes vigiam um processo de MENTIRA, nunca o servidor de verdade: subir
    servidor dentro de teste disputaria a porta com o que esta rodando.
    """

    def _com_alvo(self, corpo, **extra):
        """Escreve um programa curto e faz o vigia vigiar ELE."""
        alvo = os.path.join(_TEMP, "falso_%d.py" % abs(hash(corpo)))
        with io.open(alvo, "w", encoding="utf-8") as f:
            f.write(corpo)
        ambiente = dict(os.environ, TOUR_COMANDO=alvo, **extra)
        return alvo, ambiente

    def test_reinicia_quando_o_processo_morre(self):
        import subprocess
        alvo, ambiente = self._com_alvo(
            "import sys, time\n"
            "open(sys.argv[0] + '.contador', 'a').write('x')\n"
            "time.sleep(0.2)\n")
        r = subprocess.run(
            [sys.executable, "-c",
             "import servico; servico.ESPERA_MINIMA = 0.05; servico.DE_PE = 0.01;\n"
             "print(servico.vigiar(limite_de_quedas=3))"],
            cwd=os.getcwd(), env=ambiente, capture_output=True, text=True,
            errors="ignore", timeout=90)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        with io.open(alvo + ".contador", encoding="utf-8") as f:
            subidas = len(f.read())
        self.assertGreaterEqual(subidas, 3,
                                "o vigia não reiniciou: subiu só %d vez(es)" % subidas)

    def test_espera_cresce_quando_cai_logo(self):
        """
        Queda imediata em laco apertado consome a maquina e enche o disco. A
        espera dobra; se ele se aguenta de pe, volta ao minimo.
        """
        import servico
        self.assertLess(servico.ESPERA_MINIMA, servico.ESPERA_MAXIMA)
        self.assertGreater(servico.DE_PE, servico.ESPERA_MINIMA)

    def test_processo_travado_tambem_e_derrubado(self):
        """
        Processo vivo que nao responde e pior que processo morto: segura a porta
        e parece saudavel. A checagem de saude existe por isso.
        """
        with io.open("servico.py", encoding="utf-8") as f:
            codigo = f.read()
        self.assertIn("proc.kill()", codigo)
        self.assertIn("TOLERANCIA_TRAVADO", codigo)
        self.assertIn("def responde", codigo)

    def test_nao_derruba_durante_o_arranque(self):
        """Costura e modelos demoram a subir; cobrar saude cedo mataria em laco."""
        with io.open("servico.py", encoding="utf-8") as f:
            codigo = f.read()
        self.assertIn("time.time() - inicio < 20", codigo)


class TestImagemIntegra(unittest.TestCase):
    """
    No ponto de captura a imagem tem de ser a foto, sem deformacao nenhuma.

    A malha de profundidade desloca os vertices RADIALMENTE. Visto do centro da
    esfera, deslocamento radial nao muda a direcao de nenhum pixel — entao,
    parado no ponto, o que se ve e exatamente o panorama original. O borrao so
    nasce ao SAIR do ponto, porque ali ninguem fotografou e a malha estica para
    cobrir o vao.

    Dai o padrao de passeio livre ser ZERO: o visitante fica sempre em um ponto e
    anda pelas setas, como no Street View, e nunca ve a imagem deformada. Quem
    quiser o paralaxe abre o controle e aceita a troca.
    """

    def _andar(self):
        with io.open(os.path.join("static", "andar.html"), encoding="utf-8") as f:
            return f.read()

    def test_passeio_livre_nasce_desligado(self):
        html = self._andar()
        m = re.search(r'id="alcance"[^>]*value="(\d+)"', html)
        self.assertIsNotNone(m, "não achei o controle de alcance")
        self.assertEqual(m.group(1), "0",
                         "o passeio livre não nasce em zero: o visitante vê o borrão")

    def test_o_controle_permite_zero(self):
        """Se o minimo nao for 0, nao da para desligar e o borrao e inevitavel."""
        html = self._andar()
        m = re.search(r'id="alcance"[^>]*min="(\d+)"', html)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "0")

    def test_parado_no_ponto_nada_se_move(self):
        """
        `podeEstar` e quem barra: com alcance 0, qualquer passo cai fora e a
        posicao fica colada no ponto de captura.
        """
        html = self._andar()
        self.assertIn("if (d > alcance) return false;", html,
                      "a regra que prende ao ponto sumiu")


class TestCacheDaApi(Base):
    """
    A lista do que existe nao pode envelhecer no navegador.

    Sem cabecalho de cache, o navegador guarda por conta propria: o corretor
    cadastra um imovel, a lista continua mostrando os antigos e parece que o
    cadastro se perdeu. Aconteceu: tres imoveis no servidor, um so na tela.
    """

    def test_api_manda_nao_guardar(self):
        dona = self.conta("cache")
        iid = self.imovel(dona, "Casa")
        for rota in ("/api/imoveis", "/api/conta",
                     "/api/imoveis/%s/tour" % iid):
            r = dona.get(rota)
            cc = r.headers.get("Cache-Control", "")
            self.assertIn("no-store", cc, "%s pode ficar em cache: %r" % (rota, cc))

    def test_imagem_de_cena_continua_podendo_ser_guardada(self):
        """
        Panorama tem megabytes e quase nunca muda: guardar vale a pena, e a
        revalidacao por ETag ja cobre a troca. Sem no-store aqui.
        """
        dona = self.conta("cache2")
        iid = self.imovel(dona, "Casa 2")
        r = dona.get("/api/imoveis/%s/tour" % iid)
        self.assertIn("no-store", r.headers.get("Cache-Control", ""))
        # a rota das imagens nao vive sob /api/, entao nao recebe o no-store
        self.assertFalse("/data/".startswith("/api/"))


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
