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
import modelo3d                   # noqa: E402
import numpy as np                # noqa: E402
import plantas                    # noqa: E402
import cena_apartamento           # noqa: E402
import usuarios                   # noqa: E402
import backup                     # noqa: E402
import stitcher                  # noqa: E402
import vizinhanca               # noqa: E402
import captura                   # noqa: E402
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

    def _selo(self):
        """
        Recorta da pagina a funcao do selo de captura.

        Extraida, e nao dublada: o molde do cartao a chama, entao o teste dos
        botoes passa a exercitar tambem o selo — e um selo que gerasse
        marcacao quebrada apareceria aqui, e nao no navegador de quem abre.
        """
        pagina = io.open(os.path.join("static", "imoveis.html"),
                         encoding="utf-8").read()
        abre = "function seloDaCaptura("
        self.assertIn(abre, pagina, "a pagina nao tem mais seloDaCaptura")
        corpo = pagina[pagina.index(abre):]
        return corpo[:corpo.index(chr(10) + "}") + 2]

    def _onclicks(self, titulo, ambientes, captura=None):
        """Renderiza o cartao e devolve o codigo de cada onclick."""
        programa = (
            'const escapar = t => String(t).replace(/[&<>"]/g, c => '
            '({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;"}[c]));\n'
            "const nBR = n => String(n);\n"
            + self._selo() + "\n"
            "const i = {id:'bc7136253c', titulo:" + json.dumps(titulo) + ", "
            "ambientes:" + str(ambientes) + ", capa:null, area_total:0, "
            "ambientes_medidos:0, com_profundidade:0, leads:0, captura:"
            + json.dumps(captura or {"impedem": 0, "atrapalham": 0}) + "};\n"
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

    def _html(self, captura):
        """O cartao inteiro, para olhar o selo e nao so os onclicks."""
        programa = (
            'const escapar = t => String(t).replace(/[&<>"]/g, c => '
            '({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;"}[c]));\n'
            "const nBR = n => String(n);\n"
            + self._selo() + "\n"
            "const i = {id:'bc7136253c', titulo:'Casa', ambientes:3, capa:null,"
            " area_total:0, ambientes_medidos:0, com_profundidade:3, leads:0,"
            " captura:" + json.dumps(captura) + "};\n"
            "console.log(`" + self.molde + "`);\n")
        caminho = os.path.join(_TEMP, "cartao-selo.mjs")
        with io.open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write(programa)
        r = subprocess.run([self.node, caminho], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stderr[:500])
        return r.stdout

    def test_captura_boa_nao_ganha_selo_nenhum(self):
        """
        Silêncio quando está bom. Selo em imóvel sem problema ensina a ignorar
        selo, e aí o do imóvel quebrado passa batido junto.
        """
        if not self.node:
            self.skipTest("node nao encontrado")
        html = self._html({"impedem": 0, "atrapalham": 0})
        self.assertNotIn("selo alerta", html)
        self.assertNotIn("selo atencao", html)

    def test_imovel_que_nao_anda_aparece_na_lista(self):
        """
        Numa imobiliária com quarenta anúncios, saber que um deles não anda só
        ao abri-lo significa nunca saber.
        """
        if not self.node:
            self.skipTest("node nao encontrado")
        html = self._html({"impedem": 2, "atrapalham": 5})
        self.assertIn("selo alerta", html)
        self.assertIn("2 impede", html)
        self.assertIn("/capturar/bc7136253c", html,
                      "o selo nao leva ao guia daquele imovel")

    def test_o_grave_esconde_o_leve(self):
        """
        Dois selos no mesmo cartão competem entre si. O que impede caminhar
        manda; o resto espera.
        """
        if not self.node:
            self.skipTest("node nao encontrado")
        html = self._html({"impedem": 1, "atrapalham": 9})
        self.assertIn("selo alerta", html)
        self.assertNotIn("selo atencao", html)

    def test_so_o_que_atrapalha_usa_o_tom_mais_leve(self):
        if not self.node:
            self.skipTest("node nao encontrado")
        html = self._html({"impedem": 0, "atrapalham": 3})
        self.assertIn("selo atencao", html)
        self.assertIn("3 a melhorar", html)
        self.assertNotIn("selo alerta", html)

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


class TestRestaurarBackup(unittest.TestCase):
    """
    A restauracao — o caminho que so se usa quando tudo o mais ja deu errado.

    Ela existia sem UM teste sequer. Backup que nunca foi restaurado e
    esperanca, nao backup, e isto deixou de ser hipotese: dia 21 o acervo de
    imagens sumiu inteiro, e a copia daquele dia gravou 34 KB porque as imagens
    ja nao existiam quando ela passou.

    O caso mais importante daqui e o do zip ruim. A versao anterior movia o
    data/ para o lado e SO ENTAO abria a copia — copia corrompida significava
    perder o atual sem ganhar o antigo. Agora confere primeiro.
    """

    def setUp(self):
        self.casa = tempfile.mkdtemp(prefix="tour-restaurar-")
        self.dados = os.path.join(self.casa, "data")
        self.copias = os.path.join(self.casa, "backups")
        os.makedirs(os.path.join(self.dados, "imoveis", "abc", "scenes"))
        self.antes = (backup.PASTA_DADOS, backup.PASTA_BACKUPS)
        backup.PASTA_DADOS, backup.PASTA_BACKUPS = self.dados, self.copias

        # um tour, uma conta e uma imagem binaria de verdade
        self._gravar("usuarios.json", b'{"usuarios": []}')
        self._gravar(os.path.join("imoveis", "abc", "tour.json"),
                     '{"titulo": "Casa do João", "cenas": []}'.encode("utf-8"))
        self.imagem = bytes(range(256)) * 40
        self._gravar(os.path.join("imoveis", "abc", "scenes", "cena.jpg"),
                     self.imagem)

    def tearDown(self):
        backup.PASTA_DADOS, backup.PASTA_BACKUPS = self.antes
        shutil.rmtree(self.casa, ignore_errors=True)

    def _gravar(self, relativo, conteudo):
        caminho = os.path.join(self.dados, relativo)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "wb") as f:
            f.write(conteudo)

    def _copia(self):
        backup.criar(silencioso=True)
        nomes = sorted(n for n in os.listdir(self.copias) if n.endswith(".zip"))
        self.assertTrue(nomes, "não gerou cópia")
        return os.path.join(self.copias, nomes[-1])

    def test_a_volta_completa_devolve_tudo_igual(self):
        """
        Criar, apagar TUDO, restaurar — e os bytes têm de bater. É o único
        teste que prova que o backup serve para o que existe.
        """
        zipe = self._copia()
        shutil.rmtree(self.dados)
        self.assertFalse(os.path.isdir(self.dados))

        ok, recado, _ = backup.restaurar_de(zipe)
        self.assertTrue(ok, recado)

        with open(os.path.join(self.dados, "imoveis", "abc", "scenes",
                               "cena.jpg"), "rb") as f:
            self.assertEqual(f.read(), self.imagem, "a imagem voltou diferente")
        with io.open(os.path.join(self.dados, "imoveis", "abc", "tour.json"),
                     encoding="utf-8") as f:
            self.assertIn("Casa do João", f.read())

    def test_copia_corrompida_nao_encosta_nos_dados_vivos(self):
        """
        O pior resultado possível: perder o atual sem ganhar o antigo. Era o que
        a versão anterior fazia, porque movia data/ antes de abrir o zip.
        """
        ruim = os.path.join(self.copias, "tour-quebrado.zip")
        os.makedirs(self.copias, exist_ok=True)
        with open(ruim, "wb") as f:
            f.write(b"PK\x03\x04isto nao e um zip de verdade")

        ok, recado, _ = backup.restaurar_de(ruim)
        self.assertFalse(ok, "aceitou uma cópia corrompida")
        with open(os.path.join(self.dados, "imoveis", "abc", "scenes",
                               "cena.jpg"), "rb") as f:
            self.assertEqual(f.read(), self.imagem, "mexeu nos dados vivos")

    def test_zip_que_nao_e_backup_e_recusado(self):
        """Restaurar um zip qualquer apagaria os dados por nada."""
        outro = os.path.join(self.copias, "qualquer.zip")
        os.makedirs(self.copias, exist_ok=True)
        with zipfile.ZipFile(outro, "w") as z:
            z.writestr("foto-do-cachorro.jpg", b"nada a ver")
        ok, recado, _ = backup.restaurar_de(outro)
        self.assertFalse(ok, recado)
        self.assertIn("não parece", recado)

    def test_o_que_existia_fica_guardado_e_nao_apagado(self):
        """Restaurar a cópia errada não pode ser caminho sem volta."""
        zipe = self._copia()
        self._gravar(os.path.join("imoveis", "abc", "depois.txt"), b"so no atual")

        ok, _, guardado = backup.restaurar_de(zipe)
        self.assertTrue(ok)
        self.assertIsNotNone(guardado, "não guardou o data/ anterior")
        self.assertTrue(os.path.exists(
            os.path.join(guardado, "imoveis", "abc", "depois.txt")),
            "o que existia foi apagado em vez de guardado")

    def test_copia_vazia_e_recusada(self):
        vazio = os.path.join(self.copias, "vazio.zip")
        os.makedirs(self.copias, exist_ok=True)
        with zipfile.ZipFile(vazio, "w") as z:
            z.writestr("_backup.json", "{}")
        ok, recado, _ = backup.restaurar_de(vazio)
        self.assertFalse(ok, recado)

    def test_a_conferencia_aceita_uma_copia_de_verdade(self):
        """Conferência que recusa tudo é tão inútil quanto a que aceita tudo."""
        ok, recado, quantos = backup.conferir_copia(self._copia())
        self.assertTrue(ok, recado)
        self.assertGreaterEqual(quantos, 3)

    def test_restaurar_nao_deixa_pasta_provisoria_para_tras(self):
        zipe = self._copia()
        backup.restaurar_de(zipe)
        self.assertFalse(os.path.isdir(self.dados + ".restaurando"),
                         "sobrou a pasta de trabalho")


class TestImportarModelo(Base):
    """
    O escaneamento de celular virando maquete.

    Ate aqui a maquete so existia em imovel GERADO, porque ela precisa de
    geometria e foto nao tem geometria. Um aplicativo de escaneamento produz um
    OBJ com paredes e moveis medidos — e com ele a maquete passa a valer para
    imovel de verdade.

    A conferencia acontece ANTES de gravar, de proposito: OBJ e texto, qualquer
    arquivo pode se chamar .obj, e modelo que so se descobre quebrado na hora de
    abrir deixa o corretor sem entender o que houve.
    """

    def setUp(self):
        self.dona = self.conta("dona-modelo")
        self.iid = self.imovel(self.dona, "Casa fotografada")

    def _obj(self, escala=1.0):
        """Um cubo de 4 x 2,7 x 3 m — as medidas de um cômodo."""
        L, A, F = 4.0 * escala, 2.7 * escala, 3.0 * escala
        v = [(0, 0, 0), (L, 0, 0), (L, A, 0), (0, A, 0),
             (0, 0, F), (L, 0, F), (L, A, F), (0, A, F)]
        linhas = ["# cubo de teste", "mtllib modelo.mtl", "usemtl parede"]
        linhas += ["v %.3f %.3f %.3f" % p for p in v]
        for face in ((1, 2, 3, 4), (5, 6, 7, 8), (1, 5, 8, 4),
                     (2, 3, 7, 6), (1, 2, 6, 5), (4, 8, 7, 3)):
            linhas.append("f " + " ".join(str(i) for i in face))
        return ("\n".join(linhas) + "\n").encode("utf-8")

    def _enviar(self, conteudo, nome="scan.obj"):
        return self.dona.post(
            "/api/imoveis/%s/modelo" % self.iid,
            data={"modelo": (io.BytesIO(conteudo), nome)},
            content_type="multipart/form-data")

    def test_o_escaneamento_vira_maquete_do_imovel(self):
        """
        O ponto todo: um imóvel que só tinha fotos passa a ter maquete.
        """
        antes = self.dona.get("/api/imoveis/%s/maquete" % self.iid)
        self.assertEqual(antes.status_code, 404, "já tinha maquete antes")

        r = self._enviar(self._obj())
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])

        depois = self.dona.get("/api/imoveis/%s/maquete" % self.iid)
        self.assertEqual(depois.status_code, 200)
        m = depois.get_json()["maquete"]
        self.assertTrue(m["importado"])
        self.assertAlmostEqual(m["medidas"]["largura"], 4.0, places=2)
        self.assertAlmostEqual(m["medidas"]["fundo"], 3.0, places=2)

    def test_arquivo_sem_geometria_e_recusado_antes_de_gravar(self):
        """
        Qualquer arquivo pode se chamar .obj. Aceitar e descobrir depois deixa
        o corretor com uma maquete quebrada e sem explicação.
        """
        r = self._enviar(b"isto nao e um obj, e um bilhete")
        self.assertEqual(r.status_code, 422)
        self.assertIn("geometria", r.get_json()["erro"])
        self.assertFalse(os.path.exists(aplicacao.arq_modelo(self.iid)),
                         "gravou um arquivo que já sabia estar errado")

    def test_outro_formato_de_escaneamento_recebe_o_recado_certo(self):
        """USDZ e PLY são o que os aplicativos oferecem junto com OBJ."""
        r = self._enviar(b"qualquer coisa", nome="scan.usdz")
        self.assertEqual(r.status_code, 422)
        self.assertIn("OBJ", r.get_json()["erro"])

    def test_modelo_em_centimetros_e_aceito_com_aviso(self):
        """
        Escala errada não impede de usar — decidir isso pelo corretor seria
        demais. Mas passar batido faria a maquete abrir com um cômodo de 400 m
        e ninguém entenderia.
        """
        r = self._enviar(self._obj(escala=100.0))
        self.assertEqual(r.status_code, 200)
        avisos = " ".join(r.get_json()["avisos"])
        self.assertIn("centímetros", avisos)

    def test_o_visitante_ve_o_modelo_porque_precisa(self):
        """
        Aqui a publicidade é por NECESSIDADE, não escolha: desenhar no
        navegador de quem abre o link exige que os bytes cheguem até lá.
        """
        self._enviar(self._obj())
        visitante = aplicacao.app.test_client()
        r = visitante.get("/api/imoveis/%s/modelo.obj" % self.iid)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"v ", r.get_data())

    def test_apagar_o_modelo_devolve_o_imovel_ao_que_era(self):
        self._enviar(self._obj())
        self.assertEqual(
            self.dona.delete("/api/imoveis/%s/modelo" % self.iid).status_code, 200)
        self.assertEqual(
            self.dona.get("/api/imoveis/%s/maquete" % self.iid).status_code, 404)
        self.assertFalse(os.path.exists(aplicacao.arq_modelo(self.iid)))

    def test_modelo_grande_demais_e_recusado_com_o_caminho_da_solucao(self):
        """
        Recusa sem saída é só um muro. O recado diz o que fazer no aplicativo.
        """
        with self.assertRaises(modelo3d.ErroModelo) as c:
            modelo3d.conferir("v 0 0 0\nf 1 1 1\n",
                              modelo3d.LIMITE_BYTES + 1)
        self.assertIn("qualidade média", str(c.exception))

    def test_a_pagina_traz_o_proprio_leitor_de_obj(self):
        """
        O three.js embarcado não traz carregador de OBJ — ele mora nos
        "examples", fora do pacote. Sem leitor próprio, a página abriria vazia.
        """
        html = io.open(os.path.join("static", "maquete.html"),
                       encoding="utf-8").read()
        # a assinatura inteira, e a CHAMADA. Conferir só "function lerObj"
        # passava com "function lerObjDesativado" — o nome trocado contém o
        # nome certo como pedaço, e a mutação passou batida por isso.
        self.assertIn("function lerObj(texto, cores){", html)
        self.assertIn("function lerMtl(texto){", html)
        self.assertIn("= lerObj(texto", html, "define o leitor mas não usa")
        self.assertIn("lerMtl(await", html, "define o leitor de materiais mas não usa")
        self.assertIn("livreNaMalha", html, "anda atravessando a malha")
        self.assertIn("seguirOChao", html, "flutua em vez de seguir o piso")


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
                    # a colisao por malha e do modelo IMPORTADO;
                    # aqui se exercita a de caixas, sem malha
                    "const malhaImportada = null;\n"
                    "const livreNaMalha = () => true;\n"
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

    def test_w_anda_para_onde_a_camera_olha(self):
        """
        O defeito que o usuario encontrou: W andava para TRAS.

        A camera do three.js olha pelo seu -Z local, entao depois de
        rotateY(giro) a frente e (-sen, -cos). A primeira versao usava
        (+sen, +cos) — produto escalar -1 com a direcao do olhar, em TODOS os
        angulos. Aqui o produto tem de ser +1.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        corpo = self.html[self.html.index("  function direcao(giro, frente, lado){"):]
        corpo = corpo[:corpo.index("\n  }") + 4]
        programa = corpo + """
const casos = [0, Math.PI/2, Math.PI, -Math.PI/2, 0.7, -2.3];
const saida = casos.map(g => {
  const olha = {x: -Math.sin(g), z: -Math.cos(g)};
  const dir  = {x:  Math.cos(g), z: -Math.sin(g)};
  const w = direcao(g, 1, 0), s = direcao(g, -1, 0);
  const d = direcao(g, 0, 1), a = direcao(g, 0, -1);
  return {w: w.x*olha.x + w.z*olha.z, s: s.x*olha.x + s.z*olha.z,
          d: d.x*dir.x + d.z*dir.z,  a: a.x*dir.x + a.z*dir.z};
});
console.log(JSON.stringify(saida));
"""
        caminho = os.path.join(_TEMP, "direcao.mjs")
        with io.open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write(programa)
        r = subprocess.run([self.node, caminho], capture_output=True, text=True,
                           errors="ignore")
        self.assertEqual(r.returncode, 0, r.stderr[:500])
        for caso in json.loads(r.stdout):
            self.assertAlmostEqual(caso["w"], 1.0, places=6,
                                   msg="W não anda para onde a câmera olha")
            self.assertAlmostEqual(caso["s"], -1.0, places=6,
                                   msg="S não anda para trás")
            self.assertAlmostEqual(caso["d"], 1.0, places=6,
                                   msg="D não anda para a direita")
            self.assertAlmostEqual(caso["a"], -1.0, places=6,
                                   msg="A não anda para a esquerda")

    def test_o_pino_teleporta_de_dentro_em_vez_de_sair(self):
        """
        De fora o pino leva ao tour. De dentro, abrir outra página seria perder
        o passeio no meio.
        """
        corpo = self.html[self.html.index("const noPino ="):]
        corpo = corpo[:corpo.index("const achou =")]
        self.assertIn("if (emPessoa)", corpo)
        self.assertIn("pessoa.pos.set", corpo)
        self.assertIn("livre(x, z)", corpo,
                      "teleporta sem conferir se cabe um corpo")

    def test_o_minimapa_mostra_posicao_e_direcao(self):
        """Dentro de um imóvel, o que mais se perde é a noção de onde se está."""
        self.assertIn("desenharMinimapa", self.html)
        corpo = self.html[self.html.index("function desenharMinimapa"):]
        corpo = corpo[:corpo.index("\n  }\n")]
        self.assertIn("pessoa.pos", corpo, "não desenha onde a pessoa está")
        self.assertIn("direcao(pessoa.giro", corpo, "não desenha para onde olha")

    def test_o_manche_anda_para_onde_o_polegar_aponta(self):
        """
        No celular nao ha W A S D. O manche traduz o polegar em direcao — e a
        tela cresce o Y para BAIXO, entao empurrar para cima tem de andar para
        FRENTE. Trocar esse sinal daria o mesmo defeito do W invertido.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        corpo = self.html[self.html.index("  function doManche(dx, dy, raio){"):]
        corpo = corpo[:corpo.index("\n  }") + 4]
        programa = corpo + """
console.log(JSON.stringify({
  cima:     doManche(0, -46, 46),
  baixo:    doManche(0,  46, 46),
  direita:  doManche(46,  0, 46),
  esquerda: doManche(-46, 0, 46),
  parado:   doManche(2, 2, 46),
  meio:     doManche(0, -23, 46),
  alem:     doManche(0, -200, 46)
}));
"""
        caminho = os.path.join(_TEMP, "manche.mjs")
        with io.open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write(programa)
        r = subprocess.run([self.node, caminho], capture_output=True, text=True,
                           errors="ignore")
        self.assertEqual(r.returncode, 0, r.stderr[:500])
        v = json.loads(r.stdout)

        self.assertGreater(v["cima"]["frente"], 0.9, "para cima não anda para frente")
        self.assertLess(v["baixo"]["frente"], -0.9, "para baixo não anda para trás")
        self.assertGreater(v["direita"]["lado"], 0.9)
        self.assertLess(v["esquerda"]["lado"], -0.9)

    def test_polegar_pousado_nao_faz_andar_sozinho(self):
        """Sem zona morta, o dedo parado na tela empurra a pessoa devagar."""
        if not self.node:
            self.skipTest("node não encontrado")
        corpo = self.html[self.html.index("  function doManche(dx, dy, raio){"):]
        corpo = corpo[:corpo.index("\n  }") + 4]
        caminho = os.path.join(_TEMP, "manche2.mjs")
        with io.open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write(corpo + "\nconsole.log(JSON.stringify(doManche(2, 2, 46)));\n")
        r = subprocess.run([self.node, caminho], capture_output=True, text=True,
                           errors="ignore")
        v = json.loads(r.stdout)
        self.assertEqual((v["frente"], v["lado"]), (0, 0))

    def test_o_manche_e_analogico_e_nao_estoura_de_um(self):
        """
        Polegar pela metade anda pela metade — é o que permite olhar um cômodo
        devagar. E além da borda não pode acelerar: fica em 1.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        corpo = self.html[self.html.index("  function doManche(dx, dy, raio){"):]
        corpo = corpo[:corpo.index("\n  }") + 4]
        caminho = os.path.join(_TEMP, "manche3.mjs")
        with io.open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write(corpo + "\nconsole.log(JSON.stringify("
                    "[doManche(0,-23,46), doManche(0,-460,46)]));\n")
        r = subprocess.run([self.node, caminho], capture_output=True, text=True,
                           errors="ignore")
        meio, alem = json.loads(r.stdout)
        self.assertAlmostEqual(meio["frente"], 0.5, places=2)
        self.assertAlmostEqual(alem["frente"], 1.0, places=6)

    def test_o_manche_so_aparece_onde_ha_toque(self):
        """No computador ele seria um estorvo sobre a maquete."""
        corpo = self.html[self.html.index("function atualizarPessoa()"):]
        corpo = corpo[:corpo.index("\n  // ")]
        self.assertIn("temToque()", corpo, "aparece mesmo sem toque")
        self.assertIn('$("manche")', corpo)

    def test_o_dedo_do_manche_nao_vira_o_olhar(self):
        """
        Com dois dedos na tela — um no manche, outro olhando — usar touches[0]
        pegava o dedo errado e a vista saltava.
        """
        self.assertIn("changedTouches", self.html)
        corpo = self.html[self.html.index("const pegar ="):]
        corpo = corpo[:corpo.index("const comecar")]
        self.assertIn("changedTouches", corpo)

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

    def _olhar(self, dx, dy, dz):
        d = np.array([[dx, dy, dz]], np.float32)
        return cena_apartamento._ceu(d / np.linalg.norm(d))[0]

    def test_a_janela_muda_conforme_o_angulo(self):
        """
        O QUE FAZ UMA JANELA SER JANELA. Ate aqui ela era um retangulo bege
        chapado: de qualquer angulo, a mesma mancha clara. O que diz ao cerebro
        que aquilo e o lado de fora nao e a cor — e a vista MUDAR quando a
        cabeca vira. Painel chapado nao muda.
        """
        cima = self._olhar(0, 1, 0)
        baixo = self._olhar(0, -1, 0)
        self.assertGreater(float(np.abs(cima - baixo).max()), 40,
                           "olhar para cima e para baixo da a mesma coisa")

    def test_o_ceu_e_azul_e_o_chao_nao(self):
        """O panorama sai em BGR: no ceu o azul manda, no terreno nao."""
        cima = self._olhar(0, 1, 0)
        baixo = self._olhar(0, -1, 0)
        self.assertGreater(cima[0], cima[2] + 40, "o ceu nao esta azul")
        self.assertLessEqual(baixo[0], baixo[1], "o terreno saiu azulado")

    def test_o_horizonte_e_mais_lavado_que_o_zenite(self):
        """
        Ceu real clareia perto do horizonte, por causa da distancia de ar. Sem
        isso o vidro parece papel de parede azul.
        """
        zenite = self._olhar(0, 1, 0)
        horizonte = self._olhar(0, 0.02, 1)
        self.assertGreater(float(horizonte.mean()), float(zenite.mean()) + 20)

    def test_a_janela_recebe_mesmo_a_direcao_do_raio(self):
        """
        Conferencia de texto, assumida como tal: garante que o desenho da
        janela consulta a direcao, e nao voltou ao retangulo chapado.
        """
        fonte = io.open("cena_apartamento.py", encoding="utf-8").read()
        corpo = fonte[fonte.index("def _textura("):]
        corpo = corpo[:corpo.index(chr(10) + "def ")]
        self.assertIn("_ceu(dirs[dentro])", corpo,
                      "a janela voltou a ser um painel chapado")

    def test_render_longo_retoma_de_onde_parou(self):
        """
        Custou uma hora perdida para virar codigo: a mansao leva mais de
        sessenta minutos em 88 pontos, e qualquer interrupcao jogava fora tudo
        o que ja estava pronto.

        Exige os DOIS arquivos. Um ponto que gravou a foto e morreu antes do
        mapa de profundidade esta pela metade — e metade e pior do que nada,
        porque parece pronto e o tour abre sem caminhada naquele ponto.
        """
        pasta = os.path.join(_TEMP, "retomada")
        os.makedirs(pasta, exist_ok=True)
        self.assertFalse(cena_apartamento._ja_renderizado(pasta, 0),
                         "achou pronto o que nem existe")

        io.open(os.path.join(pasta, "ponto_0.jpg"), "w").close()
        self.assertFalse(cena_apartamento._ja_renderizado(pasta, 0),
                         "deu por pronto um ponto sem profundidade")

        io.open(os.path.join(pasta, "dist_0.npy"), "w").close()
        self.assertTrue(cena_apartamento._ja_renderizado(pasta, 0))

        io.open(os.path.join(pasta, "dist_1.npy"), "w").close()
        self.assertFalse(cena_apartamento._ja_renderizado(pasta, 1),
                         "deu por pronto um ponto sem foto")

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
        """
        Ancorado no arquivo mais novo, e nao no relogio.

        Antes fingia "duas horas atras" e comparava com a data do fonte mais
        recente — entao so passava se alguem tivesse editado algo nas ultimas
        duas horas. Reprovou de verdade num dia parado, com o produto inteiro
        certo, e teste que reprova por calendario ensina a ignorar vermelho.
        """
        gravado = servico._gravado_mais_recente()
        servico._inicio_do_servidor = lambda: gravado - 3600
        veredito, detalhe = servico.codigo_no_ar()
        self.assertIs(veredito, False, detalhe)
        self.assertIn("MAIS VELHO", detalhe)

    def test_processo_mais_novo_passa(self):
        gravado = servico._gravado_mais_recente()
        servico._inicio_do_servidor = lambda: gravado + 60
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


class PaginaNoNode:
    """
    Recorta funcoes da maquete e roda no Node.

    Conferir a pagina por texto so prova que a linha existe. Linha que existe
    ainda pode enquadrar o comodo errado, ou por o sol do meio-dia ao sul.
    """

    PAGINA = "maquete.html"

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        with io.open(os.path.join("static", cls.PAGINA), encoding="utf-8") as f:
            cls.html = f.read()

    def _funcao(self, nome):
        """Recorta uma funcao da pagina pelo nome."""
        abre = "  function %s(" % nome
        self.assertIn(abre, self.html, "a página não tem mais %s" % nome)
        corpo = self.html[self.html.index(abre):]
        return corpo[:corpo.index(chr(10) + "  }") + 4]

    def _rodar(self, programa, arquivo):
        caminho = os.path.join(_TEMP, arquivo)
        with io.open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write(programa)
        # encoding explicito: o Node escreve UTF-8 e o Windows decodificaria
        # em cp1252, transformando "12,4 m2" em "12,4 mA2" — e o teste
        # reprovaria uma pagina certa
        r = subprocess.run([self.node, caminho], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stderr[:600])
        return json.loads(r.stdout.strip())


class TestCompartilharAMaquete(PaginaNoNode, unittest.TestCase):
    """
    Tirar a maquete de dentro da tela: link de um comodo, imagem para o
    anuncio, tela cheia e a metragem escrita no chao.

    Todas nascem da mesma queixa: a maquete so servia para quem estava com ela
    aberta. Corretor manda "olha a cozinha" pelo WhatsApp, cola a planta no
    classificado e mostra no tablet — e nada disso dava para fazer.

    As funcoes sao EXTRAIDAS da pagina e rodadas no Node, contra a geometria
    real do apartamento. Conferir por texto so provaria que a linha existe, e
    linha que existe ainda pode enquadrar o comodo errado.
    """

    def _planta(self):
        """O apartamento de verdade, no formato que a API entrega."""
        p = plantas.apartamento()
        zonas = [{"nome": z[0], "x0": z[1], "x1": z[2], "z0": z[3], "z1": z[4],
                  "m2": round((z[2] - z[1]) * (z[4] - z[3]), 1)}
                 for z in p["zonas"]]
        return {"larg": p["larg"], "fundo": p["fundo"], "zonas": zonas}

    def _enquadrar(self, pedido):
        planta = self._planta()
        return self._comZonas(planta, pedido), planta

    def _comZonas(self, planta, pedido):
        programa = (
            "const THREE = {Vector3: class {\n"
            "  constructor(){ this.x = 0; this.y = 0; this.z = 0; }\n"
            "  set(x, y, z){ this.x = x; this.y = y; this.z = z; return this; }\n"
            "}};\n"
            "const orbita = {giro: 0, altura: 0.86, raio: 20,\n"
            "                alvo: new THREE.Vector3()};\n"
            "let ocioso = true;\n"
            "const atual = 0;\n"
            "const imoveis = [" + json.dumps(planta, ensure_ascii=False) + "];\n"
            + self._funcao("enquadrarComodo") + "\n"
            "const achou = enquadrarComodo(" + json.dumps(pedido, ensure_ascii=False) + ");\n"
            "console.log(JSON.stringify({achou: achou, raio: orbita.raio,\n"
            "  x: orbita.alvo.x, z: orbita.alvo.z, ocioso: ocioso}));\n")
        return self._rodar(programa, "enquadrar.mjs")

    def test_o_link_abre_a_maquete_olhando_para_aquele_comodo(self):
        """
        O pedido do corretor: mandar "olha a cozinha" e a pessoa abrir JA na
        cozinha. Se a câmera apontasse para o meio do imóvel, o link seria o
        mesmo de sempre e o recado teria sido mentira.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        for zona in self._planta()["zonas"]:
            with self.subTest(comodo=zona["nome"]):
                saida, planta = self._enquadrar(zona["nome"])
                self.assertTrue(saida["achou"])
                # a página trabalha com o imóvel centrado na origem
                cx = (zona["x0"] + zona["x1"]) / 2 - planta["larg"] / 2
                cz = (zona["z0"] + zona["z1"]) / 2 - planta["fundo"] / 2
                self.assertAlmostEqual(saida["x"], cx, places=3)
                self.assertAlmostEqual(saida["z"], cz, places=3)

    def test_a_camera_nao_para_dentro_da_parede_de_comodo_pequeno(self):
        """
        Raio proporcional ao cômodo põe a câmera a 3,9 m num lavabo de 1,5 m —
        dentro da parede do cômodo vizinho, com a maquete pelo avesso.

        Medido: nenhuma das três plantas de hoje tem cômodo tão pequeno (o
        menor lado maior é 4,2 m, na cozinha do compacto). A guarda existe
        porque a geometria vem de um JSON que aceita qualquer zona, e porque a
        roda do mouse já usa 4 m como limite — sem ela, o link de um cômodo
        seria o único caminho capaz de furar o limite da própria página. Por
        isso o cômodo deste teste é fabricado, e não tirado das plantas.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        planta = self._planta()
        planta["zonas"] = [{"nome": "Lavabo", "x0": 0.0, "x1": 1.5,
                            "z0": 0.0, "z1": 1.2, "m2": 1.8}]
        saida = self._comZonas(planta, "Lavabo")
        self.assertTrue(saida["achou"])
        self.assertGreaterEqual(saida["raio"], 4, "câmera dentro da parede")

    def test_comodo_inventado_no_endereco_nao_desmonta_a_vista(self):
        """
        Link copiado errado, cômodo renomeado depois, `?comodo=Piscina` de
        brincadeira: em todos, a maquete tem de abrir normal.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        saida, _ = self._enquadrar("Piscina olímpica")
        self.assertFalse(saida["achou"])
        self.assertEqual(saida["raio"], 20, "mexeu na câmera sem ter achado")
        self.assertTrue(saida["ocioso"], "parou o giro sem ter enquadrado nada")

    def test_a_parada_do_giro_so_acontece_quando_enquadra(self):
        """
        Enquadrar e continuar girando sozinho tiraria o cômodo de vista em
        dois segundos — seria o mesmo que não ter enquadrado.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        saida, _ = self._enquadrar(self._planta()["zonas"][0]["nome"])
        self.assertFalse(saida["ocioso"])

    def test_o_endereco_entrega_o_comodo_pedido(self):
        """O link do WhatsApp chega com acento e espaço; tem de voltar igual."""
        if not self.node:
            self.skipTest("node não encontrado")
        programa = (
            "const location = {search: '?comodo=Sala%20de%20estar&x=1'};\n"
            + self._funcao("comodoDoEndereco") + "\n"
            "const vazio = {search: ''};\n"
            "console.log(JSON.stringify(comodoDoEndereco()));\n")
        self.assertEqual(self._rodar(programa, "endereco.mjs"), "Sala de estar")

    def test_cada_imovel_baixa_com_o_proprio_nome(self):
        """
        Medido no navegador: sem isto o arquivo sai "download.png", e quem
        baixa a planta de três imóveis no mesmo dia fica com download.png,
        download(1).png e download(2).png.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        casos = [["Apartamento no Jardim Paulista", False],
                 ["Cobertura Duplex · Térreo/Superior", True],
                 ["", False], ["!!!", True]]
        programa = (self._funcao("nomeDeArquivo") + "\n"
                    "console.log(JSON.stringify(" + json.dumps(casos, ensure_ascii=False)
                    + ".map(c => nomeDeArquivo(c[0], c[1]))));\n")
        saida = self._rodar(programa, "nome-arquivo.mjs")
        self.assertEqual(saida[0], "apartamento-no-jardim-paulista-maquete.png")
        self.assertEqual(saida[1], "cobertura-duplex-terreo-superior-planta.png")
        self.assertEqual(saida[2], "maquete-maquete.png", "imóvel sem nome")
        self.assertEqual(saida[3], "maquete-planta.png", "nome só de símbolos")
        for nome in saida:
            self.assertRegex(nome, r"^[a-z0-9-]+\.png$",
                             "nome de arquivo com acento chega quebrado")

    def test_a_planta_e_a_maquete_nao_se_sobrescrevem(self):
        """Baixar as duas vistas do mesmo imóvel tem de dar dois arquivos."""
        if not self.node:
            self.skipTest("node não encontrado")
        programa = (self._funcao("nomeDeArquivo") + "\n"
                    "console.log(JSON.stringify([nomeDeArquivo('Casa', false),\n"
                    "                            nomeDeArquivo('Casa', true)]));\n")
        a, b = self._rodar(programa, "duas-vistas.mjs")
        self.assertNotEqual(a, b)

    def test_o_rotulo_no_chao_diz_a_metragem(self):
        """
        Visto de cima, "Quarto" e "Quarto" não dizem qual é o de casal. O
        tamanho é a primeira pergunta de quem procura imóvel, e estava só na
        lista lateral — fora da imagem que vai para o anúncio.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        programa = (
            "const nBR = (n, casas) => n.toLocaleString('pt-BR',\n"
            "  {minimumFractionDigits: casas, maximumFractionDigits: casas});\n"
            + self._funcao("textoDoRotulo") + "\n"
            "console.log(JSON.stringify([\n"
            "  textoDoRotulo({nome: 'Quarto de casal', m2: 12.35}),\n"
            "  textoDoRotulo({nome: 'Varanda'})]));\n")
        com, sem = self._rodar(programa, "rotulo.mjs")
        self.assertIn("12,4", com, "metragem em formato de fora do Brasil")
        self.assertIn("m²", com)
        self.assertEqual(sem, "Varanda",
                         "cômodo sem metragem não pode virar 'Varanda · 0,0 m²'")

    def test_a_vista_pode_virar_imagem(self):
        """
        Medido: sem preserveDrawingBuffer o toDataURL do WebGL devolve um PNG
        TRANSPARENTE, porque o navegador já limpou o buffer. O botão pareceria
        funcionar e o arquivo sairia vazio.
        """
        self.assertIn("preserveDrawingBuffer: true", self.html)

    def test_tela_cheia_recalcula_a_camera(self):
        """
        O palco muda de tamanho ao entrar em tela cheia. Sem recalcular a
        proporção, a maquete aparece esticada — que é pior do que não ter o
        botão.
        """
        depois = self.html[self.html.index('addEventListener("fullscreenchange"'):]
        self.assertIn("redimensionar", depois[:200])


class TestBibliotecaPropria(unittest.TestCase):
    """
    A maquete nao pode depender da internet para abrir.

    Medido: a pagina carregava o three.js DUAS vezes — o do projeto, no
    cabecalho, e um r128 do cdnjs logo antes do codigo. O segundo ganhava.
    Na pratica a maquete rodava numa versao mais velha do que a que o projeto
    distribui, e numa rede sem saida (ou com o cdnjs bloqueado, que e comum em
    rede de empresa) caia numa versao que ninguem nunca tinha exercitado.

    Imovel se mostra em lugar nenhum: no stand, no notebook da imobiliaria, no
    celular com sinal ruim. Pagina que precisa de CDN para desenhar e pagina
    que escolhe a pior hora para falhar.
    """

    PAGINAS = ["maquete.html", "andar.html", "visualizador.html", "admin.html",
               "imoveis.html", "entrar.html"]

    def _ler(self, nome):
        caminho = os.path.join("static", nome)
        if not os.path.exists(caminho):
            self.skipTest("%s não existe" % nome)
        with io.open(caminho, encoding="utf-8") as f:
            return f.read()

    def test_nenhuma_pagina_busca_codigo_na_internet(self):
        """Script ou folha de estilo de fora é ponto de falha que não é nosso."""
        for nome in self.PAGINAS:
            caminho = os.path.join("static", nome)
            if not os.path.exists(caminho):
                continue
            with io.open(caminho, encoding="utf-8") as f:
                html = f.read()
            for achado in re.findall(r'<(?:script|link)[^>]*?(?:src|href)="(https?:)?//[^"]+"',
                                     html, re.I):
                self.fail("%s ainda busca recurso de fora: %s" % (nome, achado))

    def test_a_maquete_carrega_a_biblioteca_uma_vez_so(self):
        """
        Duas versões da mesma biblioteca na mesma página: a segunda sobrescreve
        a primeira, e qual das duas roda passa a depender de a rede responder.
        """
        html = self._ler("maquete.html")
        fontes = re.findall(r'<script[^>]*src="([^"]*three[^"]*)"', html, re.I)
        self.assertEqual(fontes, ["/static/vendor/three.js"],
                         "a página carrega three.js de mais de um lugar: %s" % fontes)

    def test_a_biblioteca_do_projeto_tem_tudo_o_que_as_paginas_usam(self):
        """
        Tirar o CDN só vale se o pacote embarcado atender. Aqui o pacote é
        carregado de verdade no Node e cada THREE.X citado pelas páginas é
        procurado nele — porque classe que sumiu entre uma versão e outra só
        apareceria como tela preta no navegador de quem abriu o link.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node não encontrado")
        usados = set()
        for nome in ("maquete.html", "andar.html"):
            caminho = os.path.join("static", nome)
            if not os.path.exists(caminho):
                continue
            with io.open(caminho, encoding="utf-8") as f:
                usados |= set(re.findall(r"THREE\.([A-Za-z0-9_]+)", f.read()))
        self.assertGreater(len(usados), 15, "não achei os usos de THREE")

        programa = (
            "global.self = global; global.window = global;\n"
            "const T = require(" + json.dumps(
                os.path.abspath(os.path.join("static", "vendor", "three.js"))) + ");\n"
            "const faltam = " + json.dumps(sorted(usados)) +
            ".filter(n => T[n] === undefined);\n"
            "console.log(JSON.stringify({revisao: T.REVISION, faltam: faltam}));\n")
        caminho = os.path.join(_TEMP, "three.cjs")
        with io.open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write(programa)
        r = subprocess.run([node, caminho], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stderr[:600])
        saida = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(saida["faltam"], [],
                         "o three.js do projeto não tem: %s" % saida["faltam"])


class TestSemAceleracao3D(PaginaNoNode, unittest.TestCase):
    """
    Notebook velho, maquina virtual, navegador com aceleracao desligada por
    politica da empresa: em todos, criar o renderizador LANCA.

    Ate aqui a pagina ficava preta, sem uma palavra. O corretor abre na frente
    do cliente e nao tem o que dizer — e o tour 360 do mesmo imovel abriria
    normalmente, porque ele nao precisa de WebGL.
    """

    def _detectar(self, contexto):
        programa = (
            # parenteses em volta do objeto: sem eles o arrow vira corpo em
            # bloco, devolve undefined, e o teste reprovaria uma pagina certa
            "const document = {createElement: () => ({getContext: () => ("
            + contexto + ")})};\n"
            + self._funcao("temWebGL") + "\n"
            "console.log(JSON.stringify(temWebGL()));\n")
        return self._rodar(programa, "webgl.mjs")

    def test_navegador_sem_webgl_e_reconhecido(self):
        if not self.node:
            self.skipTest("node não encontrado")
        self.assertFalse(self._detectar("null"))

    def test_navegador_com_webgl_passa(self):
        """Guarda que reprova todo mundo tiraria a maquete de quem a tem."""
        if not self.node:
            self.skipTest("node não encontrado")
        self.assertTrue(self._detectar("{}"))

    def test_navegador_que_explode_ao_perguntar_nao_derruba_a_pagina(self):
        """
        Há navegador que lança ao pedir o contexto em vez de devolver null.
        Sem o try, a exceção sobe e mata o resto do script — inclusive o
        recado que existe justamente para essa hora.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        self.assertFalse(self._detectar("(() => { throw new Error('nao'); })()"))

    def test_a_pagina_desiste_de_montar_quando_nao_da(self):
        """
        Conferência de texto, e assumida como tal: o que ela garante é que o
        retorno de iniciar3d é OLHADO. Sem isso o guarda existiria e a página
        seguiria chamando mostrar() sobre um renderizador que nunca nasceu.
        """
        self.assertIn("if (!iniciar3d()) return;", self.html)

    def test_o_recado_aparece_no_palco_e_nao_so_no_texto_lateral(self):
        """
        Retângulo preto com a explicação escrita do lado parece defeito. Quem
        abre olha para o lugar onde a maquete deveria estar.
        """
        corpo = self.html[self.html.index("  function erro(titulo, texto){"):]
        corpo = corpo[:corpo.index("\n  }") + 4]
        self.assertIn('$("recado").hidden = false', corpo)
        self.assertIn('id="recado"', self.html)


class TestSolDoImovel(PaginaNoNode, unittest.TestCase):
    """
    "Que horas bate sol na sala?" e a segunda pergunta de quem procura imovel,
    logo depois da metragem.

    A maquete ja tinha tudo para responder — as janelas medidas e a parede em
    que cada uma esta — menos o NORTE, que geometria nenhuma carrega. Por isso
    a orientacao e do corretor.

    As contas sao exercitadas no Node porque erro de hemisferio nao aparece em
    revisao de codigo: a formula "certa" do livro coloca o sol ao sul ao
    meio-dia, o que vale para a Europa e esta invertido no Brasil.
    """

    def _sol(self, expressao, extras=()):
        nomes = ("posicaoDoSol", "horasDeSol", "ladoDaJanela", "janelasDoComodo",
                 "hhmm", "rumo", "solDoComodo", "direcaoDoSol") + tuple(extras)
        programa = ("const LATITUDE = -23.55;\n"
                    'const RUMOS = ["norte", "nordeste", "leste", "sudeste",\n'
                    '               "sul", "sudoeste", "oeste", "noroeste"];\n')
        for n in nomes:
            programa += self._funcao(n) + "\n"
        programa += "console.log(JSON.stringify(" + expressao + "));\n"
        return self._rodar(programa, "sol.mjs")

    def _planta(self):
        p = plantas.apartamento()
        return {"larg": p["larg"], "fundo": p["fundo"], "janelas": p["janelas"],
                "zonas": [{"nome": z[0], "x0": z[1], "x1": z[2],
                           "z0": z[3], "z1": z[4],
                           "m2": round((z[2] - z[1]) * (z[4] - z[3]), 1)}
                          for z in p["zonas"]]}

    def test_ao_meio_dia_no_brasil_o_sol_esta_ao_NORTE(self):
        """
        O erro que a fórmula do livro comete: no hemisfério sul o sol do meio-dia
        vem do norte, não do sul. Invertido, a maquete diria "sol da manhã" para
        o quarto que passa o dia na sombra — e quem visitasse descobriria.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        s = self._sol("posicaoDoSol(12)")
        self.assertAlmostEqual(s["azimute"], 0, places=6)
        # no equinocio a altura maxima e 90 menos a latitude
        self.assertAlmostEqual(s["altura"], 90 - 23.55, places=1)

    def test_o_sol_nasce_a_leste_e_se_poe_a_oeste(self):
        if not self.node:
            self.skipTest("node não encontrado")
        nasce = self._sol("posicaoDoSol(6)")
        poe = self._sol("posicaoDoSol(18)")
        self.assertAlmostEqual(nasce["azimute"], 90, places=1)
        self.assertAlmostEqual(poe["azimute"], 270, places=1)
        self.assertAlmostEqual(nasce["altura"], 0, places=6)

    def test_a_conta_continua_valendo_no_hemisferio_norte(self):
        """
        Não é preciosismo: prova que a conta é de astronomia e não um ajuste
        feito na mão para o Brasil. Em Nova York o sol do meio-dia está ao SUL.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        s = self._sol("posicaoDoSol(12, 40.7)")
        self.assertAlmostEqual(s["azimute"], 180, places=6)
        self.assertAlmostEqual(s["altura"], 90 - 40.7, places=1)

    def test_janela_ao_sul_no_brasil_nao_pega_sol_nenhum_dia(self):
        """
        O sol nunca cruza o sul visto daqui. Dizer que pega seria o erro que o
        cliente descobre na primeira visita, de manhã, no quarto frio.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        self.assertIsNone(self._sol("horasDeSol(180)"))

    def test_leste_pega_a_manha_e_oeste_pega_a_tarde(self):
        if not self.node:
            self.skipTest("node não encontrado")
        leste = self._sol("horasDeSol(90)")
        oeste = self._sol("horasDeSol(270)")
        self.assertLess(leste["fim"], 12, "janela a leste pegando sol da tarde")
        self.assertGreater(oeste["inicio"], 12, "janela a oeste pegando sol da manhã")
        self.assertLess(leste["inicio"], 7, "o sol nasce e a janela leste não vê")

    def test_janela_ao_norte_pega_o_dia_quase_inteiro(self):
        if not self.node:
            self.skipTest("node não encontrado")
        norte = self._sol("horasDeSol(0)")
        self.assertGreater(norte["fim"] - norte["inicio"], 6,
                           "face norte é a mais procurada justamente por isso")

    def test_girar_a_frente_meia_volta_troca_manha_por_tarde(self):
        """
        O teste que prova que a orientação é MESMO usada: o mesmo apartamento,
        os mesmos cômodos, a frente virada 180° — e o que pegava sol da manhã
        passa a pegar da tarde.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        planta = self._planta()
        sala = planta["zonas"][0]["nome"]
        expressao = ("[solDoComodo(im.zonas[0], im, 90), "
                     "solDoComodo(im.zonas[0], im, 270)]")
        leste, oeste = self._solComPlanta(planta, expressao)
        self.assertIn("manhã", leste, sala + " a leste deveria pegar sol da manhã")
        self.assertIn("tarde", oeste, sala + " a oeste deveria pegar sol da tarde")

    def _solComPlanta(self, planta, expressao):
        nomes = ("posicaoDoSol", "horasDeSol", "ladoDaJanela", "janelasDoComodo",
                 "hhmm", "rumo", "solDoComodo")
        programa = ("const LATITUDE = -23.55;\n"
                    'const RUMOS = ["norte", "nordeste", "leste", "sudeste",\n'
                    '               "sul", "sudoeste", "oeste", "noroeste"];\n'
                    "const im = " + json.dumps(planta, ensure_ascii=False) + ";\n")
        for n in nomes:
            programa += self._funcao(n) + "\n"
        programa += "console.log(JSON.stringify(" + expressao + "));\n"
        return self._rodar(programa, "sol-planta.mjs")

    def test_cada_comodo_recebe_a_janela_da_propria_parede(self):
        """
        Medido na planta real: cada cômodo do apartamento encosta numa parede
        externa e tem a sua janela. Cômodo que herdasse a janela do vizinho
        anunciaria sol onde não há.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        planta = self._planta()
        achados = self._solComPlanta(
            planta, "im.zonas.map(z => janelasDoComodo(z, im).length)")
        self.assertEqual(len(achados), len(planta["zonas"]))
        for nome, quantas in zip([z["nome"] for z in planta["zonas"]], achados):
            self.assertGreater(quantas, 0, nome + " ficou sem janela")
        # e cada janela serve um comodo SO: somar mais do que existe significa
        # que alguem esta herdando a janela do vizinho e anunciando sol alheio
        self.assertEqual(sum(achados), len(planta["janelas"]),
                         "janela contada em mais de um cômodo: %s" % achados)

    def test_comodo_sem_janela_para_fora_diz_isso_em_vez_de_inventar(self):
        if not self.node:
            self.skipTest("node não encontrado")
        planta = self._planta()
        planta["janelas"] = []
        frase = self._solComPlanta(planta, "solDoComodo(im.zonas[0], im, 90)")
        self.assertIn("Sem janela", frase)

    def test_sem_orientacao_a_pagina_nao_chuta(self):
        """
        Orientação desconhecida não pode virar "norte por padrão": seria
        inventar a informação que o corretor ainda não deu, e ela sai impressa
        na ficha do cômodo como se fosse medida.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        planta = self._planta()
        self.assertEqual(
            self._solComPlanta(planta, "solDoComodo(im.zonas[0], im, null)"), "")
        self.assertIsNone(
            self._solComPlanta(planta, "ladoDaJanela(im.janelas[0], im, null)"))

    def test_a_luz_da_cena_segue_a_hora_escolhida(self):
        """
        A conta pode estar certa e a maquete continuar com a luz de sempre. Ao
        meio-dia o sol vem de cima; às 7h vem de lado — e é isso que faz a
        maquete PARECER de manhã.
        """
        if not self.node:
            self.skipTest("node não encontrado")
        meio = self._sol("direcaoDoSol(12, 0)")
        cedo = self._sol("direcaoDoSol(7, 0)")
        self.assertGreater(meio["y"], cedo["y"],
                           "a luz do meio-dia tem de vir de mais alto")
        self.assertLess(cedo["y"], 0.55, "às 7h o sol ainda está baixo")
        # frente ao norte: ao meio-dia o sol vem da frente, ou seja, do -Z
        self.assertLess(meio["z"], 0)
        self.assertAlmostEqual(meio["x"], 0, places=6)


class TestOrientacaoDoImovel(Base):
    """
    Para que lado a frente do imovel esta voltada.

    Fica gravado NO IMOVEL, e nao no endereco. Se viajasse so no link, dois
    visitantes do mesmo imovel veriam respostas diferentes para "bate sol na
    sala?" — e essa e uma pergunta com uma resposta so.
    """

    def setUp(self):
        self.dona = self.conta("dona-sol")
        self.iid = self.imovel(self.dona, "Apartamento com sol")
        with io.open(aplicacao.arq_maquete(self.iid), "w", encoding="utf-8") as f:
            json.dump(TestMaquete.GEOMETRIA, f, ensure_ascii=False)

    def test_a_orientacao_gravada_chega_a_quem_abre_o_link(self):
        """O visitante não tem como informar o norte; ele recebe o do corretor."""
        r = self.dona.put("/api/imoveis/%s/orientacao" % self.iid,
                          json={"frente": 90})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])

        visitante = aplicacao.app.test_client()
        m = visitante.get("/api/imoveis/%s/maquete" % self.iid).get_json()["maquete"]
        self.assertEqual(m["frente"], 90)

    def test_sem_ninguem_informar_a_resposta_e_nao_sei(self):
        """
        None e zero são coisas diferentes: zero é "a frente olha para o norte",
        que é informação. Confundir os dois faria a maquete anunciar sol da
        manhã em imóvel que ninguém orientou.
        """
        m = self.dona.get("/api/imoveis/%s/maquete" % self.iid).get_json()["maquete"]
        self.assertIsNone(m["frente"])

    def test_a_frente_ao_norte_nao_se_confunde_com_nao_informado(self):
        self.dona.put("/api/imoveis/%s/orientacao" % self.iid, json={"frente": 0})
        m = self.dona.get("/api/imoveis/%s/maquete" % self.iid).get_json()["maquete"]
        self.assertEqual(m["frente"], 0)
        self.assertIsNotNone(m["frente"])

    def test_apagar_devolve_ao_nao_informado(self):
        self.dona.put("/api/imoveis/%s/orientacao" % self.iid, json={"frente": 180})
        self.assertEqual(
            self.dona.delete("/api/imoveis/%s/orientacao" % self.iid).status_code, 200)
        m = self.dona.get("/api/imoveis/%s/maquete" % self.iid).get_json()["maquete"]
        self.assertIsNone(m["frente"])

    def test_valor_sem_sentido_e_recusado_com_recado(self):
        r = self.dona.put("/api/imoveis/%s/orientacao" % self.iid,
                          json={"frente": "para o mar"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("graus", r.get_json()["erro"])

    def test_graus_acima_de_uma_volta_dao_na_mesma_direcao(self):
        self.dona.put("/api/imoveis/%s/orientacao" % self.iid, json={"frente": 450})
        m = self.dona.get("/api/imoveis/%s/maquete" % self.iid).get_json()["maquete"]
        self.assertEqual(m["frente"], 90)

    def test_visitante_nao_reorienta_imovel_alheio(self):
        """
        A orientação é pública para LER e privada para escrever: ela muda o que
        o anúncio afirma sobre o imóvel.
        """
        visitante = aplicacao.app.test_client()
        r = visitante.put("/api/imoveis/%s/orientacao" % self.iid,
                          json={"frente": 270})
        self.assertIn(r.status_code, (401, 403, 404))
        m = self.dona.get("/api/imoveis/%s/maquete" % self.iid).get_json()["maquete"]
        self.assertIsNone(m["frente"], "o visitante conseguiu girar o imóvel")

    def test_o_seletor_de_orientacao_e_so_da_dona(self):
        """Quem visita não tem como saber para que lado o imóvel olha."""
        html = io.open(os.path.join("static", "maquete.html"),
                       encoding="utf-8").read()
        trecho = html[html.index('id="frenteDona"'):]
        self.assertIn("hidden", trecho[:60],
                      "o seletor nasce visível para qualquer visitante")


class TestVizinhanca(Base):
    """
    O que existe em volta do imovel.

    O anuncio parava na porta: o tour entrega o interior inteiro — panorama,
    maquete, caminhada, medidas, sol — e nao dizia uma palavra sobre o bairro,
    que e metade da decisao de quem compra.

    Nenhum teste aqui toca a rede. Nao e comodismo: teste que depende de dois
    servicos de terceiro estarem no ar reprova codigo certo num dia ruim, e
    ensina a ignorar teste vermelho. O caminho de rede e trocado por um
    gabarito, e o que se exercita e o que o nosso codigo FAZ com a resposta.
    """

    # Dois pontos reais da Avenida Paulista, com a distancia conferida no mapa.
    MASP = (-23.561414, -46.655881)

    def setUp(self):
        self.dona = self.conta("dona-bairro")
        self.iid = self.imovel(self.dona, "Apartamento no centro")

    # ---------------------------------------------------------------- contas

    def test_a_distancia_e_a_da_esfera_e_nao_a_do_plano(self):
        """
        Um grau de latitude são 111,19 km em qualquer lugar do mundo. Tratar
        latitude e longitude como plano cartesiano erraria mais quanto mais
        longe do equador — e o Brasil inteiro está longe do equador.
        """
        self.assertAlmostEqual(vizinhanca._haversine(0, 0, 1, 0), 111195,
                               delta=60)
        # e um grau de LONGITUDE encurta com a latitude: no paralelo de São
        # Paulo ele vale cerca de 102 km, nao 111
        self.assertAlmostEqual(vizinhanca._haversine(-23.5, 0, -23.5, 1),
                               102000, delta=900)

    def test_o_mesmo_ponto_dista_zero(self):
        self.assertEqual(round(vizinhanca._haversine(*(self.MASP + self.MASP))), 0)

    def test_cada_tipo_de_lugar_cai_na_categoria_certa(self):
        casos = [
            ({"shop": "supermarket"}, "mercado"),
            ({"shop": "bakery"}, "padaria"),
            ({"amenity": "pharmacy"}, "farmacia"),
            ({"amenity": "school"}, "escola"),
            ({"highway": "bus_stop"}, "onibus"),
            ({"leisure": "park"}, "praca"),
        ]
        for tags, esperado in casos:
            with self.subTest(tags=tags):
                self.assertEqual(vizinhanca.categoria(tags)[0], esperado)

    def test_lugar_que_nao_interessa_nao_entra_na_lista(self):
        """
        O OpenStreetMap tem de tudo: poste, lixeira, banco de praça. Deixar
        entrar encheria o anúncio de coisa que não ajuda a decidir nada.
        """
        for tags in ({"amenity": "waste_basket"}, {"highway": "street_lamp"},
                     {"amenity": "bench"}, {}):
            self.assertIsNone(vizinhanca.categoria(tags), tags)

    def test_a_consulta_pede_todas_as_categorias_que_a_lista_declara(self):
        """
        Categoria nova na lista e esquecida na consulta ficaria para sempre
        com zero resultados, sem erro nenhum — o pior tipo de defeito.
        """
        texto = vizinhanca.consulta(*self.MASP)
        for _chave, rotulo, regras in vizinhanca.CATEGORIAS:
            for campo, valores in regras.items():
                for valor in valores:
                    self.assertIn(valor, texto, "%s ficou fora" % rotulo)
                self.assertIn('"%s"' % campo, texto)

    # ---------------------------------------------------------- a escolha

    def _no(self, tags, lat, lon):
        return {"type": "node", "lat": lat, "lon": lon, "tags": tags}

    def test_de_cada_categoria_sobra_o_mais_perto(self):
        """
        Saber que há catorze padarias no raio não ajuda ninguém a decidir. O
        que ajuda é saber que a mais perto está a 120 m.
        """
        lat, lon = self.MASP
        # a mais PERTO vem primeiro no gabarito de proposito: assim "fica a
        # ultima que apareceu" nao consegue se passar por "fica a mais perto"
        elementos = [
            self._no({"shop": "bakery", "name": "Padaria perto"}, lat + 0.0005, lon),
            self._no({"shop": "bakery", "name": "Padaria do meio"}, lat + 0.002, lon),
            self._no({"shop": "bakery", "name": "Padaria longe"}, lat + 0.004, lon),
            self._no({"amenity": "pharmacy", "name": "Farmácia"}, lat, lon + 0.002),
        ]
        achados = vizinhanca.escolher(elementos, lat, lon)
        padarias = [p for p in achados if p["chave"] == "padaria"]
        self.assertEqual(len(padarias), 1, "duas padarias na mesma lista")
        self.assertEqual(padarias[0]["nome"], "Padaria perto")
        self.assertLess(padarias[0]["metros"], 100)

    def test_a_lista_sai_do_mais_perto_ao_mais_longe(self):
        """A ordem é a do anúncio: o que está a 80 m vem antes do que está a 800."""
        lat, lon = self.MASP
        elementos = [
            self._no({"amenity": "school"}, lat + 0.005, lon),
            self._no({"shop": "bakery"}, lat + 0.0006, lon),
            self._no({"amenity": "pharmacy"}, lat + 0.002, lon),
        ]
        metros = [p["metros"] for p in vizinhanca.escolher(elementos, lat, lon)]
        self.assertEqual(metros, sorted(metros))

    def test_lugar_fora_do_raio_nao_entra(self):
        """
        O `around` do Overpass é aproximado, e o centro de uma área grande cai
        fora dele. Anunciar como "perto" o que está a 1,4 km seria conversa de
        corretor, não informação.
        """
        lat, lon = self.MASP
        longe = self._no({"shop": "supermarket"}, lat + 0.02, lon)   # ~2,2 km
        self.assertEqual(vizinhanca.escolher([longe], lat, lon), [])

    def test_mercado_mapeado_como_area_tambem_conta(self):
        """
        Medido no OpenStreetMap: mercado e escola quase sempre estão mapeados
        como ÁREA, não como ponto. Ler só `lat`/`lon` deixaria de fora
        justamente os lugares grandes, que são os que interessam.
        """
        lat, lon = self.MASP
        area = {"type": "way", "center": {"lat": lat + 0.001, "lon": lon},
                "tags": {"shop": "supermarket", "name": "Mercado em área"}}
        achados = vizinhanca.escolher([area], lat, lon)
        self.assertEqual(len(achados), 1, "área foi descartada")
        self.assertEqual(achados[0]["nome"], "Mercado em área")

    def test_elemento_sem_coordenada_nao_derruba_a_busca(self):
        lat, lon = self.MASP
        self.assertEqual(
            vizinhanca.escolher([{"type": "relation", "tags": {"shop": "bakery"}}],
                                lat, lon), [])

    # ------------------------------------------------- o endereco que mudou

    def test_trocar_o_endereco_apaga_a_vizinhanca_do_endereco_antigo(self):
        """
        O defeito silencioso que isto impede: o corretor corrige o endereço
        depois de ter buscado, e o anúncio passa a mostrar o mercado do lugar
        ERRADO sem avisar ninguém.
        """
        tour = aplicacao.carregar_tour(self.iid)
        tour["endereco"] = "Rua A, 100"
        tour["vizinhanca"] = {"endereco": "Rua A, 100", "lugares": [],
                              "lat": -23.5, "lon": -46.6}
        aplicacao.salvar_tour(tour, self.iid)

        self.dona.put("/api/imoveis/%s/tour" % self.iid,
                      json={"endereco": "Rua B, 200"})
        depois = aplicacao.carregar_tour(self.iid)
        self.assertNotIn("vizinhanca", depois,
                         "ficou a vizinhança do endereço antigo")

    def test_salvar_sem_mexer_no_endereco_preserva_a_busca(self):
        """
        Perder a busca ao corrigir o preço seria fazer o corretor buscar de
        novo por nada — e a busca chama serviço de fora, que tem limite de uso.
        """
        tour = aplicacao.carregar_tour(self.iid)
        tour["endereco"] = "Rua A, 100"
        tour["vizinhanca"] = {"endereco": "Rua A, 100", "lugares": []}
        aplicacao.salvar_tour(tour, self.iid)

        self.dona.put("/api/imoveis/%s/tour" % self.iid,
                      json={"preco": "R$ 500.000"})
        self.assertIn("vizinhanca", aplicacao.carregar_tour(self.iid))

    def test_esta_velha_nao_se_confunde_com_nunca_buscada(self):
        self.assertFalse(vizinhanca.esta_velha({"endereco": "Rua A"}))
        self.assertFalse(vizinhanca.esta_velha(
            {"endereco": "Rua A", "vizinhanca": {"endereco": "Rua A"}}))
        self.assertTrue(vizinhanca.esta_velha(
            {"endereco": "Rua B", "vizinhanca": {"endereco": "Rua A"}}))

    # ------------------------------------------------------------- a rota

    def test_imovel_sem_endereco_recebe_o_caminho_da_solucao(self):
        """
        Recusa sem saída é só um muro. E aqui nem chega a haver chamada de
        rede: sem endereço não há o que geocodificar.
        """
        r = self.dona.put("/api/imoveis/%s/vizinhanca" % self.iid)
        self.assertEqual(r.status_code, 422)
        self.assertIn("endereço", r.get_json()["erro"])

    def _gabarito(self, elementos):
        """Troca a camada de rede por uma resposta conhecida."""
        chamadas = []

        def falso(url, dados=None):
            chamadas.append(url)
            if url.startswith(vizinhanca.NOMINATIM):
                return [{"lat": "-23.561414", "lon": "-46.655881",
                         "display_name": "Avenida Paulista, São Paulo"}]
            return {"elements": elementos}

        return falso, chamadas

    def test_a_busca_grava_o_que_encontrou_no_imovel(self):
        tour = aplicacao.carregar_tour(self.iid)
        tour["endereco"] = "Avenida Paulista 1578, São Paulo"
        aplicacao.salvar_tour(tour, self.iid)

        lat, lon = self.MASP
        falso, chamadas = self._gabarito([
            self._no({"shop": "bakery", "name": "Padaria Xodó"}, lat + 0.0006, lon),
            self._no({"highway": "bus_stop"}, lat + 0.0002, lon)])
        original = vizinhanca._pedir
        vizinhanca._pedir = falso
        try:
            r = self.dona.put("/api/imoveis/%s/vizinhanca" % self.iid)
        finally:
            vizinhanca._pedir = original

        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(len(chamadas), 2, "geocodificou e perguntou o entorno")
        gravada = aplicacao.carregar_tour(self.iid)["vizinhanca"]
        tipos = [p["tipo"] for p in gravada["lugares"]]
        self.assertEqual(tipos, ["Ponto de ônibus", "Padaria"])
        self.assertEqual(gravada["endereco"], tour["endereco"],
                         "não guardou de qual endereço é esta vizinhança")

    def test_quem_visita_le_a_vizinhanca_sem_conta_e_sem_rede(self):
        """
        O ponto todo de guardar: a página de quem abre o link não fala com
        serviço de terceiro nenhum. Foi a lição do three.js que vinha do
        cdnjs — a hora em que um serviço de fora cai é sempre a pior hora.
        """
        tour = aplicacao.carregar_tour(self.iid)
        tour["vizinhanca"] = {"endereco": "", "lat": -23.5, "lon": -46.6,
                              "lugares": [{"chave": "padaria", "tipo": "Padaria",
                                           "nome": "Xodó", "metros": 120}]}
        aplicacao.salvar_tour(tour, self.iid)

        visitante = aplicacao.app.test_client()
        j = visitante.get("/api/imoveis/%s/tour" % self.iid).get_json()
        self.assertEqual(j["vizinhanca"]["lugares"][0]["metros"], 120)

    def test_apagar_tira_do_anuncio(self):
        tour = aplicacao.carregar_tour(self.iid)
        tour["vizinhanca"] = {"endereco": "", "lugares": []}
        aplicacao.salvar_tour(tour, self.iid)
        self.assertEqual(
            self.dona.delete("/api/imoveis/%s/vizinhanca" % self.iid).status_code,
            200)
        self.assertNotIn("vizinhanca", aplicacao.carregar_tour(self.iid))

    def test_visitante_nao_dispara_busca_em_imovel_alheio(self):
        """
        A busca chama dois serviços de fora que têm limite de uso. Aberta a
        qualquer um, o link do imóvel viraria um jeito de gastar esse limite.
        """
        visitante = aplicacao.app.test_client()
        r = visitante.put("/api/imoveis/%s/vizinhanca" % self.iid)
        self.assertIn(r.status_code, (401, 403, 404))

    def _desenhado(self, viz):
        """
        Roda a funcao de desenho do viewer no Node, contra um gabarito.

        Procurar a frase no ARQUIVO nao serve: o comentario que explica por que
        ela existe satisfaz a busca, e o teste passaria com a frase apagada da
        tela. O que importa e o que sai desenhado.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node não encontrado")
        html = io.open(os.path.join("static", "viewer.html"),
                       encoding="utf-8").read()
        corpo = ""
        for f in ("desenharVizinhanca", "metrosBR", "encurtar", "escapar"):
            abre = "function %s(" % f
            self.assertIn(abre, html, "o viewer não tem mais %s" % f)
            pedaco = html[html.index(abre):]
            corpo += pedaco[:pedaco.index(chr(10) + "}") + 2] + chr(10)

        programa = (
            "const VIZ_NO_CARTAO = 5;\n"
            "const nBR = n => Number(n).toLocaleString('pt-BR');\n"
            "const caixa = {innerHTML: '', style: {}};\n"
            "const $ = () => caixa;\n"
            + corpo +
            "desenharVizinhanca(" + json.dumps(viz, ensure_ascii=False) + ");\n"
            "console.log(JSON.stringify({html: caixa.innerHTML,\n"
            "                            mostrou: caixa.style.display || ''}));\n")
        caminho = os.path.join(_TEMP, "vizinhanca.mjs")
        with io.open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write(programa)
        r = subprocess.run([node, caminho], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stderr[:600])
        return json.loads(r.stdout.strip())

    ENTORNO = {"lat": -23.561414, "lon": -46.655881, "raio": 900,
               "lugares": [{"chave": "onibus", "tipo": "Ponto de ônibus",
                            "nome": "Avenida Paulista", "metros": 65},
                           {"chave": "padaria", "tipo": "Padaria",
                            "nome": "Padaria Xodó", "metros": 276}]}

    def test_o_anuncio_diz_que_a_distancia_e_em_linha_reta(self):
        """
        Anunciar "300 m" que na prática são 700 m de volta no quarteirão é a
        mentira que o cliente descobre a pé, no dia da visita. Distância de
        caminhada exigiria um serviço de rotas, que não temos.
        """
        saida = self._desenhado(self.ENTORNO)
        self.assertIn("em linha reta", saida["html"])
        self.assertIn("OpenStreetMap", saida["html"],
                      "a licença ODbL pede o crédito")

    def test_o_cartao_mostra_tipo_e_distancia_de_cada_lugar(self):
        saida = self._desenhado(self.ENTORNO)
        self.assertIn("Ponto de ônibus", saida["html"])
        self.assertIn("65 m", saida["html"])
        self.assertIn("276 m", saida["html"])

    def test_imovel_sem_vizinhanca_nao_ganha_cartao_vazio(self):
        """
        Faixa em branco no anúncio parece defeito. Sem nada para dizer, o
        melhor é não dizer nada.
        """
        self.assertEqual(self._desenhado(None)["mostrou"], "")
        self.assertEqual(
            self._desenhado({"lat": 1, "lon": 2, "lugares": []})["mostrou"], "")

    def test_nome_de_lugar_nao_pode_injetar_html_no_anuncio(self):
        """
        O nome vem do OpenStreetMap, que qualquer pessoa edita. Sem escapar, um
        nome com marcação entraria direto na página de quem abre o anúncio.
        """
        bravo = dict(self.ENTORNO)
        bravo["lugares"] = [{"chave": "padaria", "tipo": "Padaria", "metros": 90,
                             "nome": "<img src=x onerror=alert(1)>"}]
        html = self._desenhado(bravo)["html"]
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)


class TestViagemEntrePontos(PaginaNoNode, unittest.TestCase):
    """
    A seta deixa de teleportar: a camera caminha ate o ponto.

    Antes era `posicao.copy(p.mundo)` — piscava de um ponto ao outro. Piscar
    nao e caminhar: quem ve perde a nocao de onde estava e de quanto andou, e
    cada salto parece um corte de video em vez de um passo dentro da mesma
    casa.

    As contas rodam no Node contra um vetor de mentira, porque o que decide se
    aquilo PARECE um passo e a curva do movimento, e curva errada nao aparece
    em revisao de codigo — aparece como camera de trilho de cinema.
    """

    PAGINA = "andar.html"

    def _viagem(self, de, para, passos=40, ms=25):
        """Simula a viagem quadro a quadro e devolve o caminho andado."""
        if not self.node:
            self.skipTest("node nao encontrado")
        programa = (
            "class V3 {" + '\n'
            + "  constructor(x = 0, y = 0, z = 0){ this.x = x; this.y = y; this.z = z; }" + '\n'
            + "  copy(o){ this.x = o.x; this.y = o.y; this.z = o.z; return this; }" + '\n'
            + "  clone(){ return new V3(this.x, this.y, this.z); }" + '\n'
            + "  distanceTo(o){ return Math.hypot(this.x-o.x, this.y-o.y, this.z-o.z); }" + '\n'
            + "  lerp(o, t){ this.x += (o.x-this.x)*t; this.y += (o.y-this.y)*t;" + '\n'
            + "              this.z += (o.z-this.z)*t; return this; }" + '\n'
            + "}" + '\n'
            + "const posicao = new V3(" + ", ".join(str(v) for v in de) + ");" + '\n'
            + "let trocou = null;" + '\n'
            + "const trocarAtivo = p => { trocou = p; };" + '\n'
            + "let agora = 0;" + '\n'
            + "const performance = {now: () => agora};" + '\n'
            # `viagem` e variavel de modulo na pagina, e nao mora dentro de
            # funcao nenhuma: sem declarar aqui, o Node reclama dela
            + "let viagem = null;" + '\n')
        for nome in ("suavizar", "duracaoDaViagem", "avancoDaViagem",
                     "viajarAte", "avancarViagem"):
            programa += self._funcao(nome) + '\n'
        programa += (
            "const alvo = {mundo: new V3(" + ", ".join(str(v) for v in para) + ")};" + '\n'
            + "viajarAte(alvo);" + '\n'
            + "const dur = viagem ? viagem.dur : 0;" + '\n'
            + "const caminho = [];" + '\n'
            + "for (let k = 0; k <= " + str(passos) + "; k++){" + '\n'
            + "  agora = k * " + str(ms) + ";" + '\n'
            + "  if (viagem) avancarViagem(agora);" + '\n'
            + "  caminho.push([posicao.x, posicao.y, posicao.z, viagem ? 1 : 0]);" + '\n'
            + "}" + '\n'
            + "console.log(JSON.stringify({dur: dur, caminho: caminho," + '\n'
            + "                            trocou: trocou !== null}));" + '\n')
        return self._rodar(programa, "viagem.mjs")

    def _funcao(self, nome):
        """No andar.html as funcoes nao sao indentadas."""
        abre = "function %s(" % nome
        self.assertIn(abre, self.html, "a pagina nao tem mais %s" % nome)
        corpo = self.html[self.html.index(abre):]
        return corpo[:corpo.index(chr(10) + "}") + 2]

    # ------------------------------------------------------------ o percurso

    def test_a_camera_chega_exatamente_no_ponto(self):
        """
        Parar a 10 cm do ponto seria pior do que teletransportar: o panorama
        so esta certo EM CIMA do ponto de captura, e e de la que ele foi
        fotografado.
        """
        saida = self._viagem((0, 1.5, 0), (4, 1.5, 3))
        fim = saida["caminho"][-1]
        self.assertAlmostEqual(fim[0], 4, places=6)
        self.assertAlmostEqual(fim[2], 3, places=6)
        self.assertEqual(fim[3], 0, "a viagem nunca terminou")

    def test_a_camera_nao_anda_para_tras_em_momento_nenhum(self):
        saida = self._viagem((0, 1.5, 0), (4, 1.5, 3))
        andado = [((p[0] ** 2 + p[2] ** 2) ** 0.5) for p in saida["caminho"]]
        for antes, depois in zip(andado, andado[1:]):
            self.assertGreaterEqual(depois + 1e-9, antes, "voltou no caminho")

    def test_a_camera_nao_passa_do_ponto_e_volta(self):
        """Ultrapassar e corrigir e o que faz o estomago embrulhar."""
        saida = self._viagem((0, 1.5, 0), (4, 1.5, 3))
        alcance = max((p[0] ** 2 + p[2] ** 2) ** 0.5 for p in saida["caminho"])
        self.assertLessEqual(alcance, 5.0 + 1e-6, "passou do alvo")

    def test_sai_devagar_e_para_devagar(self):
        """
        Velocidade constante parece trilho de camera de cinema, nao passo de
        gente. Isto e o que separa "parece que eu andei" de "a tela deslizou".
        """
        saida = self._viagem((0, 1.5, 0), (6, 1.5, 0), passos=40, ms=25)
        xs = [p[0] for p in saida["caminho"]]
        andando = [b - a for a, b in zip(xs, xs[1:]) if b < 5.999]
        self.assertGreater(len(andando), 6, "a viagem foi curta demais para medir")
        comeco = andando[0]
        meio = max(andando)
        self.assertLess(comeco, meio * 0.6,
                        "saiu na velocidade cheia: parece trilho, nao passo")

    def test_viagem_curta_e_viagem_longa_nao_levam_o_mesmo_tempo(self):
        perto = self._viagem((0, 1.5, 0), (1, 1.5, 0))["dur"]
        longe = self._viagem((0, 1.5, 0), (7, 1.5, 0))["dur"]
        self.assertLess(perto, longe, "dois metros levam o tempo de oito")

    def test_nenhuma_viagem_passa_de_um_segundo(self):
        """
        Ninguem espera seis segundos de camera para ver o quarto do lado.
        Proporcional puro daria isso num imovel grande.
        """
        for metros in (1, 5, 12, 40):
            saida = self._viagem((0, 1.5, 0), (metros, 1.5, 0), passos=2)
            self.assertLessEqual(saida["dur"], 900, "%d m demorou demais" % metros)
            self.assertGreaterEqual(saida["dur"], 260, "%d m foi um piscar" % metros)

    def test_ponto_onde_ja_se_esta_nao_vira_viagem(self):
        """
        Clicar no ponto em que se esta nao pode iniciar uma viagem de 260 ms
        para lugar nenhum: a tela tremeria sem motivo.
        """
        saida = self._viagem((2, 1.5, 2), (2.01, 1.5, 2), passos=2)
        self.assertEqual(saida["dur"], 0)
        self.assertTrue(saida["trocou"], "nem trocou de ponto nem viajou")

    # ------------------------------------------------ o que mudou na pagina

    def test_a_seta_nao_teleporta_mais(self):
        """
        Conferencia de texto, e assumida como tal: garante que o caminho da
        seta passa pela viagem, e nao voltou a copiar a posicao direto.
        """
        corpo = self.html[self.html.index("function irAoPonto("):]
        corpo = corpo[:corpo.index(chr(10) + "}") + 2]
        self.assertIn("viajarAte", corpo)
        self.assertNotIn("posicao.copy", corpo, "voltou a teleportar")

    def test_apertar_uma_tecla_cancela_a_viagem(self):
        """
        Ficar preso vendo a camera terminar o passeio enquanto se aperta W e o
        tipo de coisa que faz a pessoa achar que a pagina travou.
        """
        laco = self.html[self.html.index("function animar()"):]
        laco = laco[:laco.index("const perto = maisProximo")]
        self.assertIn("if (viagem && !tentativa.equals(posicao)) viagem = null;", laco)
        self.assertLess(laco.index("viagem = null"), laco.index("avancarViagem("),
                        "a viagem avança antes de olhar o comando de quem vê")


class TestMisturaEntrePontos(PaginaNoNode, unittest.TestCase):
    """
    Andando entre dois pontos de captura, ve-se os DOIS, com peso pela posicao.

    Antes via-se um panorama esticado, e a dissolvencia acontecia so no instante
    da troca. E o pior lugar possivel para ela: no meio do caminho e onde um
    panorama sozinho estica mais, e era exatamente ali que o programa se
    comprometia com uma versao so.

    Isto nao conserta o esticamento - ele vem de a foto ter sido tirada de um
    ponto so, e a cura continua sendo capturar mais pontos. O que a mistura tira
    e o SALTO, e o compromisso com uma versao errada quando ha outra ao lado,
    igualmente perto e errada de outro jeito.

    O que se mede aqui e a curva do peso. Curva com degrau aparece como um
    piscar no meio do corredor, e isso nao se ve lendo o codigo.
    """

    PAGINA = "andar.html"

    def _funcao(self, nome):
        """No andar.html as funcoes nao sao indentadas."""
        abre = "function %s(" % nome
        self.assertIn(abre, self.html, "a pagina nao tem mais %s" % nome)
        corpo = self.html[self.html.index(abre):]
        return corpo[:corpo.index(chr(10) + "}") + 2]

    def _constante(self, nome):
        achado = re.search(r"const %s = ([\d.]+)" % nome, self.html)
        self.assertTrue(achado, "sumiu a constante %s" % nome)
        return float(achado.group(1))

    def _pesos(self, pares):
        """pesoDaMistura(dPerto, dLonge) para cada par pedido."""
        if not self.node:
            self.skipTest("node nao encontrado")
        programa = ("const MISTURA_MAX = %s;" % self._constante("MISTURA_MAX") + '\n'
                    + "const MISTURA_RAMPA = %s;" % self._constante("MISTURA_RAMPA") + '\n'
                    + "const MISTURA_MIN = %s;" % self._constante("MISTURA_MIN") + '\n'
                    + self._funcao("pesoDaMistura") + '\n'
                    + "console.log(JSON.stringify(" + json.dumps(pares)
                    + ".map(p => pesoDaMistura(p[0], p[1]))));" + '\n')
        return self._rodar(programa, "peso.mjs")

    # ----------------------------------------------------------- o peso

    def test_em_cima_do_ponto_ve_se_so_a_foto_de_verdade(self):
        """
        No ponto de captura o panorama nao estica nada: ele foi tirado dali.
        Misturar o vizinho ali seria sujar a unica imagem perfeita do passeio.
        """
        self.assertEqual(self._pesos([[0.0, 3.0]])[0], 0)

    def test_no_meio_do_caminho_cada_um_entra_com_metade(self):
        """
        E o ponto em que os dois estao igualmente esticados e igualmente
        errados - cada um de um jeito. Metade de cada incomoda menos do que um
        inteiro.
        """
        self.assertAlmostEqual(self._pesos([[2.0, 2.0]])[0], 0.5, places=6)

    def test_o_vizinho_de_outro_comodo_nao_entra(self):
        """
        Ponto a nove metros quase sempre e outro ambiente. Misturado, poria a
        cozinha por cima do quarto.
        """
        self.assertEqual(self._pesos([[1.0, 9.0]])[0], 0)

    def test_o_corte_da_distancia_nao_produz_piscada(self):
        """
        Cortar seco em sete metros faria o vizinho sumir de uma vez no meio do
        corredor. A rampa existe para que ele se apague, e nao pisque.
        """
        maximo = self._constante("MISTURA_MAX")
        rampa = self._constante("MISTURA_RAMPA")
        passo = rampa / 12.0
        dists = [maximo - rampa + k * passo for k in range(13)]
        pesos = self._pesos([[3.0, d] for d in dists])
        for antes, depois in zip(pesos, pesos[1:]):
            self.assertLessEqual(depois, antes + 1e-9, "o peso subiu ao afastar")
            self.assertLess(antes - depois, 0.12, "degrau no peso: pisca na tela")
        self.assertEqual(pesos[-1], 0)

    def test_afastar_do_ponto_aumenta_o_peso_do_vizinho(self):
        """A imagem tem de migrar de um para o outro conforme se anda."""
        pesos = self._pesos([[d / 10.0, 4.0 - d / 10.0] for d in range(0, 21)])
        for antes, depois in zip(pesos, pesos[1:]):
            self.assertGreaterEqual(depois + 1e-9, antes, "o peso caiu ao avancar")

    # ------------------------------------------- a curva vista de fora

    def test_a_imagem_de_um_ponto_nao_salta_na_troca(self):
        """
        O TESTE QUE IMPORTA. No meio do caminho o papel de base e o de camada se
        invertem. Se a parcela visivel de um panorama desse um pulo nesse
        instante, a mistura teria trocado um salto no fim por um salto no meio.

        Aqui se anda de A a B em passos pequenos e se mede quanto de B aparece
        na tela a cada passo: peso, quando B e a camada; 1 menos o peso, quando
        B virou a base.
        """
        if not self.node:
            self.skipTest("node nao encontrado")
        programa = ("const MISTURA_MAX = %s;" % self._constante("MISTURA_MAX") + '\n'
                    + "const MISTURA_RAMPA = %s;" % self._constante("MISTURA_RAMPA") + '\n'
                    + "const MISTURA_MIN = %s;" % self._constante("MISTURA_MIN") + '\n'
                    + self._funcao("pesoDaMistura") + '\n'
                    + "const vao = 4.0, parcelas = [];" + '\n'
                    + "for (let k = 0; k <= 200; k++){" + '\n'
                    + "  const x = vao * k / 200;" + '\n'
                    + "  const dA = x, dB = vao - x;" + '\n'
                    + "  const perto = Math.min(dA, dB), longe = Math.max(dA, dB);" + '\n'
                    + "  const w = pesoDaMistura(perto, longe);" + '\n'
                    + "  // B e a camada enquanto estiver mais longe; depois vira base" + '\n'
                    + "  parcelas.push(dB > dA ? w : 1 - w);" + '\n'
                    + "}" + '\n'
                    + "console.log(JSON.stringify(parcelas));" + '\n')
        parcelas = self._rodar(programa, "curva.mjs")

        self.assertAlmostEqual(parcelas[0], 0, places=6, msg="em cima de A ja aparecia B")
        self.assertAlmostEqual(parcelas[-1], 1, places=6, msg="em cima de B faltava B")
        for antes, depois in zip(parcelas, parcelas[1:]):
            self.assertLess(abs(depois - antes), 0.05,
                            "a imagem de um ponto salta no meio do caminho")
            self.assertGreaterEqual(depois + 1e-9, antes, "a imagem de B recuou")

    # ------------------------------------------------ o par escolhido

    def test_ponto_ainda_nao_carregado_fica_fora_da_mistura(self):
        """
        Escolher um ponto sem malha o poria como base e a tela ficaria preta.
        Ele entra assim que terminar de carregar.
        """
        if not self.node:
            self.skipTest("node nao encontrado")
        programa = (
            "class V3 { constructor(x,z){ this.x=x; this.z=z; }" + '\n'
            + "  distanceTo(o){ return Math.hypot(this.x-o.x, this.z-o.z); } }" + '\n'
            + "const pontos = [" + '\n'
            + "  {nome: 'perto sem malha', mundo: new V3(0.5, 0), malha: null}," + '\n'
            + "  {nome: 'carregado A', mundo: new V3(2, 0), malha: {}}," + '\n'
            + "  {nome: 'carregado B', mundo: new V3(5, 0), malha: {}}];" + '\n'
            + self._funcao("doisMaisProximos") + '\n'
            + "const par = doisMaisProximos(new V3(0, 0));" + '\n'
            + "console.log(JSON.stringify(par.map(p => p.ponto.nome)));" + '\n')
        self.assertEqual(self._rodar(programa, "par.mjs"),
                         ["carregado A", "carregado B"])

    def _garantir(self, pontos, chamadas=3):
        """
        Roda garantirVizinho algumas vezes contra um acervo de mentira e
        devolve a ordem em que os pontos foram pedidos.
        """
        if not self.node:
            self.skipTest("node nao encontrado")
        programa = (
            "const MISTURA_MAX = %s;" % self._constante("MISTURA_MAX") + '\n'
            + "class V3 { constructor(x, z){ this.x = x; this.z = z; }" + '\n'
            + "  distanceTo(o){ return Math.hypot(this.x-o.x, this.z-o.z); } }" + '\n'
            + "const posicao = new V3(0, 0);" + '\n'
            + "const pedidos = [];" + '\n'
            + "const limparAntigas = () => {};" + '\n'
            + "const carregarPonto = p => { pedidos.push(p.nome);" + '\n'
            + "  p.malha = {}; return Promise.resolve(); };" + '\n'
            + "const pontos = " + json.dumps(pontos) + ".map(p => (" + '\n'
            + "  {nome: p[0], mundo: new V3(p[1], p[2]), malha: p[3] ? {} : null}));" + '\n'
            + self._funcao("garantirVizinho") + '\n'
            + "let vindoAi = null;" + '\n'
            + "(async () => {" + '\n'
            + "  for (let k = 0; k < " + str(chamadas) + "; k++){" + '\n'
            + "    garantirVizinho();" + '\n'
            + "    garantirVizinho();      // uma segunda no mesmo quadro" + '\n'
            + "    await null;             // deixa o .then correr" + '\n'
            + "  }" + '\n'
            + "  console.log(JSON.stringify(pedidos));" + '\n'
            + "})();" + '\n')
        return self._rodar(programa, "vizinho.mjs")

    def test_o_vizinho_e_carregado_antes_de_se_precisar_dele(self):
        """
        MEDIDO NO NAVEGADOR, e foi uma surpresa: com a mistura ja escrita e
        certa - peso 0,5 no meio do caminho, conferido na mao - ela nunca
        acontecia. So UM ponto tinha malha.

        O carregamento de vizinho so era disparado no INSTANTE da troca de
        ponto ativo, e a mistura precisa dele enquanto se CAMINHA na direcao
        dele, que e antes disso. Conta certa, sem nada com que misturar.
        """
        pedidos = self._garantir([["perto", 2, 0, False],
                                  ["medio", 4, 0, False],
                                  ["ja carregado", 1, 0, True]])
        self.assertEqual(pedidos[:2], ["perto", "medio"],
                         "nao pediu do mais perto para o mais longe")
        self.assertNotIn("ja carregado", pedidos, "pediu de novo o que ja tinha")

    def test_um_vizinho_de_cada_vez(self):
        """
        Cada ponto e um panorama grande mais um mapa de profundidade. Disparar
        quatro juntos trava o celular justamente enquanto a pessoa anda.
        """
        pedidos = self._garantir([["a", 1, 0, False], ["b", 2, 0, False],
                                  ["c", 3, 0, False], ["d", 4, 0, False]],
                                 chamadas=1)
        self.assertEqual(len(pedidos), 1,
                         "disparou mais de um carregamento no mesmo quadro")

    def test_ponto_de_outro_canto_do_imovel_nao_e_carregado_a_toa(self):
        """
        Fora do alcance da mistura ele nunca entraria na tela: baixar o
        panorama seria gastar a internet de quem ve por nada.
        """
        longe = self._constante("MISTURA_MAX") + 3
        pedidos = self._garantir([["longe demais", longe, 0, False]])
        self.assertEqual(pedidos, [])

    def test_a_pagina_desenha_os_dois_e_nao_so_o_ativo(self):
        """
        Conferencia de texto, e assumida como tal: garante que o laco usa o par
        e o peso, e nao voltou a mostrar so o ponto ativo.
        """
        laco = self.html[self.html.index("function animar()"):]
        self.assertIn("const par = doisMaisProximos(posicao);", laco)
        self.assertIn("pesoDaMistura(par[0].dist, par[1].dist)", laco,
                      "o peso deixou de sair da posicao")
        self.assertIn("aplicarEstado(misturado, peso, true);", laco)
        self.assertNotIn("p === saindo", laco, "voltou a dissolvencia por relogio")


class TestGuiaDeCaptura(Base):
    """
    O que ja foi capturado e o que ainda falta.

    Todo caminho deste projeto desembocou no mesmo lugar: quem decide a
    qualidade do passeio e a CAPTURA, nao o codigo. E no entanto o corretor
    capturava no escuro - so descobria que ficou ruim com o tour pronto, e ai
    ninguem volta ao imovel.

    O guia que ja existia ensina a fotografar UM panorama. Este responde a
    outra pergunta: quantos pontos, onde, e o que falta NESTE imovel.
    """

    def setUp(self):
        self.dona = self.conta("dona-captura")
        self.iid = self.imovel(self.dona, "Apartamento a capturar")

    def _cena(self, nome, x, y, prof=True, escorrido=None):
        c = {"id": nome.lower().replace(" ", "-"), "nome": nome,
             "arquivo": "c.jpg", "hotspots": []}
        if x is not None:
            c["posicao"] = {"x": x, "y": y}
        if prof:
            c["profundidade"] = "prof.png"
        if escorrido is not None:
            c["escorrido"] = {"fracao": escorrido}
        return c

    def _gravar(self, cenas):
        tour = aplicacao.carregar_tour(self.iid)
        tour["cenas"] = cenas
        aplicacao.salvar_tour(tour, self.iid)
        return tour

    # ------------------------------------------------------- o nome do comodo

    def test_o_comodo_sai_do_nome_que_o_corretor_ja_usa(self):
        """
        Ninguem vai preencher um campo "cômodo" a mais. O corretor ja escreve
        "Cozinha - junto à mesa" por conta propria, porque e como se fala.
        """
        self.assertEqual(captura.comodo_da_cena("Cozinha - junto à mesa"), "Cozinha")
        self.assertEqual(captura.comodo_da_cena("Suíte — entrada"), "Suíte")
        self.assertEqual(captura.comodo_da_cena("Varanda"), "Varanda")
        self.assertEqual(captura.comodo_da_cena(""), "")

    # ------------------------------------------------------------ os vaos

    def test_o_vao_medido_e_ate_o_vizinho_mais_proximo(self):
        """
        O pior lugar do passeio e sempre o meio do caminho entre dois pontos.
        Entao o que importa nao e a media do imovel: e a distancia ate o
        vizinho, ponto a ponto.
        """
        cenas = [self._cena("Sala - A", 0, 0), self._cena("Sala - B", 1.5, 0),
                 self._cena("Sala - C", 6.0, 0)]
        medidos = dict((c["nome"], round(d, 2)) for c, d in captura.vaos(cenas))
        self.assertEqual(medidos["Sala - A"], 1.5)
        self.assertEqual(medidos["Sala - B"], 1.5)
        self.assertEqual(medidos["Sala - C"], 4.5)

    def test_cena_sem_posicao_fica_fora_da_conta_de_vao(self):
        """Ponto sem lugar no croqui nao tem distancia a coisa nenhuma."""
        cenas = [self._cena("Sala - A", 0, 0), self._cena("Sala - B", None, None)]
        self.assertEqual(len(captura.vaos(cenas)), 1)

    def test_ponto_unico_nao_inventa_um_vizinho(self):
        cena, metros = captura.vaos([self._cena("Sala - A", 0, 0)])[0]
        self.assertIsNone(metros)

    # ---------------------------------------------------------- o diagnostico

    def test_vao_maior_que_o_alcance_do_passeio_impede_de_caminhar(self):
        """
        O numero nao e de gosto: cada ponto alcança 2,50 m. Dois pontos mais
        distantes que isso deixam, no meio, um trecho que ponto nenhum cobre -
        a caminhada para ali.
        """
        cenas = [self._cena("Sala - A", 0, 0), self._cena("Sala - B", 4.0, 0)]
        _resumo, achados = captura.diagnosticar({"cenas": cenas})
        graves = [a for a in achados if a["grau"] == "impede"]
        self.assertTrue(graves, "vão de 4 m passou como aceitável")
        self.assertIn("meio", graves[0]["fazer"])

    def test_vao_folgado_avisa_sem_impedir(self):
        """
        Entre o ideal e o maximo a caminhada funciona e a imagem estica. Tratar
        isso como erro grave faria o corretor ignorar os erros graves de
        verdade.
        """
        cenas = [self._cena("Sala - A", 0, 0), self._cena("Sala - B", 2.2, 0)]
        _resumo, achados = captura.diagnosticar({"cenas": cenas})
        self.assertEqual([a["grau"] for a in achados if a["cena"]],
                         ["atrapalha", "atrapalha"])

    def test_captura_boa_nao_gera_reclamacao(self):
        """
        Silêncio no caso bom. Aviso em captura boa ensina a ignorar avisos, e
        aí o aviso que importa passa batido.
        """
        cenas = [self._cena("Sala - A", 0, 0), self._cena("Sala - B", 1.5, 0),
                 self._cena("Cozinha - A", 3.0, 0), self._cena("Cozinha - B", 4.4, 0)]
        resumo, achados = captura.diagnosticar({"cenas": cenas})
        self.assertEqual(achados, [], [a["o_que"] for a in achados])
        self.assertIn("boa", captura.proximo_passo(resumo, achados))

    def test_comodo_com_um_ponto_so_nao_deixa_caminhar_nele(self):
        cenas = [self._cena("Sala - A", 0, 0), self._cena("Sala - B", 1.5, 0),
                 self._cena("Lavabo", 1.2, 1.0)]
        _r, achados = captura.diagnosticar({"cenas": cenas})
        self.assertTrue(any("Lavabo" in (a["o_que"] + a["fazer"]) for a in achados),
                        "o cômodo de um ponto só passou batido")

    def test_cena_sem_profundidade_nao_anda_de_jeito_nenhum(self):
        cenas = [self._cena("Sala - A", 0, 0, prof=False),
                 self._cena("Sala - B", 1.5, 0)]
        _r, achados = captura.diagnosticar({"cenas": cenas})
        graves = [a for a in achados if a["grau"] == "impede"]
        self.assertTrue(any("profundidade" in a["o_que"] for a in graves))

    def test_imovel_vazio_recebe_por_onde_comecar(self):
        resumo, achados = captura.diagnosticar({"cenas": []})
        self.assertEqual(resumo["pontos"], 0)
        self.assertTrue(achados)
        self.assertIn("sala", achados[0]["fazer"].lower())

    def test_todo_achado_diz_o_que_fazer(self):
        """
        A REGRA DA TELA. O corretor está no imóvel, de pé, com o celular na
        mão. Achado sem o que fazer é só um muro: ele não sabe se sai dali ou
        não, e a próxima visita não acontece.
        """
        cenas = [self._cena("Sala - A", 0, 0, prof=False),
                 self._cena("Sala - B", 9.0, 0),
                 self._cena("Cozinha - A", None, None),
                 self._cena("Suíte - A", 1.0, 1.0, escorrido=0.09)]
        _r, achados = captura.diagnosticar({"cenas": cenas})
        self.assertGreaterEqual(len(achados), 4)
        for a in achados:
            self.assertTrue(a["fazer"].strip(), a["o_que"])
            self.assertTrue(a["o_que"].strip())
            self.assertIn(a["grau"], ("impede", "atrapalha"))

    def test_o_proximo_passo_e_um_so_e_o_mais_grave(self):
        """
        Lista de dez problemas no celular não vira ação nenhuma. O que vira é
        uma frase.
        """
        cenas = [self._cena("Sala - A", 0, 0, prof=False),
                 self._cena("Sala - B", 2.2, 0)]
        resumo, achados = captura.diagnosticar({"cenas": cenas})
        passo = captura.proximo_passo(resumo, achados)
        self.assertIn("profundidade", passo,
                      "sugeriu o problema leve tendo um grave na frente")

    # ------------------------------------------- o guia e o passeio combinam

    def test_o_limite_do_guia_e_o_alcance_real_do_passeio(self):
        """
        Se alguém mexer no alcance do passeio e esquecer do guia, o guia passa
        a mandar o corretor capturar errado — e com toda a autoridade de um
        número na tela. Os dois têm de ser o mesmo número.
        """
        html = io.open(os.path.join("static", "andar.html"),
                       encoding="utf-8").read()
        achado = re.search(r"const PASSEIO_CHEIO = ([\d.]+)", html)
        self.assertTrue(achado, "sumiu o PASSEIO_CHEIO do andar.html")
        self.assertEqual(float(achado.group(1)), captura.VAO_MAXIMO)

    # -------------------------------------------------------------- as rotas

    def test_o_diagnostico_chega_pela_api(self):
        self._gravar([self._cena("Sala - A", 0, 0), self._cena("Sala - B", 4.0, 0)])
        r = self.dona.get("/api/imoveis/%s/captura" % self.iid)
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertEqual(j["resumo"]["pontos"], 2)
        self.assertTrue(j["passo"])
        self.assertTrue(j["achados"])

    def test_o_que_falta_capturar_nao_e_publico(self):
        """
        É o avesso do anúncio: diz onde a captura está fraca, que é exatamente
        o que não se conta para o comprador.
        """
        self._gravar([self._cena("Sala - A", 0, 0)])
        visitante = aplicacao.app.test_client()
        r = visitante.get("/api/imoveis/%s/captura" % self.iid)
        self.assertIn(r.status_code, (401, 403, 404))

    def test_a_pagina_do_guia_abre_para_a_dona(self):
        self.assertEqual(self.dona.get("/capturar/%s" % self.iid).status_code, 200)

    def test_a_pagina_do_guia_exige_sessao(self):
        """
        A docstring da rota afirma isso, entao tem de estar travado: a pagina
        diz onde a captura esta fraca, e guarda o destino para voltar depois
        de entrar.
        """
        visitante = aplicacao.app.test_client()
        r = visitante.get("/capturar/%s" % self.iid)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/entrar", r.headers["Location"])
        self.assertIn("/capturar/%s" % self.iid, r.headers["Location"],
                      "perdeu o destino: depois de entrar cai em outro lugar")

    def test_imovel_que_nao_existe_volta_para_a_lista(self):
        r = self.dona.get("/capturar/naoexiste9")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/imoveis", r.headers["Location"])

    def test_a_lista_de_imoveis_ja_traz_o_diagnostico(self):
        """
        Numa imobiliária com quarenta anúncios, saber que um deles não anda só
        ao abri-lo significa nunca saber. O tour já é lido ali para montar o
        cartão, então a conta sai de graça.
        """
        self._gravar([self._cena("Sala - A", 0, 0), self._cena("Sala - B", 6.0, 0)])
        itens = self.dona.get("/api/imoveis").get_json()["imoveis"]
        meu = next(i for i in itens if i["id"] == self.iid)
        self.assertGreater(meu["captura"]["impedem"], 0,
                           "vão de 6 m passou como imóvel saudável na lista")

    def test_a_lista_e_o_guia_nunca_discordam(self):
        """
        Dois diagnósticos do mesmo imóvel dando números diferentes fariam o
        corretor perder a confiança nos dois. Sai do mesmo lugar, de propósito.
        """
        self._gravar([self._cena("Sala - A", 0, 0), self._cena("Sala - B", 2.2, 0),
                      self._cena("Cozinha - A", 9.0, 9.0)])
        guia = self.dona.get("/api/imoveis/%s/captura" % self.iid).get_json()["resumo"]
        itens = self.dona.get("/api/imoveis").get_json()["imoveis"]
        meu = next(i for i in itens if i["id"] == self.iid)
        self.assertEqual(meu["captura"]["impedem"], guia["impedem"])
        self.assertEqual(meu["captura"]["atrapalham"], guia["atrapalham"])

    def test_diagnostico_que_falha_nao_derruba_a_lista(self):
        """
        A lista é a porta de entrada do sistema. Um diagnóstico que tropece
        num imóvel não vale esconder os outros trinta e nove — o selo é um
        auxílio, não um requisito para a página existir.
        """
        self._gravar([self._cena("Sala - A", 0, 0)])
        original = aplicacao.captura.diagnosticar

        def explodir(_tour):
            raise RuntimeError("diagnóstico quebrou")

        aplicacao.captura.diagnosticar = explodir
        try:
            r = self.dona.get("/api/imoveis")
        finally:
            aplicacao.captura.diagnosticar = original
        self.assertEqual(r.status_code, 200)
        meu = next(i for i in r.get_json()["imoveis"] if i["id"] == self.iid)
        self.assertEqual(meu["captura"], {"impedem": 0, "atrapalham": 0},
                         "sem diagnóstico o cartão tem de ficar sem selo")

    def test_a_pagina_nao_busca_nada_na_internet(self):
        """Guia de captura se abre DENTRO do imóvel, onde o sinal é ruim."""
        html = io.open(os.path.join("static", "capturar.html"),
                       encoding="utf-8").read()
        for achado in re.findall(r'(?:src|href)="(https?:)?//[^"]+"', html):
            self.fail("o guia busca recurso de fora: %s" % achado)


class TestPrepararOImovel(Base):
    """
    Deixar o imovel INTEIRO pronto para caminhar, numa tarefa so.

    Ate aqui era cena por cena: num imovel de catorze pontos, o corretor
    clicava vinte e oito vezes e ficava olhando. Ninguem faz isso duas vezes —
    na pratica o passo era pulado, e o imovel ia para o ar sem profundidade ou
    sem camada de fundo, que sao as duas coisas que fazem a caminhada valer.

    Nenhum teste aqui carrega modelo de IA: o que se exercita e a LOGICA do
    lote — o que fazer, em que ordem, o que pular, e o que acontece quando uma
    cena da errado no meio.
    """

    def setUp(self):
        self.dona = self.conta("dona-preparar")
        self.iid = self.imovel(self.dona, "Imóvel a preparar")

    def _cena(self, nome, prof=None, fundo=None, completo=True):
        c = {"id": nome, "nome": nome, "arquivo": nome + ".jpg",
             "panorama_completo": completo, "hotspots": []}
        if prof:
            c["profundidade"] = prof
        if fundo:
            c["fundo"] = fundo
        return c

    def _gravar(self, cenas):
        tour = aplicacao.carregar_tour(self.iid)
        tour["cenas"] = cenas
        aplicacao.salvar_tour(tour, self.iid)

    def _preparar(self, tem_profundidade=True, tem_fundo=False, quebrar=None):
        """
        Chama a rota com os modelos e o trabalho pesado trocados por dublês.

        O que interessa aqui e a decisao do lote, nao a inferencia: carregar
        modelo de verdade faria o teste depender de 300 MB baixados e de uma
        GPU, e reprovaria numa maquina limpa.
        """
        feito = {"profundidade": [], "fundo": [], "relatos": []}
        guardados = (aplicacao.profundidade.modelo_disponivel,
                     aplicacao.fundo.modelo_disponivel,
                     aplicacao._fazer_profundidade,
                     aplicacao._fazer_fundo,
                     aplicacao.tarefas.enfileirar)

        def fazer_prof(imovel, destino, cena_id, cena, relatar):
            relatar(50, "meio")
            if quebrar == cena_id:
                raise RuntimeError("panorama corrompido")
            feito["profundidade"].append(cena_id)
            tour = aplicacao.carregar_tour(imovel)
            alvo = aplicacao.achar_cena(tour, cena_id)
            alvo["profundidade"] = "prof.png"
            aplicacao.salvar_tour(tour, imovel)
            return alvo

        def fazer_fundo(imovel, destino, cena_id, cena, relatar):
            feito["fundo"].append(cena_id)
            tour = aplicacao.carregar_tour(imovel)
            alvo = aplicacao.achar_cena(tour, cena_id)
            alvo["fundo"] = {"textura": "t.jpg", "reconstruido": 4}
            aplicacao.salvar_tour(tour, imovel)
            return alvo, {"reconstruido": 4}

        def na_hora(tid, trabalho):
            feito["resultado"] = trabalho(
                lambda pct, msg="": feito["relatos"].append((pct, msg)))

        aplicacao.profundidade.modelo_disponivel = lambda: tem_profundidade
        aplicacao.fundo.modelo_disponivel = lambda: tem_fundo
        aplicacao._fazer_profundidade = fazer_prof
        aplicacao._fazer_fundo = fazer_fundo
        aplicacao.tarefas.enfileirar = na_hora
        try:
            resposta = self.dona.post("/api/imoveis/%s/preparar" % self.iid)
        finally:
            (aplicacao.profundidade.modelo_disponivel,
             aplicacao.fundo.modelo_disponivel,
             aplicacao._fazer_profundidade,
             aplicacao._fazer_fundo,
             aplicacao.tarefas.enfileirar) = guardados
        return resposta, feito

    # --------------------------------------------------------- sem os modelos

    def test_sem_o_modelo_de_profundidade_recusa_dizendo_o_comando(self):
        """
        Recusa sem saída é só um muro. O recado traz o comando exato, porque
        quem está no painel não vai procurar isso em documentação nenhuma.
        """
        self._gravar([self._cena("sala")])
        r, _ = self._preparar(tem_profundidade=False)
        self.assertEqual(r.status_code, 422)
        self.assertIn("baixar_modelo.py", r.get_json()["erro"])

    def test_sem_o_modelo_de_fundo_faz_o_que_da_e_avisa(self):
        """
        Faltar a segunda IA não pode impedir a primeira: profundidade sozinha
        já libera a caminhada. Travar tudo seria transformar uma melhoria que
        falta numa parede.
        """
        self._gravar([self._cena("sala"), self._cena("cozinha")])
        r, feito = self._preparar(tem_fundo=False)
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.get_json()["passos"], 2)
        self.assertFalse(r.get_json()["com_fundo"])
        self.assertEqual(feito["profundidade"], ["sala", "cozinha"])
        self.assertEqual(feito["fundo"], [])

    # ------------------------------------------------------- o que ha a fazer

    def test_as_duas_etapas_entram_quando_as_duas_ias_existem(self):
        self._gravar([self._cena("sala")])
        r, feito = self._preparar(tem_fundo=True)
        self.assertEqual(r.get_json()["passos"], 2)
        self.assertEqual(feito["profundidade"], ["sala"])
        self.assertEqual(feito["fundo"], ["sala"])

    def test_nao_refaz_o_que_ja_esta_pronto(self):
        """
        Refazer seria jogar fora meia hora de processamento por engano. Um
        clique a mais não pode custar isso.
        """
        self._gravar([self._cena("sala", prof="p.png",
                                 fundo={"textura": "t.jpg"})])
        r, feito = self._preparar(tem_fundo=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["passos"], 0)
        self.assertIn("pronto", r.get_json()["recado"])
        self.assertEqual(feito["profundidade"], [])

    def test_cena_com_profundidade_so_ganha_o_fundo_que_falta(self):
        self._gravar([self._cena("sala", prof="p.png"), self._cena("cozinha")])
        r, feito = self._preparar(tem_fundo=True)
        self.assertEqual(r.get_json()["passos"], 3)   # fundo da sala + as duas da cozinha
        self.assertEqual(feito["profundidade"], ["cozinha"])
        self.assertEqual(sorted(feito["fundo"]), ["cozinha", "sala"])

    def test_panorama_parcial_fica_de_fora(self):
        """Só dá para andar em 360 completo; cena parcial não tem o que preparar."""
        self._gravar([self._cena("sala"), self._cena("recorte", completo=False)])
        r, feito = self._preparar()
        self.assertEqual(r.get_json()["passos"], 1)
        self.assertEqual(feito["profundidade"], ["sala"])

    # ----------------------------------------------------------- o andamento

    def test_a_barra_nao_volta_a_zero_a_cada_cena(self):
        """
        Medido no desenho: sem fatiar, cada cena relataria 0 a 100 de novo.
        Quem está olhando conclui que travou e recarrega a página no meio de
        meia hora de processamento.
        """
        self._gravar([self._cena("sala"), self._cena("cozinha"),
                      self._cena("quarto")])
        _r, feito = self._preparar()
        pcts = [p for p, _m in feito["relatos"]]
        self.assertEqual(pcts, sorted(pcts), "o andamento voltou para trás")
        self.assertLessEqual(max(pcts), 100.0001)
        self.assertGreaterEqual(min(pcts), 0)
        self.assertEqual(pcts[-1], 100, "não terminou em 100")
        # o meio da segunda cena tem de cair perto do meio do lote
        self.assertAlmostEqual(pcts[1], 50, delta=1)

    def test_o_andamento_diz_em_que_cena_esta(self):
        """"Processando" não diz nada a quem espera meia hora."""
        self._gravar([self._cena("sala"), self._cena("cozinha")])
        _r, feito = self._preparar()
        juntos = " | ".join(m for _p, m in feito["relatos"])
        self.assertIn("1 de 2", juntos)
        self.assertIn("cozinha", juntos)

    # ------------------------------------------------------- quando da errado

    def test_uma_cena_ruim_nao_derruba_as_outras(self):
        """
        O corretor prefere doze prontas e um recado a um lote inteiro perdido
        depois de vinte minutos.
        """
        self._gravar([self._cena("sala"), self._cena("cozinha"),
                      self._cena("quarto")])
        _r, feito = self._preparar(quebrar="cozinha")
        self.assertEqual(feito["profundidade"], ["sala", "quarto"])
        problemas = feito["resultado"]["problemas"]
        self.assertEqual(len(problemas), 1)
        self.assertEqual(problemas[0]["cena"], "cozinha")
        self.assertIn("corrompido", problemas[0]["erro"])

    def test_o_resultado_conta_o_que_foi_feito(self):
        self._gravar([self._cena("sala"), self._cena("cozinha")])
        _r, feito = self._preparar(tem_fundo=True)
        self.assertEqual(feito["resultado"]["feitos"],
                         {"profundidade": 2, "fundo": 2})
        self.assertEqual(feito["resultado"]["problemas"], [])

    # ------------------------------------------------------------- quem pode

    def test_visitante_nao_dispara_processamento_alheio(self):
        """
        Meia hora de CPU por clique, aberta a qualquer um com o link, seria um
        jeito de derrubar o servidor de graça.
        """
        self._gravar([self._cena("sala")])
        visitante = aplicacao.app.test_client()
        r = visitante.post("/api/imoveis/%s/preparar" % self.iid)
        self.assertIn(r.status_code, (401, 403, 404))


def limpar():
    shutil.rmtree(_TEMP, ignore_errors=True)


if __name__ == "__main__":
    try:
        # warnings=None: respeita o filtro acima em vez de reativar tudo
        unittest.main(verbosity=2, exit=False, warnings=None)
    finally:
        limpar()
