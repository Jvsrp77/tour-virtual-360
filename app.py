# -*- coding: utf-8 -*-
"""
Tour Virtual - servidor do prototipo.

Fluxo: fotos entram -> servidor costura em panorama 360 -> painel liga as cenas
com hotspots -> visualizador publica o tour navegavel.
"""
import os
import io
import json
import uuid
import shutil
import zipfile
import threading
import traceback
from datetime import datetime

from flask import (Flask, Blueprint, g, request, jsonify, send_from_directory,
                   send_file, redirect, Response, abort)

import cv2

import stitcher
import cena_demo
import profundidade

RAIZ = os.path.dirname(os.path.abspath(__file__))
PASTA_DADOS = os.path.join(RAIZ, "data")
PASTA_UPLOADS = os.path.join(PASTA_DADOS, "uploads")
PASTA_IMOVEIS = os.path.join(PASTA_DADOS, "imoveis")

for p in (PASTA_DADOS, PASTA_UPLOADS, PASTA_IMOVEIS):
    os.makedirs(p, exist_ok=True)


# ----------------------------------------------------------------- imoveis
# Cada imovel e uma pasta isolada, com o proprio tour.json e as proprias cenas.
# Assim dois imoveis nunca se misturam e apagar um nao mexe no outro.

def pasta_imovel(imovel_id):
    return os.path.join(PASTA_IMOVEIS, imovel_id)


def arq_tour(imovel_id):
    return os.path.join(pasta_imovel(imovel_id), "tour.json")


def pasta_cenas(imovel_id=None):
    caminho = os.path.join(pasta_imovel(imovel_id or g.imovel), "scenes")
    os.makedirs(caminho, exist_ok=True)
    return caminho


def imovel_existe(imovel_id):
    return bool(imovel_id) and os.path.exists(arq_tour(imovel_id))


def listar_imoveis():
    itens = []
    for iid in sorted(os.listdir(PASTA_IMOVEIS)):
        if not imovel_existe(iid):
            continue
        tour = carregar_tour(iid)
        capa = next((c["arquivo"] for c in tour["cenas"]), None)
        itens.append({
            "id": iid,
            "titulo": tour.get("titulo") or "Imóvel sem título",
            "endereco": tour.get("endereco", ""),
            "preco": tour.get("preco", ""),
            "ambientes": len(tour["cenas"]),
            "com_profundidade": sum(1 for c in tour["cenas"] if c.get("profundidade")),
            "leads": len(tour.get("leads_capturados", [])),
            "capa": capa,
            "criado_em": tour.get("criado_em", ""),
        })
    itens.sort(key=lambda i: i["criado_em"], reverse=True)
    return itens


def criar_imovel(titulo):
    iid = uuid.uuid4().hex[:10]
    os.makedirs(os.path.join(pasta_imovel(iid), "scenes"), exist_ok=True)
    tour = json.loads(json.dumps(TOUR_PADRAO))
    tour["titulo"] = titulo or "Imóvel sem título"
    tour["criado_em"] = datetime.now().isoformat(timespec="seconds")
    salvar_tour(tour, iid)
    return iid


def migrar_formato_antigo():
    """
    Move o tour unico do formato antigo (data/tour.json + data/scenes) para dentro
    de data/imoveis/<id>/. Roda uma vez so, na primeira subida apos a atualizacao.
    """
    antigo_tour = os.path.join(PASTA_DADOS, "tour.json")
    antiga_cenas = os.path.join(PASTA_DADOS, "scenes")
    if not os.path.exists(antigo_tour):
        return None

    iid = uuid.uuid4().hex[:10]
    destino = pasta_imovel(iid)
    os.makedirs(destino, exist_ok=True)
    shutil.move(antigo_tour, arq_tour(iid))
    if os.path.exists(antiga_cenas):
        shutil.move(antiga_cenas, os.path.join(destino, "scenes"))
    else:
        os.makedirs(os.path.join(destino, "scenes"), exist_ok=True)

    tour = carregar_tour(iid)
    tour.setdefault("criado_em", datetime.now().isoformat(timespec="seconds"))
    salvar_tour(tour, iid)
    print("  imovel existente migrado para data/imoveis/%s" % iid)
    return iid

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024   # 300 MB por requisicao

# Todas as rotas de conteudo vivem sob um imovel. O Blueprint carrega o id no
# proprio caminho, entao nenhuma rota precisa receber o imovel como parametro.
api = Blueprint("api", __name__, url_prefix="/api/imoveis/<imovel>")


@api.url_value_preprocessor
def _pegar_imovel(endpoint, valores):
    g.imovel = valores.pop("imovel", None)


# Uma trava por imovel. Quase toda rota que escreve faz ler-alterar-gravar; sem
# serializar, duas requisicoes leem a mesma versao e a segunda apaga o que a
# primeira gravou. Num teste com 40 visitas simultaneas, 27 se perdiam.
_TRAVAS = {}
_TRAVA_MESTRA = threading.Lock()

ROTAS_PESADAS = {"api.api_costurar", "api.api_importar_varredura",
                 "api.api_importar_360", "api.api_gerar_profundidade"}


def trava_do_imovel(imovel_id):
    with _TRAVA_MESTRA:
        return _TRAVAS.setdefault(imovel_id, threading.RLock())


@api.before_request
def _exigir_imovel():
    if not imovel_existe(g.imovel):
        return jsonify({"ok": False, "erro": "Imóvel não encontrado."}), 404
    # Rotas pesadas (costura, profundidade) levam dezenas de segundos. Se
    # segurassem a trava o tempo todo, um visitante ficaria esperando a costura
    # terminar para registrar a visita — medi 10,7s de espera. Elas travam
    # sozinhas, so no momento de gravar o tour.json.
    if request.method != "GET" and request.endpoint not in ROTAS_PESADAS:
        g.trava = trava_do_imovel(g.imovel)
        g.trava.acquire()


@api.teardown_request
def _soltar_trava(erro=None):
    trava = g.pop("trava", None)
    if trava is not None:
        trava.release()

TOUR_PADRAO = {
    "titulo": "Imovel sem titulo",
    "descricao": "",
    "endereco": "",
    "preco": "",
    "logo": "",
    "cor": "#e07b39",
    "cena_inicial": None,
    "lead": {
        "ativo": True,
        "titulo": "Gostou do imovel?",
        "texto": "Deixe seu contato que um corretor fala com voce.",
        "segundos": 25,
    },
    "cenas": [],
    "leads_capturados": [],
    "visitas": [],
}


# ------------------------------------------------------------------ dados

def carregar_tour(imovel_id=None):
    caminho = arq_tour(imovel_id or g.imovel)
    if not os.path.exists(caminho):
        return json.loads(json.dumps(TOUR_PADRAO))
    with open(caminho, "r", encoding="utf-8") as f:
        tour = json.load(f)
    for chave, valor in TOUR_PADRAO.items():          # completa campos novos
        tour.setdefault(chave, valor)
    return tour


def salvar_tour(tour, imovel_id=None):
    """
    Grava num arquivo temporario e so entao troca pelo definitivo.

    Escrever por cima do arquivo original nao serve: outra requisicao pode le-lo
    no meio da gravacao e encontrar JSON pela metade. os.replace troca o arquivo
    de uma vez, entao quem le sempre pega a versao inteira, velha ou nova.
    """
    caminho = arq_tour(imovel_id or g.imovel)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    temporario = caminho + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(tour, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporario, caminho)


def achar_cena(tour, cena_id):
    return next((c for c in tour["cenas"] if c["id"] == cena_id), None)


def montar_cena(nome, arquivo, largura, altura, origem, info=None):
    """
    info vem da costura e traz a cobertura medida a partir da orientacao das fotos.
    Sem ele (foto 360 importada ou cena demo) a cobertura e deduzida da proporcao.
    """
    if info:
        haov, vaov = info["haov"], info["vaov"]
        completa = bool(info["fechada"])
    else:
        completa = stitcher.eh_equirretangular(largura, altura)
        haov, vaov = stitcher.cobertura_angular(largura, altura)
        if completa:
            haov, vaov = 360.0, 180.0

    cena = {
        "id": uuid.uuid4().hex[:10],
        "nome": nome,
        "arquivo": arquivo,
        "largura": largura,
        "altura": altura,
        "origem": origem,                  # costura | equirretangular | demo
        "panorama_completo": completa,
        "haov": round(haov, 2),
        "vaov": round(vaov, 2),
        "vista_inicial": {"yaw": 0, "pitch": 0, "hfov": 100},
        "hotspots": [],
    }
    if info:
        cena["captura"] = {
            "fileiras": info["fileiras"],
            "volta_fechada": bool(info["fechada"]),
            "maior_buraco": round(info["maior_buraco"], 1),
            "fov_foto": round(info["fov"], 1),
        }
    return cena


# ------------------------------------------------------------------ paginas

@app.route("/")
def home():
    return redirect("/imoveis")


@app.route("/imoveis")
def pagina_imoveis():
    return send_from_directory("static", "imoveis.html")


@app.route("/painel/<imovel>")
def painel(imovel):
    if not imovel_existe(imovel):
        return redirect("/imoveis")
    return send_from_directory("static", "admin.html")


@app.route("/tour/<imovel>")
def visualizador(imovel):
    if not imovel_existe(imovel):
        return redirect("/imoveis")
    return send_from_directory("static", "viewer.html")


@app.route("/andar/<imovel>")
def andar(imovel):
    if not imovel_existe(imovel):
        return redirect("/imoveis")
    return send_from_directory("static", "andar.html")


@app.route("/data/<imovel>/scenes/<path:nome>")
def arquivo_cena(imovel, nome):
    if not imovel_existe(imovel):
        abort(404)
    return send_from_directory(pasta_cenas(imovel), nome)


# --------------------------------------------------------- lista de imoveis

@app.route("/api/imoveis", methods=["GET"])
def api_listar_imoveis():
    return jsonify({"ok": True, "imoveis": listar_imoveis()})


@app.route("/api/imoveis", methods=["POST"])
def api_criar_imovel():
    titulo = (request.get_json(silent=True) or {}).get("titulo", "").strip()
    iid = criar_imovel(titulo)
    return jsonify({"ok": True, "id": iid})


@app.route("/api/imoveis/<imovel>", methods=["DELETE"])
def api_remover_imovel(imovel):
    """Apaga o imovel inteiro: tour, cenas, mapas de profundidade e leads."""
    if not imovel_existe(imovel):
        return jsonify({"ok": False, "erro": "Imóvel não encontrado."}), 404
    shutil.rmtree(pasta_imovel(imovel), ignore_errors=True)
    return jsonify({"ok": True})


@app.route("/data/uploads/<path:nome>")
def arquivo_upload(nome):
    return send_from_directory(PASTA_UPLOADS, nome)


# ------------------------------------------------------------------ api tour

@api.route("/tour", methods=["GET"])
def api_obter_tour():
    return jsonify(carregar_tour())


@api.route("/tour", methods=["PUT"])
def api_salvar_tour():
    tour = carregar_tour()
    dados = request.get_json(force=True)
    for campo in ("titulo", "descricao", "endereco", "preco", "cor",
                  "cena_inicial", "lead", "logo"):
        if campo in dados:
            tour[campo] = dados[campo]
    salvar_tour(tour)
    return jsonify({"ok": True, "tour": tour})


@api.route("/tour/reiniciar", methods=["POST"])
def api_reiniciar():
    for pasta in (pasta_cenas(), PASTA_UPLOADS):
        shutil.rmtree(pasta, ignore_errors=True)
        os.makedirs(pasta, exist_ok=True)
    if os.path.exists(ARQ_TOUR):
        os.remove(ARQ_TOUR)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ api cenas

@api.route("/cenas/costurar", methods=["POST"])
def api_costurar():
    """Recebe N fotos de um mesmo ambiente e costura numa panoramica."""
    arquivos = request.files.getlist("fotos")
    nome = (request.form.get("nome") or "Ambiente").strip()

    if len(arquivos) < 2:
        return jsonify({"ok": False,
                        "erro": "Selecione pelo menos 2 fotos do mesmo ambiente."}), 400

    temporarios = []
    try:
        lote = os.path.join(PASTA_UPLOADS, uuid.uuid4().hex[:10])
        os.makedirs(lote, exist_ok=True)
        for i, f in enumerate(arquivos):
            ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                ext = ".jpg"
            destino = os.path.join(lote, "foto_%02d%s" % (i, ext))
            f.save(destino)
            temporarios.append(destino)

        arquivo, largura, altura, info = stitcher.costurar(temporarios, pasta_cenas())

        with trava_do_imovel(g.imovel):
            tour = carregar_tour()
            cena = montar_cena(nome, arquivo, largura, altura, "costura", info)
            tour["cenas"].append(cena)
            if not tour["cena_inicial"]:
                tour["cena_inicial"] = cena["id"]
            salvar_tour(tour)

        avisos = []
        if not info["fechada"]:
            avisos.append(
                "Você cobriu %.0f graus, com um vão de %.0f graus sem foto. O ambiente "
                "abre como panorama parcial. Para virar 360 completo, feche a volta."
                % (info["haov"], info["maior_buraco"]))
        if info["fileiras"] == 1:
            avisos.append(
                "Captura em 1 fileira: teto e chão foram preenchidos por aproximação. "
                "Fotografe também com o celular inclinado para cima e para baixo se "
                "quiser teto e chão reais.")

        return jsonify({"ok": True, "cena": cena, "fotos_usadas": len(temporarios),
                        "avisos": avisos})

    except stitcher.ErroCostura as e:
        return jsonify({"ok": False, "erro": str(e)}), 422
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "erro": "Erro inesperado: %s" % e}), 500


@api.route("/cenas/varredura", methods=["POST"])
def api_importar_varredura():
    """Recebe o panorama do modo Panorama do celular (projecao cilindrica)."""
    arquivos = request.files.getlist("fotos")
    nome_base = (request.form.get("nome") or "").strip()
    try:
        haov = float(request.form.get("haov") or 360)
    except ValueError:
        haov = 360.0
    if not arquivos:
        return jsonify({"ok": False, "erro": "Nenhum arquivo enviado."}), 400

    criadas, avisos, prontas = [], [], []
    try:
        for f in arquivos:
            ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
            temp = os.path.join(PASTA_UPLOADS, "%s%s" % (uuid.uuid4().hex[:10], ext))
            f.save(temp)

            arquivo, largura, altura, info = stitcher.importar_varredura(
                temp, pasta_cenas(), haov)
            rotulo = nome_base or os.path.splitext(f.filename)[0][:40] or "Ambiente"
            prontas.append(montar_cena(rotulo, arquivo, largura, altura, "varredura", info))

            avisos.append(
                "Varredura convertida: %.0f graus na horizontal e %.0f na vertical. "
                "Teto e chão foram preenchidos por aproximação — o modo Panorama do "
                "celular não alcança essas partes." % (info["haov"], info["fov"]))

        with trava_do_imovel(g.imovel):
            tour = carregar_tour()
            tour["cenas"].extend(prontas)
            criadas = prontas
            if criadas and not tour["cena_inicial"]:
                tour["cena_inicial"] = criadas[0]["id"]
            salvar_tour(tour)
        return jsonify({"ok": True, "cenas": criadas, "avisos": avisos})
    except stitcher.ErroCostura as e:
        return jsonify({"ok": False, "erro": str(e)}), 422
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "erro": str(e)}), 500


@api.route("/cenas/importar360", methods=["POST"])
def api_importar_360():
    """Recebe uma foto 360 ja pronta (camera 360 ou app de celular)."""
    arquivos = request.files.getlist("fotos")
    nome_base = (request.form.get("nome") or "").strip()
    if not arquivos:
        return jsonify({"ok": False, "erro": "Nenhum arquivo enviado."}), 400

    criadas, avisos = [], []
    try:
        for f in arquivos:
            ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
            temp = os.path.join(PASTA_UPLOADS, "%s%s" % (uuid.uuid4().hex[:10], ext))
            f.save(temp)
            arquivo, largura, altura = stitcher.importar_equirretangular(temp, pasta_cenas())

            rotulo = nome_base or os.path.splitext(f.filename)[0][:40] or "Ambiente"
            cena = montar_cena(rotulo, arquivo, largura, altura, "equirretangular")
            if not cena["panorama_completo"]:
                avisos.append(
                    "A foto %s nao esta na proporcao 2:1 (esta %dx%d). Vai abrir como "
                    "foto parcial, sem giro completo." % (rotulo, largura, altura))
            criadas.append(cena)

        with trava_do_imovel(g.imovel):
            tour = carregar_tour()
            tour["cenas"].extend(criadas)
            if criadas and not tour["cena_inicial"]:
                tour["cena_inicial"] = criadas[0]["id"]
            salvar_tour(tour)
        return jsonify({"ok": True, "cenas": criadas, "avisos": avisos})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "erro": str(e)}), 500


@api.route("/cenas/demo", methods=["POST"])
def api_cena_demo():
    rotulo = (request.get_json(silent=True) or {}).get("nome", "AMBIENTE DEMO")
    arquivo, largura, altura = cena_demo.gerar(pasta_cenas(), rotulo.upper())
    tour = carregar_tour()
    cena = montar_cena(rotulo.title(), arquivo, largura, altura, "demo")
    tour["cenas"].append(cena)
    if not tour["cena_inicial"]:
        tour["cena_inicial"] = cena["id"]
    salvar_tour(tour)
    return jsonify({"ok": True, "cena": cena})


@api.route("/cenas/<cena_id>", methods=["PUT"])
def api_atualizar_cena(cena_id):
    tour = carregar_tour()
    cena = achar_cena(tour, cena_id)
    if not cena:
        return jsonify({"ok": False, "erro": "Cena nao encontrada."}), 404
    dados = request.get_json(force=True)
    for campo in ("nome", "hotspots", "vista_inicial", "haov", "vaov", "posicao"):
        if campo in dados:
            cena[campo] = dados[campo]
    salvar_tour(tour)
    return jsonify({"ok": True, "cena": cena})


@api.route("/planta", methods=["PUT"])
def api_salvar_planta():
    """
    Grava de uma vez a posicao de todos os pontos de captura, em metros.

    As posicoes ligam os panoramas num espaco comum: e o que permite ao visitante
    caminhar de um ponto ao outro em vez de saltar entre fotos soltas.
    """
    tour = carregar_tour()
    posicoes = request.get_json(force=True).get("posicoes", {})
    for cena in tour["cenas"]:
        if cena["id"] in posicoes:
            p = posicoes[cena["id"]]
            cena["posicao"] = {"x": round(float(p["x"]), 3),
                               "y": round(float(p["y"]), 3)}
    salvar_tour(tour)
    return jsonify({"ok": True, "cenas": tour["cenas"]})


@api.route("/cenas/<cena_id>", methods=["DELETE"])
def api_remover_cena(cena_id):
    tour = carregar_tour()
    cena = achar_cena(tour, cena_id)
    if not cena:
        return jsonify({"ok": False, "erro": "Cena nao encontrada."}), 404

    # o panorama e tambem o mapa de profundidade e a previa, senao ficam orfaos
    for chave in ("arquivo", "profundidade", "previa_profundidade"):
        nome = cena.get(chave)
        if not nome:
            continue
        caminho = os.path.join(pasta_cenas(), nome)
        if os.path.exists(caminho):
            os.remove(caminho)

    tour["cenas"] = [c for c in tour["cenas"] if c["id"] != cena_id]

    # limpa hotspots que apontavam para a cena removida
    for outra in tour["cenas"]:
        outra["hotspots"] = [h for h in outra.get("hotspots", [])
                             if h.get("destino") != cena_id]
    if tour["cena_inicial"] == cena_id:
        tour["cena_inicial"] = tour["cenas"][0]["id"] if tour["cenas"] else None
    salvar_tour(tour)
    return jsonify({"ok": True})


@api.route("/cenas/<cena_id>/profundidade", methods=["POST"])
def api_gerar_profundidade(cena_id):
    """Calcula o mapa de profundidade que permite andar dentro da cena."""
    tour = carregar_tour()
    cena = achar_cena(tour, cena_id)
    if not cena:
        return jsonify({"ok": False, "erro": "Cena nao encontrada."}), 404
    if not cena.get("panorama_completo"):
        return jsonify({"ok": False, "erro":
                        "Só dá para andar em cenas com 360 completo. Esta é parcial."}), 422

    try:
        disp, previa = profundidade.gerar(os.path.join(pasta_cenas(), cena["arquivo"]))
        nome = "prof_%s.png" % cena_id
        profundidade.salvar(disp, os.path.join(pasta_cenas(), nome))

        nome_previa = "prev_%s.jpg" % cena_id
        ok, buf = cv2.imencode(".jpg", previa, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            buf.tofile(os.path.join(pasta_cenas(), nome_previa))

        with trava_do_imovel(g.imovel):
            tour = carregar_tour()          # relê: pode ter mudado durante o calculo
            cena = achar_cena(tour, cena_id)
            if not cena:
                return jsonify({"ok": False, "erro": "Cena removida durante o cálculo."}), 404
            cena["profundidade"] = nome
            cena["previa_profundidade"] = nome_previa
            salvar_tour(tour)
        return jsonify({"ok": True, "cena": cena})
    except profundidade.ErroProfundidade as e:
        return jsonify({"ok": False, "erro": str(e)}), 422
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "erro": "Falha ao gerar profundidade: %s" % e}), 500


@api.route("/cenas/ordenar", methods=["POST"])
def api_ordenar():
    tour = carregar_tour()
    ordem = request.get_json(force=True).get("ordem", [])
    indice = {cid: i for i, cid in enumerate(ordem)}
    tour["cenas"].sort(key=lambda c: indice.get(c["id"], 999))
    salvar_tour(tour)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ leads

@api.route("/visita", methods=["POST"])
def api_registrar_visita():
    """
    Recebe o resumo de uma visita ao tour: quanto tempo durou e quanto tempo o
    visitante passou em cada ambiente.

    E o que responde "isso vende mais?" com numero em vez de opiniao, e diz ao
    corretor por onde comecar a conversa: se o cliente ficou 3 minutos na suite,
    e por ali.
    """
    dados = request.get_json(force=True) or {}
    tour = carregar_tour()
    visitas = tour.setdefault("visitas", [])

    visitas.append({
        "quando": datetime.now().isoformat(timespec="seconds"),
        "segundos": max(0, int(dados.get("segundos") or 0)),
        "ambientes": {str(k): int(v) for k, v in (dados.get("ambientes") or {}).items()},
        "andou": bool(dados.get("andou")),
        "celular": bool(dados.get("celular")),
        "virou_lead": False,
    })
    del visitas[:-500]          # o arquivo e JSON: guardar tudo cresceria sem limite
    salvar_tour(tour)
    return jsonify({"ok": True})


@api.route("/metricas", methods=["GET"])
def api_metricas():
    tour = carregar_tour()
    visitas = tour.get("visitas", [])
    nomes = {c["id"]: c["nome"] for c in tour["cenas"]}

    if not visitas:
        return jsonify({"ok": True, "visitas": 0, "resumo": None})

    duracoes = sorted(v["segundos"] for v in visitas)
    por_ambiente = {}
    for v in visitas:
        for cid, seg in v["ambientes"].items():
            d = por_ambiente.setdefault(cid, {"nome": nomes.get(cid, "(removido)"),
                                              "segundos": 0, "visitas": 0})
            d["segundos"] += seg
            d["visitas"] += 1

    ranking = sorted(por_ambiente.values(), key=lambda d: d["segundos"], reverse=True)
    for d in ranking:
        d["media"] = round(d["segundos"] / max(1, d["visitas"]))

    return jsonify({"ok": True, "visitas": len(visitas), "resumo": {
        "tempo_mediano": duracoes[len(duracoes) // 2],
        "tempo_medio": round(sum(duracoes) / len(duracoes)),
        "usaram_andar": sum(1 for v in visitas if v["andou"]),
        "no_celular": sum(1 for v in visitas if v["celular"]),
        "leads": len(tour.get("leads_capturados", [])),
        "conversao": round(len(tour.get("leads_capturados", [])) * 100.0 / len(visitas), 1),
        "ambientes": ranking[:12],
    }})


@api.route("/logo", methods=["POST"])
def api_enviar_logo():
    """Guarda a marca da imobiliaria, exibida no canto do tour."""
    arquivo = request.files.get("logo")
    if not arquivo:
        return jsonify({"ok": False, "erro": "Nenhum arquivo enviado."}), 400

    ext = os.path.splitext(arquivo.filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
        return jsonify({"ok": False,
                        "erro": "Use PNG, JPG, WEBP ou SVG."}), 422

    nome = "logo%s" % ext
    arquivo.save(os.path.join(pasta_cenas(), nome))
    tour = carregar_tour()
    tour["logo"] = nome
    salvar_tour(tour)
    return jsonify({"ok": True, "logo": nome})


@api.route("/logo", methods=["DELETE"])
def api_remover_logo():
    tour = carregar_tour()
    if tour.get("logo"):
        caminho = os.path.join(pasta_cenas(), tour["logo"])
        if os.path.exists(caminho):
            os.remove(caminho)
    tour["logo"] = ""
    salvar_tour(tour)
    return jsonify({"ok": True})


@api.route("/leads", methods=["POST"])
def api_registrar_lead():
    tour = carregar_tour()
    dados = request.get_json(force=True)
    visitas = tour.get("visitas", [])
    if visitas:
        visitas[-1]["virou_lead"] = True
    tour["leads_capturados"].append({
        "nome": dados.get("nome", ""),
        "telefone": dados.get("telefone", ""),
        "email": dados.get("email", ""),
        "quando": dados.get("quando", ""),
    })
    salvar_tour(tour)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ exportar

@api.route("/exportar", methods=["GET"])
def api_exportar():
    """Empacota o tour como site estatico, pronto para hospedar em qualquer lugar."""
    tour = carregar_tour()
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
        privados = ("leads_capturados", "visitas")
        publico = {k: v for k, v in tour.items() if k not in privados}
        z.writestr("tour.json", json.dumps(publico, ensure_ascii=False, indent=2))
        # O ZIP nao tem servidor: as paginas leem estes enderecos em vez de montar
        # os caminhos a partir do imovel. Injetar a configuracao e mais seguro do que
        # sair trocando pedacos de JavaScript por busca e substituicao.
        config = ("<script>window.__TOUR__='tour.json';"
                  "window.__CENAS__='scenes/';"
                  "window.__ANDAR__='andar.html';"
                  "window.__VOLTAR__='index.html';</script>")

        def para_estatico(html):
            html = html.replace("/static/vendor/", "vendor/")
            # logo apos <head>: o cabecalho das paginas le estas variaveis, entao a
            # configuracao precisa vir antes de qualquer script
            return html.replace("<head>", "<head>\n" + config, 1)

        for origem, destino in (("viewer.html", "index.html"),
                                ("andar.html", "andar.html")):
            with open(os.path.join(RAIZ, "static", origem), "r", encoding="utf-8") as f:
                z.writestr(destino, para_estatico(f.read()))

        pasta_vendor = os.path.join(RAIZ, "static", "vendor")
        for nome in os.listdir(pasta_vendor):
            z.write(os.path.join(pasta_vendor, nome), "vendor/%s" % nome)

        if tour.get("logo"):
            caminho = os.path.join(pasta_cenas(), tour["logo"])
            if os.path.exists(caminho):
                z.write(caminho, "scenes/%s" % tour["logo"])

        for cena in tour["cenas"]:
            # o panorama e, quando existir, o mapa de profundidade que permite andar
            for chave in ("arquivo", "profundidade"):
                nome = cena.get(chave)
                if not nome:
                    continue
                caminho = os.path.join(pasta_cenas(), nome)
                if os.path.exists(caminho):
                    z.write(caminho, "scenes/%s" % nome)
    memoria.seek(0)
    limpo = "".join(ch if ch.isalnum() or ch in " -_" else "" for ch in tour["titulo"])
    nome_zip = (limpo.strip().replace(" ", "-").lower() or "tour") + ".zip"
    return send_file(memoria, mimetype="application/zip", as_attachment=True,
                     download_name=nome_zip)


@api.route("/embed")
def api_embed():
    base = request.host_url.rstrip("/")
    codigo = ('<iframe src="' + base + '/tour/' + g.imovel + '" width="100%" '
              'height="520" frameborder="0" allowfullscreen '
              'allow="vr; gyroscope; accelerometer"></iframe>')
    return Response(codigo, mimetype="text/plain")


app.register_blueprint(api)


if __name__ == "__main__":
    migrar_formato_antigo()
    if not listar_imoveis():
        criar_imovel("Meu primeiro imóvel")
        print("  nenhum imovel encontrado: criei um vazio para comecar")
    print("")
    print("  Tour Virtual rodando")
    print("  Imoveis: http://127.0.0.1:5000/imoveis")
    print("")
    # 127.0.0.1 de proposito, e nao localhost: no Windows o nome resolve para
    # IPv6 (::1) primeiro, o servidor so escuta IPv4, e cada requisicao espera
    # o timeout antes de tentar o IPv4 — medi 2 segundos por chamada.
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
