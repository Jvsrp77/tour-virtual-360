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
import traceback
from flask import (Flask, request, jsonify, send_from_directory,
                   send_file, redirect, Response)

import cv2

import stitcher
import cena_demo
import profundidade

RAIZ = os.path.dirname(os.path.abspath(__file__))
PASTA_DADOS = os.path.join(RAIZ, "data")
PASTA_UPLOADS = os.path.join(PASTA_DADOS, "uploads")
PASTA_CENAS = os.path.join(PASTA_DADOS, "scenes")
ARQ_TOUR = os.path.join(PASTA_DADOS, "tour.json")

for p in (PASTA_DADOS, PASTA_UPLOADS, PASTA_CENAS):
    os.makedirs(p, exist_ok=True)

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024   # 300 MB por requisicao

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
}


# ------------------------------------------------------------------ dados

def carregar_tour():
    if not os.path.exists(ARQ_TOUR):
        return json.loads(json.dumps(TOUR_PADRAO))
    with open(ARQ_TOUR, "r", encoding="utf-8") as f:
        tour = json.load(f)
    for chave, valor in TOUR_PADRAO.items():          # completa campos novos
        tour.setdefault(chave, valor)
    return tour


def salvar_tour(tour):
    with open(ARQ_TOUR, "w", encoding="utf-8") as f:
        json.dump(tour, f, ensure_ascii=False, indent=2)


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
    return redirect("/painel")


@app.route("/painel")
def painel():
    return send_from_directory("static", "admin.html")


@app.route("/tour")
def visualizador():
    return send_from_directory("static", "viewer.html")


@app.route("/data/scenes/<path:nome>")
def arquivo_cena(nome):
    return send_from_directory(PASTA_CENAS, nome)


@app.route("/data/uploads/<path:nome>")
def arquivo_upload(nome):
    return send_from_directory(PASTA_UPLOADS, nome)


# ------------------------------------------------------------------ api tour

@app.route("/api/tour", methods=["GET"])
def api_obter_tour():
    return jsonify(carregar_tour())


@app.route("/api/tour", methods=["PUT"])
def api_salvar_tour():
    tour = carregar_tour()
    dados = request.get_json(force=True)
    for campo in ("titulo", "descricao", "endereco", "preco", "cor",
                  "cena_inicial", "lead", "logo"):
        if campo in dados:
            tour[campo] = dados[campo]
    salvar_tour(tour)
    return jsonify({"ok": True, "tour": tour})


@app.route("/api/tour/reiniciar", methods=["POST"])
def api_reiniciar():
    for pasta in (PASTA_CENAS, PASTA_UPLOADS):
        shutil.rmtree(pasta, ignore_errors=True)
        os.makedirs(pasta, exist_ok=True)
    if os.path.exists(ARQ_TOUR):
        os.remove(ARQ_TOUR)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ api cenas

@app.route("/api/cenas/costurar", methods=["POST"])
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

        arquivo, largura, altura, info = stitcher.costurar(temporarios, PASTA_CENAS)

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


@app.route("/api/cenas/importar360", methods=["POST"])
def api_importar_360():
    """Recebe uma foto 360 ja pronta (camera 360 ou app de celular)."""
    arquivos = request.files.getlist("fotos")
    nome_base = (request.form.get("nome") or "").strip()
    if not arquivos:
        return jsonify({"ok": False, "erro": "Nenhum arquivo enviado."}), 400

    tour = carregar_tour()
    criadas, avisos = [], []
    try:
        for f in arquivos:
            ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
            temp = os.path.join(PASTA_UPLOADS, "%s%s" % (uuid.uuid4().hex[:10], ext))
            f.save(temp)
            arquivo, largura, altura = stitcher.importar_equirretangular(temp, PASTA_CENAS)

            rotulo = nome_base or os.path.splitext(f.filename)[0][:40] or "Ambiente"
            cena = montar_cena(rotulo, arquivo, largura, altura, "equirretangular")
            if not cena["panorama_completo"]:
                avisos.append(
                    "A foto %s nao esta na proporcao 2:1 (esta %dx%d). Vai abrir como "
                    "foto parcial, sem giro completo." % (rotulo, largura, altura))
            tour["cenas"].append(cena)
            criadas.append(cena)

        if criadas and not tour["cena_inicial"]:
            tour["cena_inicial"] = criadas[0]["id"]
        salvar_tour(tour)
        return jsonify({"ok": True, "cenas": criadas, "avisos": avisos})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/cenas/demo", methods=["POST"])
def api_cena_demo():
    rotulo = (request.get_json(silent=True) or {}).get("nome", "AMBIENTE DEMO")
    arquivo, largura, altura = cena_demo.gerar(PASTA_CENAS, rotulo.upper())
    tour = carregar_tour()
    cena = montar_cena(rotulo.title(), arquivo, largura, altura, "demo")
    tour["cenas"].append(cena)
    if not tour["cena_inicial"]:
        tour["cena_inicial"] = cena["id"]
    salvar_tour(tour)
    return jsonify({"ok": True, "cena": cena})


@app.route("/api/cenas/<cena_id>", methods=["PUT"])
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


@app.route("/api/planta", methods=["PUT"])
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


@app.route("/api/cenas/<cena_id>", methods=["DELETE"])
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
        caminho = os.path.join(PASTA_CENAS, nome)
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


@app.route("/api/cenas/<cena_id>/profundidade", methods=["POST"])
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
        disp, previa = profundidade.gerar(os.path.join(PASTA_CENAS, cena["arquivo"]))
        nome = "prof_%s.png" % cena_id
        profundidade.salvar(disp, os.path.join(PASTA_CENAS, nome))

        nome_previa = "prev_%s.jpg" % cena_id
        ok, buf = cv2.imencode(".jpg", previa, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            buf.tofile(os.path.join(PASTA_CENAS, nome_previa))

        cena["profundidade"] = nome
        cena["previa_profundidade"] = nome_previa
        salvar_tour(tour)
        return jsonify({"ok": True, "cena": cena})
    except profundidade.ErroProfundidade as e:
        return jsonify({"ok": False, "erro": str(e)}), 422
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "erro": "Falha ao gerar profundidade: %s" % e}), 500


@app.route("/andar")
def andar():
    return send_from_directory("static", "andar.html")


@app.route("/api/cenas/ordenar", methods=["POST"])
def api_ordenar():
    tour = carregar_tour()
    ordem = request.get_json(force=True).get("ordem", [])
    indice = {cid: i for i, cid in enumerate(ordem)}
    tour["cenas"].sort(key=lambda c: indice.get(c["id"], 999))
    salvar_tour(tour)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ leads

@app.route("/api/leads", methods=["POST"])
def api_registrar_lead():
    tour = carregar_tour()
    dados = request.get_json(force=True)
    tour["leads_capturados"].append({
        "nome": dados.get("nome", ""),
        "telefone": dados.get("telefone", ""),
        "email": dados.get("email", ""),
        "quando": dados.get("quando", ""),
    })
    salvar_tour(tour)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ exportar

@app.route("/api/exportar", methods=["GET"])
def api_exportar():
    """Empacota o tour como site estatico, pronto para hospedar em qualquer lugar."""
    tour = carregar_tour()
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
        publico = {k: v for k, v in tour.items() if k != "leads_capturados"}
        z.writestr("tour.json", json.dumps(publico, ensure_ascii=False, indent=2))
        def para_estatico(html):
            return (html.replace("/api/tour", "tour.json")
                        .replace("/data/scenes/", "scenes/")
                        .replace("/static/vendor/", "vendor/")
                        .replace("'/andar?cena='", "'andar.html?cena='")
                        .replace('href="/tour"', 'href="index.html"'))

        for origem, destino in (("viewer.html", "index.html"),
                                ("andar.html", "andar.html")):
            with open(os.path.join(RAIZ, "static", origem), "r", encoding="utf-8") as f:
                z.writestr(destino, para_estatico(f.read()))

        pasta_vendor = os.path.join(RAIZ, "static", "vendor")
        for nome in os.listdir(pasta_vendor):
            z.write(os.path.join(pasta_vendor, nome), "vendor/%s" % nome)

        for cena in tour["cenas"]:
            # o panorama e, quando existir, o mapa de profundidade que permite andar
            for chave in ("arquivo", "profundidade"):
                nome = cena.get(chave)
                if not nome:
                    continue
                caminho = os.path.join(PASTA_CENAS, nome)
                if os.path.exists(caminho):
                    z.write(caminho, "scenes/%s" % nome)
    memoria.seek(0)
    return send_file(memoria, mimetype="application/zip", as_attachment=True,
                     download_name="tour-virtual.zip")


@app.route("/embed")
def api_embed():
    base = request.host_url.rstrip("/")
    codigo = ('<iframe src="' + base + '/tour" width="100%" height="520" '
              'frameborder="0" allowfullscreen '
              'allow="vr; gyroscope; accelerometer"></iframe>')
    return Response(codigo, mimetype="text/plain")


if __name__ == "__main__":
    print("")
    print("  Tour Virtual rodando")
    print("  Painel:        http://localhost:5000/painel")
    print("  Visualizador:  http://localhost:5000/tour")
    print("")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
