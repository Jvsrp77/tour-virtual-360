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
import shutil
import hashlib
import tempfile
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
    40 escritas simultaneas perdiam 27 antes das travas por imovel existirem:
    duas requisicoes liam o mesmo tour.json e a segunda apagava a primeira.
    """

    def test_escritas_simultaneas_nao_se_perdem(self):
        dona = self.conta("concorrencia")
        iid = self.imovel(dona, "Concorrência")
        quantas = 40

        def envia(n):
            c = self.app.test_client()
            c.post("/api/imoveis/%s/leads" % iid,
                   json={"nome": "visitante %d" % n, "telefone": str(n)})

        threads = [threading.Thread(target=envia, args=(n,)) for n in range(quantas)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        leads = dona.get("/api/imoveis/%s/leads" % iid).get_json()["leads"]
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


def limpar():
    shutil.rmtree(_TEMP, ignore_errors=True)


if __name__ == "__main__":
    try:
        # warnings=None: respeita o filtro acima em vez de reativar tudo
        unittest.main(verbosity=2, exit=False, warnings=None)
    finally:
        limpar()
