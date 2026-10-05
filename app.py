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
import time
import threading
import re
import traceback
from datetime import datetime
from urllib.parse import quote

from datetime import timedelta

from flask import (Flask, Blueprint, g, request, jsonify, send_from_directory,
                   send_file, redirect, Response, abort, session)
from markupsafe import escape

import cv2
import numpy as np

import stitcher
import video
import cena_demo
import profundidade
import tarefas
import aviso
import maquete3d
import modelo3d
import vizinhanca
import captura
import area
import fundo
import usuarios
import marca

RAIZ = os.path.dirname(os.path.abspath(__file__))
# TOUR_DADOS existe para os testes rodarem numa pasta descartavel: sem isso o
# unico jeito de testar a matriz de acesso seria contra os dados de producao.
PASTA_DADOS = os.environ.get("TOUR_DADOS") or os.path.join(RAIZ, "data")
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


def arq_maquete(imovel_id):
    """
    A geometria do imovel, quando existe.

    So imovel SINTETICO tem: dele conhecemos as paredes e os moveis em metros,
    porque foi assim que ele nasceu. Imovel fotografado nao tem geometria — tem
    panorama e profundidade, que e outra coisa. Por isso o arquivo e opcional, e
    a maquete so aparece onde ele existe.
    """
    return os.path.join(pasta_imovel(imovel_id), "maquete.json")


def arq_modelo(imovel_id, ext=".obj"):
    """O modelo 3D importado de um escaneamento, quando existe."""
    return os.path.join(pasta_imovel(imovel_id), "modelo" + ext)


def arq_textura(imovel_id, nome):
    """
    A imagem que o escaneamento cola na malha.

    Guardada com o nome que o .mtl pede, porque e assim que a pagina vai
    procura-la — mas so depois de passar pela limpeza do modelo3d.
    """
    limpo = modelo3d.nome_de_textura_seguro(nome)
    if not limpo:
        return None
    return os.path.join(pasta_imovel(imovel_id), "modelotex_" + limpo)


def texturas_do_modelo(imovel_id):
    """Os nomes de textura que ja estao no disco para este imovel."""
    pasta = pasta_imovel(imovel_id)
    if not os.path.isdir(pasta):
        return []
    return sorted(n[len("modelotex_"):] for n in os.listdir(pasta)
                  if n.startswith("modelotex_"))


def tem_modelo(imovel_id):
    return os.path.exists(arq_modelo(imovel_id))


def tem_maquete(imovel_id):
    return os.path.exists(arq_maquete(imovel_id)) or tem_modelo(imovel_id)


def pasta_cenas(imovel_id=None):
    caminho = os.path.join(pasta_imovel(imovel_id or g.imovel), "scenes")
    os.makedirs(caminho, exist_ok=True)
    return caminho


def imovel_existe(imovel_id):
    return bool(imovel_id) and os.path.exists(arq_tour(imovel_id))


def listar_imoveis(conta_id=None):
    itens = []
    for iid in sorted(os.listdir(PASTA_IMOVEIS)):
        if not imovel_existe(iid):
            continue
        tour = carregar_tour(iid)
        dono = tour.get("conta") or ""
        if conta_id is not None and dono and dono != conta_id:
            continue
        capa = next((c.get("miniatura") or c["arquivo"] for c in tour["cenas"]), None)
        itens.append({
            "id": iid,
            "titulo": tour.get("titulo") or "Imóvel sem título",
            "endereco": tour.get("endereco", ""),
            "preco": tour.get("preco", ""),
            "ambientes": len(tour["cenas"]),
            "com_profundidade": sum(1 for c in tour["cenas"] if c.get("profundidade")),
            "area_total": round(sum(c["area"]["m2"] for c in tour["cenas"]
                                    if c.get("area")), 1),
            "ambientes_medidos": sum(1 for c in tour["cenas"] if c.get("area")),
            "leads": len(tour.get("leads_capturados", [])),
            # O diagnostico de captura na LISTA, e nao so dentro do imovel: numa
            # imobiliaria com quarenta anuncios, saber que um deles nao anda so
            # ao abri-lo significa nunca saber. O tour ja esta carregado aqui,
            # entao a conta sai de graca.
            "captura": _saude_da_captura(tour),
            "capa": capa,
            "criado_em": tour.get("criado_em", ""),
        })
    itens.sort(key=lambda i: i["criado_em"], reverse=True)
    return itens


def _saude_da_captura(tour):
    """
    Quantos problemas de captura este imovel tem.

    Sai do mesmo diagnostico do guia, para que a lista e o guia nunca digam
    coisas diferentes sobre o mesmo imovel. Falhar aqui nao pode derrubar a
    lista inteira: um imovel com dado estranho nao vale esconder os outros
    trinta e nove.
    """
    try:
        resumo, _achados = captura.diagnosticar(tour)
        return {"impedem": resumo["impedem"], "atrapalham": resumo["atrapalham"]}
    except Exception:
        return {"impedem": 0, "atrapalham": 0}


def adotar_imoveis_sem_dono():
    """
    Da os imoveis orfaos a primeira conta.

    O acervo criado antes das contas existirem nao tem dono. Sem isso ele ficaria
    visivel a qualquer conta nova — inclusive a de outra imobiliaria.
    """
    contas = usuarios.listar(PASTA_DADOS)
    if not contas:
        return 0
    dono = contas[0]["id"]
    adotados = 0
    for iid in os.listdir(PASTA_IMOVEIS):
        if not imovel_existe(iid):
            continue
        tour = carregar_tour(iid)
        if not tour.get("conta"):
            tour["conta"] = dono
            salvar_tour(tour, iid)
            adotados += 1
    if adotados:
        print("  %d imovel(is) sem dono adotado(s) pela primeira conta" % adotados)
    return adotados


def criar_imovel(titulo, conta_id=""):
    iid = uuid.uuid4().hex[:10]
    os.makedirs(os.path.join(pasta_imovel(iid), "scenes"), exist_ok=True)
    tour = json.loads(json.dumps(TOUR_PADRAO))
    tour["conta"] = conta_id
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
app.secret_key = usuarios.segredo(PASTA_DADOS)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=timedelta(days=30))

# Atras de um proxy que termina o TLS, o Flask so enxerga http e o IP do proxy.
# Sem o ProxyFix o cookie de sessao nunca seria marcado como seguro e o log
# registraria sempre o mesmo endereco.
ATRAS_DE_PROXY = os.environ.get("TOUR_ATRAS_DE_PROXY") == "1"
if ATRAS_DE_PROXY:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.update(SESSION_COOKIE_SECURE=True)


# ------------------------------------------------------------ HTTPS de verdade
#
# Marcar o cookie como seguro nao basta: se alguem abrir o link em http, a senha
# do corretor viaja legivel antes de qualquer cookie existir. O waitress nao faz
# TLS — quem termina o TLS e o Caddy (ver Caddyfile) — entao o que cabe aqui e
# nao ACEITAR o http: desviar para https e pedir ao navegador que nunca mais
# tente em claro.
#
# Fica desligado por padrao de proposito. Ligado sem HTTPS de verdade na frente,
# ele desviaria para um endereco que nao responde e tiraria o site do ar.
EXIGIR_HTTPS = os.environ.get("TOUR_EXIGIR_HTTPS") == "1"
HSTS_SEGUNDOS = 60 * 60 * 24 * 180


@app.before_request
def _exigir_https():
    if not EXIGIR_HTTPS or request.is_secure:
        return None
    # /saude e como o vigia sabe que o site esta vivo, e ele chama em 127.0.0.1
    # sem TLS. Desviar isto poria o servidor em ciclo de reinicio.
    if request.endpoint == "saude" or request.remote_addr in ("127.0.0.1", "::1"):
        return None
    if request.method not in ("GET", "HEAD"):
        return jsonify({"ok": False, "erro":
                        "Esta conexão não é segura. Use o endereço https."}), 403
    return redirect(request.url.replace("http://", "https://", 1), code=308)


@app.after_request
def _fixar_https(resposta):
    if EXIGIR_HTTPS and request.is_secure:
        resposta.headers["Strict-Transport-Security"] = (
            "max-age=%d; includeSubDomains" % HSTS_SEGUNDOS)
    return resposta

# O tour publicado e o produto: ele fica aberto, e com ele o modo de caminhada,
# as imagens das cenas e o registro de visita e de lead. Todo o resto — painel,
# lista, metricas, exportacao e qualquer escrita — exige sessao.
#
# Rotas registradas no app NAO levam prefixo no nome do endpoint; so as do
# Blueprint levam. Escrever "app.visualizador" aqui ja mandou o tour do cliente
# para a tela de login uma vez.
ROTAS_PUBLICAS = {
    "visualizador", "andar", "arquivo_cena", "pagina_entrar", "saude",
    "static", "api_entrar", "api_estado_conta",
    "api.api_obter_tour", "api.api_registrar_lead", "api.api_registrar_visita",
    "api.api_embed", "maquete", "api.api_maquete",
    "api.api_baixar_modelo", "api.api_baixar_modelo_mtl",
    "api.api_textura_do_modelo",
}

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

ROTAS_PESADAS = {"api.api_costurar", "api.api_costurar_video",
                 "api.api_importar_varredura",
                 "api.api_importar_360", "api.api_gerar_profundidade",
                 "api.api_corrigir_cena", "api.api_fundo"}


def trava_do_imovel(imovel_id):
    with _TRAVA_MESTRA:
        return _TRAVAS.setdefault(imovel_id, threading.RLock())


@api.before_request
def _exigir_imovel():
    if not imovel_existe(g.imovel):
        return jsonify({"ok": False, "erro": "Imóvel não encontrado."}), 404
    # Rota publica do tour nao exige conta; toda outra exige, e exige ser dona.
    # "Nao encontrado" em vez de "sem permissao": quem nao e dono nao precisa
    # descobrir que o imovel existe.
    if request.endpoint not in ROTAS_PUBLICAS and not pode_ver(g.imovel):
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
    """
    Le o tour, sob a trava do imovel.

    A trava aqui nao e pela leitura em si — `os.replace` ja garante que ninguem
    ve JSON pela metade. E pelo Windows: la o `MoveFileEx` RECUSA a troca
    enquanto o destino tiver um handle aberto, e a gravacao falha com WinError 5.
    Com visitantes lendo sem parar, isso derrubava 38 de 40 gravacoes.

    Custa pouco: ler e questao de microssegundos, e as rotas pesadas (costura,
    profundidade) nao seguram a trava — so a pegam no instante de gravar.
    """
    alvo = imovel_id or g.imovel
    caminho = arq_tour(alvo)
    if not os.path.exists(caminho):
        return json.loads(json.dumps(TOUR_PADRAO))
    with trava_do_imovel(alvo):
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
    alvo = imovel_id or g.imovel
    caminho = arq_tour(alvo)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    temporario = caminho + ".tmp"
    with trava_do_imovel(alvo):
        with open(temporario, "w", encoding="utf-8") as f:
            json.dump(tour, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        _trocar(temporario, caminho)


def _trocar(temporario, definitivo, tentativas=12, espera=0.02):
    """
    os.replace, com paciência — no Windows ele falha se o destino estiver aberto.

    Quem resolve a corrida interna é a trava em `carregar_tour`/`salvar_tour`:
    com ela, nenhuma thread nossa tem o arquivo aberto na hora da troca. Medido:
    o teste de concorrência passa sem este retry.

    Ele fica para os handles que NÃO são nossos e que a trava não alcança —
    antivírus varrendo o arquivo recém-escrito, indexador do Windows, ferramenta
    de backup. Nenhum teste aqui consegue produzir isso, então é precaução
    declarada, não conserto medido. No Linux o rename é atômico mesmo com
    leitores e este caminho nunca é exercido.
    """
    for tentativa in range(tentativas):
        try:
            os.replace(temporario, definitivo)
            return
        except PermissionError:
            if tentativa == tentativas - 1:
                raise
            time.sleep(espera * (tentativa + 1))


def achar_cena(tour, cena_id):
    return next((c for c in tour["cenas"] if c["id"] == cena_id), None)


LARGURA_MINIATURA = 480


def gerar_miniatura(imovel_id, arquivo):
    """
    Versao pequena do panorama para as listas.

    Sem isso, uma miniatura de 109x60 na tela baixa o panorama inteiro: o menu de
    um tour de 13 ambientes puxava 17 MB antes do visitante clicar em nada.
    """
    origem = os.path.join(pasta_cenas(imovel_id), arquivo)
    if not os.path.exists(origem):
        return ""
    nome = "mini_" + os.path.splitext(arquivo)[0] + ".jpg"
    destino = os.path.join(pasta_cenas(imovel_id), nome)
    try:
        img = cv2.imdecode(np.fromfile(origem, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return ""
        escala = LARGURA_MINIATURA / float(img.shape[1])
        if escala < 1:
            img = cv2.resize(img, (LARGURA_MINIATURA, max(1, int(img.shape[0] * escala))),
                             interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 78])
        if not ok:
            return ""
        buf.tofile(destino)
        return nome
    except Exception:
        traceback.print_exc()
        return ""


LADO_ESBOCO = (960, 540)


def gerar_esboco(imovel_id, cena):
    """
    Poster da vista inicial: a primeira coisa que o visitante enxerga.

    O panorama tem 1,3 MB e leva quase 7 s em 4G fraco — tempo que o visitante
    passa olhando "Carregando o tour...". O esboco tem uns 30 KB, chega em 0,2 s
    e ja mostra o comodo no enquadramento exato em que o panorama vai abrir.

    Tem de ser um recorte em perspectiva, nao o equirretangular reduzido: o
    Pannellum desenha o preview como imagem de fundo chapada (background-size:
    cover), entao um equirretangular apareceria esmagado.
    """
    origem = os.path.join(pasta_cenas(imovel_id), cena.get("arquivo", ""))
    if not cena.get("arquivo") or not os.path.exists(origem):
        return ""
    try:
        img = cv2.imdecode(np.fromfile(origem, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return ""
        H, W = img.shape[:2]
        vista = cena.get("vista_inicial") or {}
        larg, alt = LADO_ESBOCO
        hfov = max(30.0, min(120.0, float(vista.get("hfov") or 100)))
        f = (larg / 2.0) / np.tan(np.radians(hfov) / 2.0)

        eixo_x = np.arange(larg, dtype=np.float32) - larg / 2.0
        eixo_y = np.arange(alt, dtype=np.float32) - alt / 2.0
        ux, uy = np.meshgrid(eixo_x, eixo_y)
        d = np.stack([ux, uy, np.full_like(ux, f)], -1)
        d /= np.linalg.norm(d, axis=-1, keepdims=True)

        # pitch positivo olha para cima; +y da imagem aponta para baixo
        p = np.radians(float(vista.get("pitch") or 0))
        y = np.radians(float(vista.get("yaw") or 0))
        Rx = np.array([[1, 0, 0],
                       [0, np.cos(p), -np.sin(p)],
                       [0, np.sin(p), np.cos(p)]])
        Ry = np.array([[np.cos(y), 0, np.sin(y)],
                       [0, 1, 0],
                       [-np.sin(y), 0, np.cos(y)]])
        d = d @ (Ry @ Rx).T

        lon = np.degrees(np.arctan2(d[..., 0], d[..., 2]))
        lat = np.degrees(np.arcsin(np.clip(d[..., 1], -1, 1)))
        # cena parcial ocupa so haov x vaov da esfera, centrada em (0, 0)
        haov = float(cena.get("haov") or 360.0) or 360.0
        vaov = float(cena.get("vaov") or 180.0) or 180.0
        mx = ((lon / haov) + 0.5) * W
        my = ((lat / vaov) + 0.5) * H
        borda = cv2.BORDER_WRAP if haov >= 359.0 else cv2.BORDER_REPLICATE
        recorte = cv2.remap(img, mx.astype(np.float32), my.astype(np.float32),
                            cv2.INTER_AREA, borderMode=borda)

        nome = "esboco_%s.jpg" % cena["id"]
        ok, buf = cv2.imencode(".jpg", recorte, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            return ""
        buf.tofile(os.path.join(pasta_cenas(imovel_id), nome))
        return nome
    except Exception:
        traceback.print_exc()
        return ""


def completar_esbocos():
    """Cria o poster de abertura das cenas que ainda nao tem."""
    feitos = 0
    for iid in os.listdir(PASTA_IMOVEIS):
        if not imovel_existe(iid):
            continue
        tour = carregar_tour(iid)
        mudou = False
        for cena in tour["cenas"]:
            if cena.get("esboco") and os.path.exists(
                    os.path.join(pasta_cenas(iid), cena["esboco"])):
                continue
            nome = gerar_esboco(iid, cena)
            if nome:
                cena["esboco"] = nome
                mudou = True
                feitos += 1
        if mudou:
            salvar_tour(tour, iid)
    if feitos:
        print("  %d esboco(s) de abertura gerado(s)" % feitos)


def completar_miniaturas():
    """Cria as miniaturas que faltam nos imoveis ja existentes."""
    feitas = 0
    for iid in os.listdir(PASTA_IMOVEIS):
        if not imovel_existe(iid):
            continue
        tour = carregar_tour(iid)
        mudou = False
        for cena in tour["cenas"]:
            if cena.get("miniatura"):
                caminho = os.path.join(pasta_cenas(iid), cena["miniatura"])
                if os.path.exists(caminho):
                    continue
            nome = gerar_miniatura(iid, cena["arquivo"])
            if nome:
                cena["miniatura"] = nome
                mudou = True
                feitas += 1
        if mudou:
            salvar_tour(tour, iid)
    if feitas:
        print("  %d miniatura(s) gerada(s)" % feitas)


DIAS_GUARDA_UPLOADS = 7


def limpar_cenas_orfas():
    """
    Apaga arquivos em scenes/ que nenhuma cena referencia.

    Costura recusada no meio, cena substituida, profundidade de uma cena ja
    removida: cada caso deixa arquivo para tras. Foram encontrados 2,5 MB assim
    num imovel com um unico ambiente.
    """
    liberado = 0
    for iid in os.listdir(PASTA_IMOVEIS):
        if not imovel_existe(iid):
            continue
        tour = carregar_tour(iid)
        usados = set()
        if tour.get("logo"):
            usados.add(tour["logo"])
        for cena in tour["cenas"]:
            for chave in ("arquivo", "profundidade", "previa_profundidade",
                          "miniatura", "esboco"):
                if cena.get(chave):
                    usados.add(cena[chave])
            for chave in ("textura", "profundidade"):
                if (cena.get("fundo") or {}).get(chave):
                    usados.add(cena["fundo"][chave])
            if cena.get("arquivo"):
                usados.add("orig_" + cena["arquivo"])   # pristino da marca no chao

        pasta = os.path.join(pasta_imovel(iid), "scenes")
        if not os.path.isdir(pasta):
            continue
        for nome in os.listdir(pasta):
            if nome in usados:
                continue
            caminho = os.path.join(pasta, nome)
            if os.path.isfile(caminho):
                liberado += os.path.getsize(caminho)
                os.remove(caminho)
    if liberado:
        print("  faxina: %.1f MB de arquivos de cena orfaos apagados" % (liberado / 1e6))


def limpar_uploads_orfaos():
    """
    Apaga lotes de fotos originais que nao pertencem a nenhuma cena.

    As originais valem a pena guardar por um tempo — ja precisei delas para
    recosturar com ajustes melhores. Mas sem limpeza a pasta so cresce: estavam
    226 MB de lotes de costuras que falharam ou foram apagadas.
    """
    usados = set()
    for iid in os.listdir(PASTA_IMOVEIS):
        if not imovel_existe(iid):
            continue
        for cena in carregar_tour(iid)["cenas"]:
            if cena.get("lote"):
                usados.add(cena["lote"])

    limite = time.time() - DIAS_GUARDA_UPLOADS * 86400
    liberado = 0
    for nome in os.listdir(PASTA_UPLOADS):
        caminho = os.path.join(PASTA_UPLOADS, nome)
        if nome in usados or not os.path.isdir(caminho):
            continue
        if os.path.getmtime(caminho) > limite:
            continue                       # recente: pode ser de uma costura em curso
        tamanho = sum(os.path.getsize(os.path.join(r, f))
                      for r, _, fs in os.walk(caminho) for f in fs)
        shutil.rmtree(caminho, ignore_errors=True)
        liberado += tamanho
    if liberado:
        print("  faxina: %.0f MB de fotos originais orfas apagados" % (liberado / 1e6))


def formato_recusado(caminho, nome_original=""):
    """
    Devolve um recado se o arquivo nao for imagem que o OpenCV abre, ou None.

    O caso que motivou isto: o iPhone grava em HEIC POR PADRAO. A rota trocava a
    extensao para .jpg e seguia, e o conteudo continuava HEIC — a costura morria
    la na frente com "Não consegui abrir o arquivo: foto_00.jpg", que culpa o
    arquivo sem dizer o que fazer. Corretor de iPhone batia nisso no primeiro uso.

    A conferencia e pelos bytes, nao pela extensao: quem renomeia .heic para .jpg
    continua enviando HEIC, e e justamente quem mais precisa do recado certo.
    """
    try:
        with open(caminho, "rb") as f:
            cabeca = f.read(16)
    except OSError:
        return None

    rotulo = os.path.basename(nome_original or caminho)
    # ISO-BMFF: "ftyp" no byte 4, e a marca do formato logo depois
    if len(cabeca) >= 12 and cabeca[4:8] == b"ftyp":
        marca = cabeca[8:12]
        if marca in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
            return ("O arquivo %s está em HEIC, o formato que o iPhone usa por "
                    "padrão, e o sistema ainda não abre esse formato. No iPhone: "
                    "Ajustes › Câmera › Formatos › Mais Compatível. As fotos "
                    "passam a sair em JPEG e basta tirar de novo. Para as que já "
                    "existem, abra a foto e use Compartilhar › Opções › Formato "
                    "JPEG." % rotulo)
        if marca in (b"qt  ", b"isom", b"mp42", b"M4V "):
            return ("O arquivo %s é um vídeo, não uma foto. Se quer montar o "
                    "ambiente a partir de vídeo, use o campo de vídeo em vez do "
                    "de fotos." % rotulo)
    return None


def montar_cena(nome, arquivo, largura, altura, origem, info=None,
                imovel_id=None):
    """
    info vem da costura e traz a cobertura medida a partir da orientacao das fotos.
    Sem ele (foto 360 importada ou cena demo) a cobertura e deduzida da proporcao.
    """
    if info:
        haov, vaov = info["haov"], info["vaov"]
        completa = bool(info["fechada"])
    else:
        completa = stitcher.eh_equirretangular(largura, altura)
        if completa:
            haov, vaov = 360.0, 180.0
        else:
            # nao e 2:1: estimar a cobertura em vez de espalhar pela volta inteira
            haov, vaov = stitcher.cobertura_parcial(largura, altura)

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
        "miniatura": gerar_miniatura(imovel_id or g.imovel, arquivo),
    }
    cena["esboco"] = gerar_esboco(imovel_id or g.imovel, cena)
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


def conta_atual():
    """Conta logada, ou None. `id` e o que fica gravado no imovel."""
    nome = session.get("usuario")
    return usuarios.obter(PASTA_DADOS, nome) if nome else None


@app.before_request
def _exigir_sessao():
    if request.endpoint in ROTAS_PUBLICAS or request.endpoint is None:
        return
    if conta_atual():
        return
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "erro": "Faça login para continuar.",
                        "login": True}), 401
    # Leva junto para onde a pessoa ia. Sem isto, abrir o link do painel sem
    # sessao jogava para a lista de imoveis e parecia que "o login nao pegou".
    return redirect("/entrar" + _proximo_para(request.path))


@app.after_request
def _nao_guardar_api(resposta):
    """
    Resposta de API nunca pode ficar em cache do navegador.

    Sem nenhum cabecalho de cache, o navegador decide sozinho — e decide guardar.
    O sintoma: o corretor cadastra um imovel, a lista continua mostrando os
    antigos, e parece que o cadastro se perdeu. Aconteceu de verdade: tres
    imoveis no servidor, um so na tela.

    As imagens das cenas continuam como estao (revalidadas por ETag): sao
    arquivos grandes que quase nunca mudam, e guardar vale a pena. O que nao
    pode envelhecer e a LISTA do que existe.
    """
    if request.path.startswith("/api/"):
        resposta.headers["Cache-Control"] = "no-store, must-revalidate"
        resposta.headers["Pragma"] = "no-cache"
    return resposta


def _proximo_para(caminho):
    """
    Monta ?proximo=<caminho> so para destino LOCAL.

    Caminho vindo de fora nao entra aqui sem conferencia: aceitar "//sitedele"
    ou "http://..." transformaria a tela de login numa ponte para site alheio,
    com o endereco do proprio corretor na barra.
    """
    if (not caminho or not caminho.startswith("/") or caminho.startswith("//")
            or "\\" in caminho or caminho in ("/entrar", "/")):
        return ""
    return "?proximo=" + quote(caminho, safe="/")


def dono_do_imovel(imovel_id):
    return (carregar_tour(imovel_id) or {}).get("conta") or ""


def pode_ver(imovel_id):
    """
    Cada conta enxerga apenas os proprios imoveis.

    Imovel sem dono e de quem chegou primeiro: e o acervo criado antes das contas
    existirem, adotado na migracao. Depois disso todo imovel nasce com dono.
    """
    conta = conta_atual()
    if not conta:
        return False
    dono = dono_do_imovel(imovel_id)
    return (not dono) or dono == conta["id"]


@app.route("/saude")
def saude():
    """Usada pelo container e pelo proxy para saber se o processo esta de pe."""
    return jsonify({"ok": True, "imoveis": len(os.listdir(PASTA_IMOVEIS))
                    if os.path.isdir(PASTA_IMOVEIS) else 0,
                    "modelos": {"profundidade": profundidade.modelo_disponivel(),
                                "fundo": fundo.modelo_disponivel()},
                    # para quem cuida do servidor ver de fora que o aviso de
                    # contato esta desligado, sem precisar perder um lead antes
                    "aviso_de_lead": aviso.configurado()})


@app.route("/entrar")
def pagina_entrar():
    return send_from_directory("static", "entrar.html")


@app.route("/imoveis")
def pagina_imoveis():
    return send_from_directory("static", "imoveis.html")


@app.route("/painel/<imovel>")
def painel(imovel):
    if not imovel_existe(imovel) or not pode_ver(imovel):
        return redirect("/imoveis")
    return send_from_directory("static", "admin.html")


@app.route("/tour/<imovel>")
def visualizador(imovel):
    if not imovel_existe(imovel):
        return redirect("/imoveis")
    return _com_previa("viewer.html", imovel)


def _texto_da_previa(tour):
    """Segunda linha da prévia: o que faz alguém decidir tocar no link."""
    partes = []
    n = len(tour.get("cenas", []))
    if n:
        partes.append("%d ambiente%s em 360°" % (n, "s" if n > 1 else ""))
    metros = sum(c["area"]["m2"] for c in tour.get("cenas", []) if c.get("area"))
    if metros:
        partes.append(("%.1f m²" % metros).replace(".", ","))
    for campo in ("endereco", "preco"):
        if tour.get(campo):
            partes.append(str(tour[campo]))
    return " · ".join(partes) or "Visita virtual pelo imóvel."


def _com_previa(pagina, imovel_id):
    """
    Serve a página do tour com as etiquetas de prévia já no HTML.

    Imóvel se vende por link no WhatsApp, e ali o link ia PELADO: só o endereço
    cru, sem foto, sem título, sem metragem. Link com a foto da sala e "3
    ambientes · 11,1 m²" é tocado muito mais do que uma URL seca — e essa é a
    diferença entre o corretor mandar o tour ou mandar as fotos soltas.

    Tem de ser no HTML servido, e não no JavaScript: o robô que monta a prévia
    busca a página uma vez e NÃO executa script. Injetado pela página pronta, o
    robô veria o cabeçalho vazio do arquivo estático.
    """
    caminho = os.path.join(RAIZ, "static", pagina)
    try:
        with io.open(caminho, encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return send_from_directory("static", pagina)

    tour = carregar_tour(imovel_id)
    titulo = tour.get("titulo") or "Tour virtual"
    descricao = _texto_da_previa(tour)
    raiz = request.url_root.rstrip("/")
    capa = next((c.get("miniatura") or c.get("arquivo")
                 for c in tour.get("cenas", []) if c.get("arquivo")), None)

    etiquetas = [
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Tour Virtual">',
        '<meta property="og:locale" content="pt_BR">',
        '<meta property="og:title" content="%s">' % escape(titulo),
        '<meta property="og:description" content="%s">' % escape(descricao),
        '<meta property="og:url" content="%s/tour/%s">' % (escape(raiz),
                                                           escape(imovel_id)),
        '<meta name="description" content="%s">' % escape(descricao),
    ]
    if capa:
        # endereco absoluto: o robo busca de fora e nao resolve caminho relativo
        imagem = "%s/data/%s/scenes/%s" % (raiz, imovel_id, capa)
        etiquetas += [
            '<meta property="og:image" content="%s">' % escape(imagem),
            '<meta name="twitter:card" content="summary_large_image">',
            '<meta name="twitter:image" content="%s">' % escape(imagem),
        ]
    else:
        etiquetas.append('<meta name="twitter:card" content="summary">')

    html = html.replace("<head>", "<head>\n" + "\n".join(etiquetas), 1)
    html = html.replace("<title>Tour Virtual</title>",
                        "<title>%s</title>" % escape(titulo), 1)
    resposta = Response(html, mimetype="text/html")
    # o robo guarda a previa por muito tempo; titulo trocado tem de chegar
    resposta.headers["Cache-Control"] = "public, max-age=300"
    return resposta


@app.route("/andar/<imovel>")
def andar(imovel):
    if not imovel_existe(imovel):
        return redirect("/imoveis")
    return send_from_directory("static", "andar.html")


@app.route("/maquete/<imovel>")
def maquete(imovel):
    """A vista 3D do imovel: a mesma geometria do tour, vista por fora."""
    if not imovel_existe(imovel) or not tem_maquete(imovel):
        return redirect("/tour/" + imovel if imovel_existe(imovel) else "/imoveis")
    return _com_previa("maquete.html", imovel)


@app.route("/capturar/<imovel>")
def capturar(imovel):
    """
    O guia de captura, para abrir no celular DENTRO do imovel.

    Nao e publico: quem entra ve o que falta capturar, e isso e o avesso do
    anuncio. A pagina exige sessao como qualquer tela de trabalho.
    """
    if not imovel_existe(imovel):
        return redirect("/imoveis")
    return send_from_directory("static", "capturar.html")


@app.route("/data/<imovel>/scenes/<path:nome>")
def arquivo_cena(imovel, nome):
    if not imovel_existe(imovel):
        abort(404)
    return send_from_directory(pasta_cenas(imovel), nome)


# --------------------------------------------------------- lista de imoveis

@app.route("/api/imoveis", methods=["GET"])
def api_listar_imoveis():
    conta = conta_atual()
    return jsonify({"ok": True, "imoveis": listar_imoveis(conta["id"]),
                    "imobiliaria": conta["imobiliaria"]})


@app.route("/api/imoveis", methods=["POST"])
def api_criar_imovel():
    titulo = (request.get_json(silent=True) or {}).get("titulo", "").strip()
    iid = criar_imovel(titulo, conta_atual()["id"])
    return jsonify({"ok": True, "id": iid})


# ------------------------------------------------------------------- contas

@app.route("/api/conta", methods=["GET"])
def api_estado_conta():
    """A tela de entrada pergunta se ja existe alguma conta neste servidor."""
    conta = conta_atual()
    return jsonify({"ok": True, "primeiro_acesso": not usuarios.ha_usuarios(PASTA_DADOS),
                    "logado": bool(conta),
                    "imobiliaria": conta["imobiliaria"] if conta else ""})


# ---------------------------------------------------- freio de forca bruta
#
# A espera de 1 segundo por tentativa errada atrapalha um ataque, mas nao o
# impede: 1 por segundo ainda da 86 mil tentativas por dia, e senha de corretor
# nao costuma aguentar 86 mil. Na rede interna isso nao preocupava; publicado na
# internet, preocupa.
#
# A contagem e por ORIGEM, nao por usuario: travar por usuario deixaria qualquer
# um trancar a conta do corretor de fora, o que troca um problema por outro.
TENTATIVAS_ATE_TRAVAR = 8
TRAVA_SEGUNDOS = 300.0
_tentativas = {}
_trava_tentativas = threading.Lock()


def _origem():
    """IP de quem chama, respeitando o proxy so quando ha um configurado."""
    if os.environ.get("TOUR_ATRAS_DE_PROXY") == "1":
        adiante = request.headers.get("X-Forwarded-For", "")
        if adiante:
            return adiante.split(",")[0].strip()
    return request.remote_addr or "?"


def _espera_da_trava(origem):
    """Segundos que ainda faltam, ou 0 se pode tentar."""
    with _trava_tentativas:
        erros, ate = _tentativas.get(origem, (0, 0.0))
        if erros >= TENTATIVAS_ATE_TRAVAR and ate > time.time():
            return ate - time.time()
    return 0.0


def _contar_erro(origem):
    with _trava_tentativas:
        erros, _ = _tentativas.get(origem, (0, 0.0))
        erros += 1
        _tentativas[origem] = (erros, time.time() + TRAVA_SEGUNDOS)
        # nao deixa o dicionario crescer sem fim com IPs de passagem
        if len(_tentativas) > 4000:
            agora = time.time()
            for k, (_, v) in list(_tentativas.items()):
                if v < agora:
                    _tentativas.pop(k, None)


def _limpar_erros(origem):
    with _trava_tentativas:
        _tentativas.pop(origem, None)


@app.route("/api/entrar", methods=["POST"])
def api_entrar():
    """
    Entrada e criacao da primeira conta.

    Nao existe cadastro aberto: a primeira conta e criada no primeiro acesso ao
    servidor, e as demais imobiliarias saem do `conta.py`, na mao de quem opera.
    Cadastro publico num produto vendido a imobiliarias so serviria para estranho
    criar conta no servidor do cliente.
    """
    d = request.get_json(silent=True) or {}
    nome = (d.get("usuario") or "").strip().lower()
    senha = d.get("senha") or ""

    origem = _origem()
    falta = _espera_da_trava(origem)
    if falta > 0:
        return jsonify({"ok": False, "erro":
                        "Tentativas demais deste endereço. Tente de novo em "
                        "%d minutos." % max(1, int(falta / 60) + 1)}), 429

    if not usuarios.ha_usuarios(PASTA_DADOS):
        try:
            usuarios.criar(PASTA_DADOS, nome, senha, d.get("imobiliaria") or "")
        except usuarios.ErroUsuario as e:
            return jsonify({"ok": False, "erro": str(e)}), 400
        adotar_imoveis_sem_dono()
    elif not usuarios.verificar(PASTA_DADOS, nome, senha):
        _contar_erro(origem)
        time.sleep(1.0)                 # atrasa a tentativa em massa
        return jsonify({"ok": False, "erro": "Usuário ou senha incorretos."}), 401

    _limpar_erros(origem)               # acertou: a conta volta ao normal

    session.permanent = True
    session["usuario"] = nome
    conta = usuarios.obter(PASTA_DADOS, nome)
    return jsonify({"ok": True, "imobiliaria": conta["imobiliaria"]})


# ------------------------------------------------------- recarregar o servidor
#
# A publicacao virou o gargalo: copiar os arquivos e facil, mas o processo velho
# segue na memoria com o codigo antigo, e aplicar dependia de alguem abrir um
# terminal e acertar um comando. Errou tres vezes seguidas aqui, e a culpa nao e
# de quem digitou: e do produto, que nao sabia se recarregar.
#
# O processo simplesmente SAI. Quem repoe e o vigia, em segundos, ja lendo os
# arquivos novos — por isso a rota se recusa a agir quando nao ha vigia: ali
# sair deixaria o site fora do ar ate alguem ir na maquina.
INICIADO_EM = time.time()


def _fontes_do_projeto():
    import glob
    return (glob.glob(os.path.join(RAIZ, "*.py"))
            + glob.glob(os.path.join(RAIZ, "static", "*.html")))


def versao_pendente():
    """
    Diz se ha codigo publicado no disco que este processo ainda nao carregou.

    Comparar a hora de inicio com a do arquivo mais novo e barato e exato: o
    processo sabe quando nasceu. Sem isto o painel nao teria como avisar, e a
    pessoa so descobriria que a publicacao nao pegou quando o recurso novo nao
    aparecesse.
    """
    try:
        arquivos = _fontes_do_projeto()
        if not arquivos:
            return {"pendente": False, "motivo": "não achei os arquivos"}
        mais_novo = max(arquivos, key=os.path.getmtime)
        quando = os.path.getmtime(mais_novo)
    except OSError as e:
        return {"pendente": False, "motivo": str(e)}
    return {"pendente": quando > INICIADO_EM,
            "arquivo": os.path.basename(mais_novo),
            "minutos": max(0, int((quando - INICIADO_EM) / 60))}


def ha_vigia():
    return os.environ.get("TOUR_VIGIADO") == "1"


@app.route("/api/versao", methods=["GET"])
def api_versao():
    dados = versao_pendente()
    dados.update({"ok": True, "ha_vigia": ha_vigia(),
                  "no_ar_desde": int(time.time() - INICIADO_EM)})
    return jsonify(dados)


@app.route("/api/recarregar", methods=["POST"])
def api_recarregar():
    """Sai do ar de proposito, para o vigia repor com o codigo publicado."""
    if not ha_vigia():
        return jsonify({"ok": False, "erro":
                        "Este servidor não está sob o vigia, então ninguém o "
                        "traria de volta. Rode-o por 'python servico.py' ou "
                        "reinicie na mão."}), 409

    def sair():
        time.sleep(0.6)          # tempo de a resposta chegar ao painel
        os._exit(0)              # saida limpa: o vigia repoe em segundos

    threading.Thread(target=sair, daemon=True, name="recarregar").start()
    return jsonify({"ok": True, "aviso": "Saindo do ar; o vigia repõe em "
                                         "alguns segundos."})


@app.route("/api/sair", methods=["POST"])
def api_sair():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/imoveis/<imovel>", methods=["DELETE"])
def api_remover_imovel(imovel):
    """
    Apaga o imovel inteiro: tour, cenas, mapas de profundidade e leads.

    A checagem de posse esta aqui, e nao no before_request do Blueprint, porque
    esta rota vive no `app`. Sem ela, uma conta apagava o acervo de outra so
    sabendo o id — foi o que aconteceu no teste da matriz de acesso.
    """
    if not imovel_existe(imovel) or not pode_ver(imovel):
        return jsonify({"ok": False, "erro": "Imóvel não encontrado."}), 404
    for cena in carregar_tour(imovel)["cenas"]:
        if cena.get("lote"):
            shutil.rmtree(os.path.join(PASTA_UPLOADS, cena["lote"]), ignore_errors=True)
    shutil.rmtree(pasta_imovel(imovel), ignore_errors=True)
    return jsonify({"ok": True})


@app.route("/data/uploads/<path:nome>")
def arquivo_upload(nome):
    return send_from_directory(PASTA_UPLOADS, nome)


# ------------------------------------------------------------------ api tour

@api.route("/tour", methods=["GET"])
def api_obter_tour():
    """
    O visualizador publico usa esta rota, entao ela nunca devolve dado interno.

    Antes mandava o tour inteiro, com leads_capturados junto: qualquer um com o
    link do tour lia nome, telefone e e-mail de todos os contatos capturados. O
    painel busca esses dados em /leads e /metricas.
    """
    tour = carregar_tour()
    for campo in ("leads_capturados", "visitas"):
        tour.pop(campo, None)
    return jsonify(tour)


@api.route("/maquete", methods=["GET"])
def api_maquete():
    """
    Devolve a geometria. Publica, como o tour: quem abre o link do imovel ve a
    maquete sem precisar de conta.
    """
    caminho = arq_maquete(g.imovel)
    tour_agora = carregar_tour()
    if not os.path.exists(caminho):     # imovel de fotos nao tem geometria
        # ...a nao ser que alguem tenha importado um escaneamento. Ai a
        # geometria vem do OBJ, e a pagina busca o arquivo em vez das caixas.
        if tem_modelo(g.imovel):
            info = tour_agora.get("modelo", {})
            return jsonify({"ok": True, "maquete": {
                "importado": True,
                "titulo": tour_agora.get("titulo", ""),
                "descricao": tour_agora.get("descricao", ""),
                "medidas": info.get("medidas", {}),
                "avisos": info.get("avisos", []),
                "tem_mtl": os.path.exists(arq_modelo(g.imovel, ".mtl")),
                "texturas": texturas_do_modelo(g.imovel),
                "frente": _orientacao(tour_agora),
                "zonas": [], "caixas": [], "pontos": [], "janelas": [],
                "larg": (info.get("medidas") or {}).get("largura", 10),
                "fundo": (info.get("medidas") or {}).get("fundo", 10),
                "pe": (info.get("medidas") or {}).get("altura", 2.7)}})
        return jsonify({"ok": False, "erro":
                        "Este imóvel não tem geometria: a maquete só existe "
                        "para ambiente gerado, não para foto."}), 404
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)
    tour = carregar_tour()
    dados["titulo"] = tour.get("titulo") or dados.get("nome", "")
    dados["descricao"] = tour.get("descricao") or dados.get("descricao", "")
    dados["frente"] = _orientacao(tour)

    # Costura a maquete ao tour: cada ponto de captura vira um link para a cena
    # 360 tirada dali. O casamento e pelo NOME, que e o mesmo dos dois lados
    # porque a cena nasceu do ponto. Cena renomeada perde o link e o pino deixa
    # de ser clicavel — o que e melhor do que levar para a cena errada.
    por_nome = {c.get("nome"): c.get("id") for c in tour.get("cenas", [])}
    for ponto in dados.get("pontos", []):
        ponto["cena_id"] = por_nome.get(ponto.get("nome"))
    return jsonify({"ok": True, "maquete": dados})


def _orientacao(tour):
    """
    Para que lado aponta a frente do imovel, em graus de bussola.

    None quando ninguem disse. E diferente de zero: zero e "a frente olha para
    o NORTE", que e uma informacao; None e "nao sabemos", e a pagina precisa
    saber a diferenca para nao inventar a hora do sol.
    """
    valor = tour.get("frente")
    if valor is None:
        return None
    try:
        return int(float(valor)) % 360
    except (TypeError, ValueError):
        return None


@api.route("/orientacao", methods=["PUT", "DELETE"])
def api_orientacao():
    """
    Guarda para que lado a frente do imovel esta voltada.

    Isto nao sai da geometria: planta nenhuma carrega o norte. Quem sabe e
    quem esteve no imovel, e por isso e do dono — e fica gravado no tour, e
    nao no endereco, para que TODO visitante veja a mesma coisa. Orientacao
    que viajasse so no link daria sol da manha para um e sol da tarde para
    outro, no mesmo imovel.
    """
    tour = carregar_tour()
    if request.method == "DELETE":
        tour.pop("frente", None)
        salvar_tour(tour)
        return jsonify({"ok": True, "frente": None})

    bruto = (request.get_json(silent=True) or {}).get("frente")
    try:
        graus = int(float(bruto)) % 360
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro":
                        "Informe a direção da frente em graus, de 0 a 359."}), 422
    tour["frente"] = graus
    salvar_tour(tour)
    return jsonify({"ok": True, "frente": graus})


@api.route("/captura", methods=["GET"])
def api_captura():
    """
    O que ja foi capturado neste imovel e o que ainda falta.

    E do dono, e nao publica: e o avesso do anuncio. Diz onde a captura esta
    fraca, que e exatamente o que nao se conta para o comprador.
    """
    tour = carregar_tour()
    resumo, achados = captura.diagnosticar(tour)
    return jsonify({"ok": True, "resumo": resumo, "achados": achados,
                    "passo": captura.proximo_passo(resumo, achados),
                    "titulo": tour.get("titulo", "")})


@api.route("/vizinhanca", methods=["PUT", "DELETE"])
def api_vizinhanca():
    """
    Busca (ou apaga) o que existe em volta do imovel.

    E do dono porque e ELE quem chama a rede: quem visita apenas le o que ficou
    gravado. Se a busca acontecesse a cada visita, o anuncio ficaria refem de
    dois servicos de terceiro estarem no ar — e a hora em que eles caem e
    sempre a pior hora possivel.
    """
    tour = carregar_tour()
    if request.method == "DELETE":
        tour.pop("vizinhanca", None)
        salvar_tour(tour)
        return jsonify({"ok": True, "vizinhanca": None})

    try:
        achado = vizinhanca.buscar(tour.get("endereco", ""))
    except vizinhanca.ErroVizinhanca as erro:
        return jsonify({"ok": False, "erro": str(erro)}), 422

    tour["vizinhanca"] = achado
    salvar_tour(tour)
    return jsonify({"ok": True, "vizinhanca": achado})


@api.route("/modelo", methods=["POST"])
def api_enviar_modelo():
    """
    Recebe o OBJ de um escaneamento e passa a usa-lo como maquete do imovel.

    A conferencia acontece ANTES de gravar: OBJ e texto, qualquer arquivo pode
    se chamar .obj, e modelo que so se descobre quebrado na hora de abrir deixa
    o corretor sem entender o que houve.
    """
    arquivo = request.files.get("modelo")
    if not arquivo:
        return jsonify({"ok": False, "erro": "Nenhum arquivo enviado."}), 400
    if not arquivo.filename.lower().endswith(".obj"):
        return jsonify({"ok": False, "erro":
                        "Envie o arquivo .obj. No aplicativo de escaneamento, "
                        "exporte em OBJ — não em USDZ nem em PLY."}), 422

    bruto = arquivo.read()
    try:
        texto = bruto.decode("utf-8", errors="replace")
        medidas, avisos = modelo3d.conferir(texto, len(bruto))
    except modelo3d.ErroModelo as e:
        return jsonify({"ok": False, "erro": str(e)}), 422

    with open(arq_modelo(g.imovel), "wb") as f:
        f.write(bruto)
    mtl = request.files.get("mtl")
    pedidas = []
    if mtl and mtl.filename.lower().endswith(".mtl"):
        bruto_mtl = mtl.read()
        with open(arq_modelo(g.imovel, ".mtl"), "wb") as f:
            f.write(bruto_mtl)
        pedidas = modelo3d.texturas_do_mtl(
            bruto_mtl.decode("utf-8", errors="replace"))

    # As imagens que o .mtl pede. Sem elas o escaneamento entra como massa
    # cinza: mais fiel em medida e muito pior de olhar do que no aplicativo.
    guardadas = []
    for imagem in request.files.getlist("texturas"):
        destino = arq_textura(g.imovel, imagem.filename)
        if not destino:
            avisos.append("Ignorei %s: não é imagem de textura conhecida."
                          % imagem.filename)
            continue
        imagem.save(destino)
        guardadas.append(os.path.basename(destino)[len("modelotex_"):])

    faltando = [n for n in (modelo3d.nome_de_textura_seguro(p) for p in pedidas)
                if n and n not in guardadas]
    if faltando:
        avisos.append(
            "O modelo pede %d imagem(ns) de textura que não vieram (%s). Ele "
            "abre assim mesmo, em cinza. No aplicativo, exporte o OBJ com as "
            "texturas e envie os arquivos juntos."
            % (len(faltando), ", ".join(faltando[:3])))

    tour = carregar_tour()
    tour["modelo"] = {"medidas": medidas, "avisos": avisos,
                      "texturas": guardadas,
                      "enviado_em": datetime.now().isoformat(timespec="seconds")}
    salvar_tour(tour)
    return jsonify({"ok": True, "medidas": medidas, "avisos": avisos})


@api.route("/modelo", methods=["DELETE"])
def api_apagar_modelo():
    for ext in (".obj", ".mtl"):
        caminho = arq_modelo(g.imovel, ext)
        if os.path.exists(caminho):
            os.remove(caminho)
    # textura sem modelo e lixo que ninguem vai procurar depois
    for nome in texturas_do_modelo(g.imovel):
        caminho = arq_textura(g.imovel, nome)
        if caminho and os.path.exists(caminho):
            os.remove(caminho)
    tour = carregar_tour()
    tour.pop("modelo", None)
    salvar_tour(tour)
    return jsonify({"ok": True})


@api.route("/modelo.obj", methods=["GET"])
def api_baixar_modelo():
    """
    Serve o modelo para a pagina desenhar.

    E publico por NECESSIDADE, nao por escolha: a maquete roda no navegador de
    quem abre o link, e desenhar exige que os bytes cheguem ate la. Quem
    importa um escaneamento esta publicando a geometria junto com o tour — e o
    painel diz isso na hora do envio.
    """
    caminho = arq_modelo(g.imovel)
    if not os.path.exists(caminho):
        return jsonify({"ok": False, "erro": "Sem modelo importado."}), 404
    return send_file(caminho, mimetype="text/plain")


@api.route("/modelo.mtl", methods=["GET"])
def api_baixar_modelo_mtl():
    caminho = arq_modelo(g.imovel, ".mtl")
    if not os.path.exists(caminho):
        return jsonify({"ok": False, "erro": "Sem materiais."}), 404
    return send_file(caminho, mimetype="text/plain")


@api.route("/modelo/textura/<nome>", methods=["GET"])
def api_textura_do_modelo(nome):
    """
    Serve a imagem que o escaneamento cola na malha.

    Publica pelo mesmo motivo do proprio modelo: a maquete desenha no navegador
    de quem abre o link, e sem os bytes da textura o comodo aparece em cinza.
    """
    caminho = arq_textura(g.imovel, nome)
    if not caminho or not os.path.exists(caminho):
        return jsonify({"ok": False, "erro": "Textura não encontrada."}), 404
    return send_file(caminho)


@api.route("/maquete/obj", methods=["GET"])
def api_maquete_obj():
    """
    Baixa a geometria como OBJ + MTL, para abrir no SketchUp ou no Blender.

    Ao contrario de ver a maquete, isto NAO e publico. Ver o imovel e o que
    ajuda a vender; levar embora o modelo editavel e outra coisa, e quem decide
    e a dona do imovel. Visitante continua podendo olhar, girar e medir.
    """
    caminho = arq_maquete(g.imovel)
    if not os.path.exists(caminho):
        return jsonify({"ok": False, "erro":
                        "Este imóvel não tem geometria para exportar."}), 404
    with open(caminho, "r", encoding="utf-8") as f:
        geo = json.load(f)
    geo["titulo"] = carregar_tour().get("titulo") or geo.get("nome", "maquete")
    memoria, nome = maquete3d.zipar(geo)
    return send_file(memoria, mimetype="application/zip", as_attachment=True,
                     download_name=nome)


@api.route("/tour", methods=["PUT"])
def api_salvar_tour():
    tour = carregar_tour()
    dados = request.get_json(force=True)
    for campo in ("titulo", "descricao", "endereco", "preco", "cor",
                  "cena_inicial", "lead", "logo"):
        if campo in dados:
            tour[campo] = dados[campo]

    # Endereco corrigido depois da busca deixaria o anuncio mostrando o mercado
    # do endereco ANTIGO, sem avisar ninguem. Melhor perder a vizinhanca e
    # pedir para buscar de novo do que exibir a do lugar errado.
    if vizinhanca.esta_velha(tour):
        tour.pop("vizinhanca", None)

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
        nome_lote = uuid.uuid4().hex[:10]
        lote = os.path.join(PASTA_UPLOADS, nome_lote)
        os.makedirs(lote, exist_ok=True)
        for i, f in enumerate(arquivos):
            ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                ext = ".jpg"
            destino = os.path.join(lote, "foto_%02d%s" % (i, ext))
            f.save(destino)
            recado = formato_recusado(destino, f.filename)
            if recado:
                return jsonify({"ok": False, "erro": recado}), 400
            temporarios.append(destino)

        imovel = g.imovel
        destino = pasta_cenas()

        def trabalho(relatar):
            arquivo, largura, altura, info = stitcher.costurar(
                temporarios, destino, relatar)

            with trava_do_imovel(imovel):
                tour = carregar_tour(imovel)
                cena = montar_cena(nome, arquivo, largura, altura, "costura", info,
                                   imovel_id=imovel)
                cena["lote"] = nome_lote      # para apagar as originais junto com a cena
                tour["cenas"].append(cena)
                if not tour["cena_inicial"]:
                    tour["cena_inicial"] = cena["id"]
                salvar_tour(tour, imovel)

            # o que a conferencia viu na captura vem primeiro: e o que o corretor
            # precisa mudar na proxima vez
            avisos = list(info.get("conferencia") or [])
            if not info["fechada"]:
                avisos.append(
                    "Você cobriu %.0f graus, com um vão de %.0f graus sem foto. O "
                    "ambiente abre como panorama parcial. Para virar 360 completo, "
                    "feche a volta." % (info["haov"], info["maior_buraco"]))
            niv = info.get("nivelamento") or {}
            if niv.get("aplicado"):
                avisos.append(
                    "Horizonte nivelado: a captura estava %.1f° fora do prumo, "
                    "corrigida com %d linhas verticais da cena."
                    % (niv.get("inclinacao", 0), niv.get("linhas_usadas", 0)))
            elif niv.get("motivo"):
                avisos.append("Não consegui nivelar: " + niv["motivo"])

            exp = info.get("exposicao", {})
            if exp.get("antes") and exp.get("depois"):
                ganho = exp["antes"]["sombra_esmagada"] - exp["depois"]["sombra_esmagada"]
                if ganho > 0.5:
                    avisos.append(
                        "Exposição corrigida: detalhe recuperado em %.1f%% da imagem "
                        "que estava escura demais." % ganho)
            if info["fileiras"] == 1:
                avisos.append(
                    "Captura em 1 fileira: teto e chão foram preenchidos por "
                    "aproximação. Fotografe também com o celular inclinado para cima "
                    "e para baixo se quiser teto e chão reais.")
            return {"cena": cena, "fotos_usadas": len(temporarios), "avisos": avisos}

        tid = tarefas.criar(imovel, "costura", "Costurando %s" % nome)
        tarefas.enfileirar(tid, trabalho)
        return jsonify({"ok": True, "tarefa": tid}), 202

    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "erro": "Erro inesperado: %s" % e}), 500


@api.route("/cenas/video", methods=["POST"])
def api_costurar_video():
    """
    Recebe um video girando no mesmo ponto e costura os melhores quadros.

    Video nao rende panorama melhor que foto — rende panorama mais dificil de
    errar: a sobreposicao e continua, entao nao existe "girei demais". O preco e
    resolucao, e video.conferir_largura avisa quando ela nao da.
    """
    arquivo = (request.files.get("video") or
               (request.files.getlist("fotos") or [None])[0])
    nome = (request.form.get("nome") or "Ambiente").strip()

    if arquivo is None or not arquivo.filename:
        return jsonify({"ok": False, "erro": "Selecione um vídeo do ambiente."}), 400

    ext = os.path.splitext(arquivo.filename)[1].lower()
    if ext not in video.EXTENSOES:
        return jsonify({"ok": False, "erro":
                        "Formato não suportado (%s). Envie MP4 ou MOV, que é o que "
                        "o celular grava." % (ext or "sem extensão")}), 400

    try:
        nome_lote = uuid.uuid4().hex[:10]
        lote = os.path.join(PASTA_UPLOADS, nome_lote)
        os.makedirs(lote, exist_ok=True)
        origem = os.path.join(lote, "video" + ext)
        arquivo.save(origem)

        imovel = g.imovel
        destino = pasta_cenas()

        def trabalho(relatar):
            quadros, avisos_video = video.extrair_quadros(origem, lote, relatar)
            arq, largura, altura, info = stitcher.costurar(quadros, destino, relatar)

            with trava_do_imovel(imovel):
                tour = carregar_tour(imovel)
                cena = montar_cena(nome, arq, largura, altura, "video", info,
                                   imovel_id=imovel)
                cena["lote"] = nome_lote
                tour["cenas"].append(cena)
                if not tour["cena_inicial"]:
                    tour["cena_inicial"] = cena["id"]
                salvar_tour(tour, imovel)

            # o video ja virou quadros; guardar o original so ocupa disco
            try:
                os.remove(origem)
            except OSError:
                pass

            avisos = list(avisos_video) + list(info.get("conferencia") or [])
            if not info["fechada"]:
                avisos.append(
                    "Você cobriu %.0f graus, com um vão de %.0f graus sem imagem. "
                    "Para fechar a volta, gire até voltar ao ponto de partida antes "
                    "de parar a gravação." % (info["haov"], info["maior_buraco"]))
            return {"cena": cena, "fotos_usadas": len(quadros), "avisos": avisos}

        tid = tarefas.criar(imovel, "video", "Vídeo de %s" % nome)
        tarefas.enfileirar(tid, trabalho)
        return jsonify({"ok": True, "tarefa": tid}), 202

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
            prontas.append(montar_cena(rotulo, arquivo, largura, altura, "varredura",
                                       info, imovel_id=g.imovel))

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
                    "A foto %s não está na proporção 2:1 (está %dx%d), então não é um "
                    "360 completo. Estimei %.0f° de cobertura pelo formato; se as "
                    "paredes parecerem esticadas ou espremidas, ajuste em "
                    "“Cobertura horizontal”." % (rotulo, largura, altura, cena["haov"]))
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
    # o poster de abertura e um recorte da vista inicial: se ela mudou, refaz
    if {"vista_inicial", "haov", "vaov"} & set(dados):
        cena["esboco"] = gerar_esboco(g.imovel, cena)
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
    for chave in ("textura", "profundidade"):
        nome = (cena.get("fundo") or {}).get(chave)
        if nome:
            caminho = os.path.join(pasta_cenas(), nome)
            if os.path.exists(caminho):
                os.remove(caminho)
    for chave in ("arquivo", "profundidade", "previa_profundidade",
                  "miniatura", "esboco"):
        if chave == "arquivo":
            orig = os.path.join(pasta_cenas(), "orig_" + cena["arquivo"])
            if os.path.exists(orig):
                os.remove(orig)
        nome = cena.get(chave)
        if not nome:
            continue
        caminho = os.path.join(pasta_cenas(), nome)
        if os.path.exists(caminho):
            os.remove(caminho)

    if cena.get("lote"):
        shutil.rmtree(os.path.join(PASTA_UPLOADS, cena["lote"]), ignore_errors=True)

    tour["cenas"] = [c for c in tour["cenas"] if c["id"] != cena_id]

    # limpa hotspots que apontavam para a cena removida
    for outra in tour["cenas"]:
        outra["hotspots"] = [h for h in outra.get("hotspots", [])
                             if h.get("destino") != cena_id]
    if tour["cena_inicial"] == cena_id:
        tour["cena_inicial"] = tour["cenas"][0]["id"] if tour["cenas"] else None
    salvar_tour(tour)
    return jsonify({"ok": True})


@api.route("/cenas/<cena_id>/area", methods=["GET"])
def api_area(cena_id):
    """Metragem a partir do mapa de profundidade, com retangulo ajustado."""
    cena = achar_cena(carregar_tour(), cena_id)
    if not cena:
        return jsonify({"ok": False, "erro": "Cena não encontrada."}), 404
    if not cena.get("profundidade"):
        return jsonify({"ok": False, "erro":
                        "Gere a profundidade deste ambiente antes de medir."}), 422
    try:
        r = area.medir(os.path.join(pasta_cenas(), cena["profundidade"]))
    except area.ErroArea as e:
        return jsonify({"ok": False, "erro": str(e)}), 422
    return jsonify({"ok": True, "medida": r})


@api.route("/cenas/<cena_id>/area", methods=["PUT", "DELETE"])
def api_publicar_area(cena_id):
    """
    Grava (ou tira) a metragem que aparece no anuncio.

    Medir e publicar sao passos separados de proposito. A estimativa tem uns 2%
    de erro e o corretor costuma ter o numero da matricula, que vale mais. Quem
    publica assume o numero — por isso fica gravado se ele foi medido ou digitado.
    """
    tour = carregar_tour()
    cena = achar_cena(tour, cena_id)
    if not cena:
        return jsonify({"ok": False, "erro": "Cena não encontrada."}), 404

    if request.method == "DELETE":
        cena.pop("area", None)
        salvar_tour(tour)
        return jsonify({"ok": True})

    dados = request.get_json(silent=True) or {}
    try:
        metros = float(str(dados.get("area_m2", "")).replace(",", "."))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "Metragem inválida."}), 400
    if not (1.0 <= metros <= 400.0):
        return jsonify({"ok": False, "erro":
                        "A metragem precisa ficar entre 1 e 400 m²."}), 400

    registro = {"m2": round(metros, 1),
                "origem": "informado" if dados.get("corrigido") else "medido"}
    for campo in ("comprimento_m", "largura_m"):
        try:
            registro[campo] = round(float(dados[campo]), 2)
        except (KeyError, TypeError, ValueError):
            pass
    # Guarda o quanto a medida merecia credito. Numero digitado pelo corretor
    # dispensa: quem digitou assumiu. Numero estimado carrega a nota junto,
    # porque metragem errada num anuncio e o que o comprador usa para comparar
    # preco — e a estimativa erra feio em comodo nao retangular.
    if registro["origem"] == "medido" and isinstance(dados.get("confianca"), dict):
        c = dados["confianca"]
        if c.get("leitura") in ("alta", "media", "baixa"):
            registro["confianca"] = {"nota": c.get("nota"),
                                     "leitura": c.get("leitura")}
    cena["area"] = registro
    salvar_tour(tour)
    return jsonify({"ok": True, "area": registro})


def _fatia(relatar, feito, total, rotulo):
    """
    Transforma o andamento de UMA cena no andamento do lote.

    Sem isto a barra voltaria a zero a cada cena, e quem esta olhando
    concluiria que travou e recarregaria a pagina no meio do trabalho.
    """
    largura = 100.0 / max(1, total)
    inicio = largura * feito

    def relatar_fatia(pct, mensagem=""):
        relatar(inicio + largura * (pct / 100.0),
                "%s — %s" % (rotulo, mensagem) if mensagem else rotulo)
    return relatar_fatia


def _fazer_profundidade(imovel, destino, cena_id, cena, relatar):
    """
    Calcula e grava a profundidade de uma cena. Devolve a cena atualizada.

    Vive fora da rota porque o lote precisa exatamente disto, e duplicar faria
    um defeito precisar de dois consertos — com a copia errada escolhida no
    dia em que ninguem lembra que ha duas.
    """
    panorama = os.path.join(destino, cena["arquivo"])
    disp, previa = profundidade.gerar(panorama, relatar=relatar)
    nome = "prof_%s.png" % cena_id
    profundidade.salvar(disp, os.path.join(destino, nome))

    nome_previa = "prev_%s.jpg" % cena_id
    ok, buf = cv2.imencode(".jpg", previa, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if ok:
        buf.tofile(os.path.join(destino, nome_previa))

    # Previsao de escorrido: o corretor precisa saber se a captura presta ANTES
    # de publicar, e nao descobrir pelo cliente. Sai de graca aqui, porque o
    # panorama e a profundidade ja estao na mao.
    try:
        escorrido = profundidade.medir_escorrido(
            stitcher._ler_imagem(panorama), disp)
    except Exception:
        escorrido = None          # medida e informacao, nao pode derrubar a tarefa

    with trava_do_imovel(imovel):
        tour = carregar_tour(imovel)     # relê: pode ter mudado durante o calculo
        atual = achar_cena(tour, cena_id)
        if not atual:
            raise RuntimeError("A cena foi removida durante o cálculo.")
        atual["profundidade"] = nome
        atual["previa_profundidade"] = nome_previa
        if escorrido:
            atual["escorrido"] = escorrido
        salvar_tour(tour, imovel)
    return atual


def _fazer_fundo(imovel, destino, cena_id, cena, relatar):
    """Reconstroi e grava a camada de fundo. Devolve (cena, info)."""
    relatar(5, "procurando o que está na frente")
    panorama = os.path.join(destino, cena["arquivo"])
    profundo = os.path.join(destino, cena["profundidade"])
    textura, disp, info = fundo.gerar(panorama, profundo, relatar=relatar)

    relatar(96, "gravando a camada")
    nome_tex = "fundotex_%s.jpg" % cena_id
    ok, buf = cv2.imencode(".jpg", textura, [cv2.IMWRITE_JPEG_QUALITY, 86])
    if not ok:
        raise RuntimeError("falha ao gravar a textura de fundo")
    buf.tofile(os.path.join(destino, nome_tex))

    nome_prof = "fundoprof_%s.png" % cena_id
    profundidade.salvar(disp, os.path.join(destino, nome_prof))

    with trava_do_imovel(imovel):
        tour = carregar_tour(imovel)
        atual = achar_cena(tour, cena_id)
        if not atual:
            raise RuntimeError("A cena foi removida durante a reconstrução.")
        atual["fundo"] = {"textura": nome_tex, "profundidade": nome_prof,
                          "reconstruido": info["reconstruido"], "gerado_por_ia": True}
        salvar_tour(tour, imovel)
    return atual, info


@api.route("/preparar", methods=["POST"])
def api_preparar():
    """
    Deixa o imovel INTEIRO pronto para caminhar, numa tarefa so.

    Ate aqui era cena por cena: num imovel de catorze pontos, o corretor
    clicava vinte e oito vezes e ficava olhando. Ninguem faz isso duas vezes —
    na pratica o passo era pulado, e o imovel ia para o ar sem profundidade ou
    sem camada de fundo, que sao justamente as duas coisas que fazem a
    caminhada valer.

    O que ele faz, por cena que ainda nao tem: gera a profundidade e, se o
    modelo de reconstrucao estiver instalado, a camada de fundo.

    Nao refaz o que ja existe. Refazer seria jogar fora meia hora de
    processamento por engano, e um clique a mais nao pode custar isso.
    """
    tour = carregar_tour()
    if not profundidade.modelo_disponivel():
        return jsonify({"ok": False, "erro":
                        "O modelo de profundidade não está instalado. Rode "
                        "'python baixar_modelo.py' uma vez (94 MB)."}), 422

    com_fundo = fundo.modelo_disponivel()
    cenas = [c for c in tour.get("cenas", []) if c.get("panorama_completo")]
    parciais = len(tour.get("cenas", [])) - len(cenas)

    # O que realmente ha para fazer. Contado ANTES de comecar, porque a barra
    # de andamento precisa saber o tamanho do trabalho para nao mentir.
    passos = []
    for cena in cenas:
        if not cena.get("profundidade"):
            passos.append((cena["id"], "profundidade"))
        if com_fundo and not cena.get("fundo"):
            passos.append((cena["id"], "fundo"))

    if not passos:
        return jsonify({"ok": True, "tarefa": None, "passos": 0,
                        "recado": "Tudo o que dava para preparar já está pronto."
                                  + ("" if com_fundo else
                                     " A camada de fundo exige o modelo de "
                                     "reconstrução: rode 'python baixar_modelo.py "
                                     "--fundo' uma vez (208 MB).")})

    imovel = g.imovel
    destino = pasta_cenas()
    total = len(passos)

    def trabalho(relatar):
        feitos = {"profundidade": 0, "fundo": 0}
        problemas = []
        for i, (cena_id, etapa) in enumerate(passos):
            atual = carregar_tour(imovel)
            cena = achar_cena(atual, cena_id)
            if not cena:
                continue                  # apagada no meio do lote: segue a vida
            rotulo = "%d de %d · %s" % (i + 1, total, cena.get("nome", ""))
            passo = _fatia(relatar, i, total, rotulo)
            try:
                if etapa == "profundidade":
                    if not cena.get("profundidade"):
                        _fazer_profundidade(imovel, destino, cena_id, cena, passo)
                        feitos["profundidade"] += 1
                else:
                    cena = achar_cena(carregar_tour(imovel), cena_id)
                    if cena and cena.get("profundidade") and not cena.get("fundo"):
                        _fazer_fundo(imovel, destino, cena_id, cena, passo)
                        feitos["fundo"] += 1
            except tarefas.Cancelada:
                raise
            except Exception as erro:
                # Uma cena ruim nao pode derrubar as outras treze. O corretor
                # prefere doze prontas e um recado a um lote inteiro perdido.
                problemas.append({"cena": cena.get("nome", "") if cena else cena_id,
                                  "etapa": etapa, "erro": str(erro)[:200]})
        relatar(100, "pronto")
        return {"feitos": feitos, "problemas": problemas,
                "com_fundo": com_fundo, "parciais": parciais}

    tid = tarefas.criar(imovel, "preparar",
                        "Preparar %d etapa(s) para caminhar" % total)
    tarefas.enfileirar(tid, trabalho)
    return jsonify({"ok": True, "tarefa": tid, "passos": total,
                    "com_fundo": com_fundo}), 202


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

    if not profundidade.modelo_disponivel():
        return jsonify({"ok": False, "erro":
                        "O modelo de profundidade não está instalado. Rode "
                        "'python baixar_modelo.py' uma vez (94 MB)."}), 422

    imovel = g.imovel
    destino = pasta_cenas()

    def trabalho(relatar):
        return {"cena": _fazer_profundidade(imovel, destino, cena_id, cena,
                                            relatar)}

    tid = tarefas.criar(imovel, "profundidade", "Profundidade de %s" % cena["nome"])
    tarefas.enfileirar(tid, trabalho)
    return jsonify({"ok": True, "tarefa": tid}), 202


@api.route("/cenas/<cena_id>/corrigir", methods=["POST"])
def api_corrigir_cena(cena_id):
    """
    Reaplica nivelamento e reconstrucao de teto numa cena ja gravada.

    Cenas montadas antes destas correcoes existirem ficaram com o horizonte torto
    e com o leque de cunhas no teto — bem visivel no modo de caminhada, onde a
    textura esticada vira geometria quebrada. As fotos originais ja foram
    apagadas, mas as duas correcoes trabalham sobre o equirretangular pronto.

    O mapa de profundidade e refeito junto: nivelar gira o panorama, e o mapa
    antigo passaria a apontar para as direcoes erradas.
    """
    tour = carregar_tour()
    cena = achar_cena(tour, cena_id)
    if not cena:
        return jsonify({"ok": False, "erro": "Cena não encontrada."}), 404
    if not cena.get("panorama_completo"):
        return jsonify({"ok": False, "erro":
                        "Só dá para corrigir cenas com 360 completo."}), 422
    if os.path.exists(os.path.join(pasta_cenas(), "orig_" + cena["arquivo"])):
        return jsonify({"ok": False, "erro":
                        "Tire a marca do chão antes de corrigir: ela seria "
                        "reaplicada sobre a imagem antiga."}), 422

    imovel = g.imovel
    destino = pasta_cenas()
    panorama = os.path.join(destino, cena["arquivo"])
    tinha_profundidade = bool(cena.get("profundidade"))

    def trabalho(relatar):
        relatar(10, "endireitando e refazendo o teto")
        info = stitcher.reprocessar(panorama)

        relatar(45, "refazendo miniatura e abertura")
        mini = gerar_miniatura(imovel, cena["arquivo"])
        esboco = gerar_esboco(imovel, cena)

        prof = previa = None
        if tinha_profundidade and profundidade.modelo_disponivel():
            # o panorama girou: o mapa antigo apontaria para as direcoes erradas
            def repassar(pct, txt):
                relatar(55 + int(pct * 0.4), txt)
            disp, img_previa = profundidade.gerar(panorama, relatar=repassar)
            prof = "prof_%s.png" % cena_id
            profundidade.salvar(disp, os.path.join(destino, prof))
            previa = "prev_%s.jpg" % cena_id
            ok, buf = cv2.imencode(".jpg", img_previa, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                buf.tofile(os.path.join(destino, previa))

        relatar(97, "gravando")
        with trava_do_imovel(imovel):
            tour = carregar_tour(imovel)
            atual = achar_cena(tour, cena_id)
            if not atual:
                raise RuntimeError("A cena foi removida durante a correção.")
            if mini:
                atual["miniatura"] = mini
            if esboco:
                atual["esboco"] = esboco
            if prof:
                atual["profundidade"] = prof
                atual["previa_profundidade"] = previa
            atual["correcao"] = info
            # a metragem sai do mapa de profundidade, que acabou de ser refeito:
            # o numero publicado antes da correcao nao vale mais sem conferencia
            if atual.get("area"):
                atual["area"]["revisar"] = True
            salvar_tour(tour, imovel)
        return {"cena": atual, "correcao": info}

    tid = tarefas.criar(imovel, "correcao", "Corrigindo %s" % cena["nome"])
    tarefas.enfileirar(tid, trabalho)
    return jsonify({"ok": True, "tarefa": tid}), 202


@api.route("/cenas/<cena_id>/fundo", methods=["POST", "DELETE"])
def api_fundo(cena_id):
    """
    Gera (ou remove) a camada de fundo: o que provavelmente esta atras dos moveis.

    Caminhando, o visitante enxerga alem das bordas do que a foto registrou. Ali
    nao ha dado, e a malha esticava a textura. Esta camada da conteudo proprio ao
    vao — CONTEUDO GERADO, nao o imovel — e por isso a cena fica marcada e o
    visualizador avisa na tela.
    """
    tour = carregar_tour()
    cena = achar_cena(tour, cena_id)
    if not cena:
        return jsonify({"ok": False, "erro": "Cena não encontrada."}), 404

    if request.method == "DELETE":
        cena.pop("fundo", None)
        salvar_tour(tour)
        return jsonify({"ok": True})

    if not cena.get("profundidade"):
        return jsonify({"ok": False, "erro":
                        "Gere a profundidade antes: a camada de fundo sai dela."}), 422
    if not fundo.modelo_disponivel():
        return jsonify({"ok": False, "erro":
                        "O modelo de reconstrução não está instalado. Rode "
                        "'python baixar_modelo.py --fundo' uma vez (208 MB)."}), 422

    imovel = g.imovel
    destino = pasta_cenas()

    def trabalho(relatar):
        atual, info = _fazer_fundo(imovel, destino, cena_id, cena, relatar)
        return {"cena": atual, "info": info}

    tid = tarefas.criar(imovel, "fundo", "Camada de fundo de %s" % cena["nome"])
    tarefas.enfileirar(tid, trabalho)
    return jsonify({"ok": True, "tarefa": tid}), 202


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


@api.route("/tarefas/<tid>", methods=["GET"])
def api_tarefa(tid):
    tarefa = tarefas.obter(tid)
    if not tarefa or tarefa["imovel"] != g.imovel:
        return jsonify({"ok": False, "erro": "Tarefa não encontrada."}), 404
    return jsonify({"ok": True, "tarefa": tarefa})


@api.route("/tarefas", methods=["GET"])
def api_tarefas():
    return jsonify({"ok": True, "tarefas": tarefas.listar(g.imovel)})


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


@api.route("/marca-chao", methods=["POST"])
def api_marca_chao():
    """
    Aplica ou remove a marca no chao de todas as cenas 360 do imovel.

    O panorama original fica guardado ao lado: assim da para trocar a logo, mudar
    o tamanho ou desfazer, sem precisar recosturar as fotos.
    """
    dados = request.get_json(silent=True) or {}
    ativo = bool(dados.get("ativo", True))
    raio = float(dados.get("raio") or marca.RAIO_PADRAO)

    tour = carregar_tour()
    pasta = pasta_cenas()
    logo = None
    # sem logotipo o polo e apenas tapado com a cor do piso: o leque de cunhas
    # some do mesmo jeito, e quem ainda nao tem marca nao fica sem saida
    if ativo and tour.get("logo"):
        caminho_logo = os.path.join(pasta, tour["logo"])
        logo = cv2.imdecode(np.fromfile(caminho_logo, dtype=np.uint8),
                            cv2.IMREAD_UNCHANGED)
        if logo is None:
            return jsonify({"ok": False, "erro": "Não consegui abrir a logo."}), 422
        if logo.ndim == 2:
            logo = cv2.cvtColor(logo, cv2.COLOR_GRAY2BGR)

    alteradas, erros = 0, []
    for cena in tour["cenas"]:
        if not cena.get("panorama_completo"):
            continue
        atual = os.path.join(pasta, cena["arquivo"])
        original = os.path.join(pasta, "orig_" + cena["arquivo"])

        try:
            if not ativo:
                if os.path.exists(original):
                    shutil.copyfile(original, atual)
                    os.remove(original)
                    cena.pop("marca_chao", None)
                    cena["miniatura"] = gerar_miniatura(g.imovel, cena["arquivo"])
                    cena["esboco"] = gerar_esboco(g.imovel, cena)
                    alteradas += 1
                continue

            if not os.path.exists(original):
                shutil.copyfile(atual, original)      # guarda o pristino uma vez
            base = cv2.imdecode(np.fromfile(original, dtype=np.uint8), cv2.IMREAD_COLOR)
            saida = marca.aplicar(base, logo, raio)
            ok, buf = cv2.imencode(".jpg", saida, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise marca.ErroMarca("falha ao gravar")
            buf.tofile(atual)
            cena["marca_chao"] = {"raio": raio, "com_logo": logo is not None}
            cena["miniatura"] = gerar_miniatura(g.imovel, cena["arquivo"])
            cena["esboco"] = gerar_esboco(g.imovel, cena)
            alteradas += 1
        except marca.ErroMarca as e:
            erros.append("%s: %s" % (cena["nome"], e))
        except Exception as e:
            traceback.print_exc()
            erros.append("%s: %s" % (cena["nome"], e))

    salvar_tour(tour)
    return jsonify({"ok": True, "alteradas": alteradas, "erros": erros,
                    "ativo": ativo})


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


@api.route("/leads", methods=["GET"])
def api_listar_leads():
    """Usado pelo painel. Fica separado do tour para nao vazar no link publico."""
    return jsonify({"ok": True, "leads": carregar_tour().get("leads_capturados", [])})


@api.route("/leads", methods=["POST"])
def api_registrar_lead():
    """
    Recebe o contato do visitante.

    Guarda o consentimento junto com o dado, e nao so a marca de que houve: a
    LGPD pede que o titular saiba ao que consentiu, e o texto muda com o tempo.
    """
    tour = carregar_tour()
    dados = request.get_json(force=True)
    visitas = tour.get("visitas", [])
    if visitas:
        visitas[-1]["virou_lead"] = True
    registro = {
        "id": uuid.uuid4().hex[:10],
        "nome": (dados.get("nome") or "")[:120],
        "telefone": (dados.get("telefone") or "")[:40],
        "email": (dados.get("email") or "")[:160],
        "quando": dados.get("quando", ""),
        "recebido_em": datetime.now().isoformat(timespec="seconds"),
        "consentimento": (dados.get("consentimento") or "")[:400],
        "atendido": False,
    }
    tour["leads_capturados"].append(registro)
    salvar_tour(tour)

    # O contato ja esta GRAVADO acima. O aviso vem depois e dentro de try por
    # isso: contato que espera o corretor abrir o painel e contato perdido, mas
    # perder o contato por causa do aviso seria trocar um problema por um pior.
    try:
        aviso.avisar(registro, tour.get("titulo", ""),
                     link=request.url_root.rstrip("/") + "/painel/" + g.imovel)
    except Exception:   # o aviso nunca derruba o cadastro do contato
        traceback.print_exc()
    return jsonify({"ok": True})


@api.route("/aviso", methods=["GET"])
def api_aviso():
    """
    Diz se o aviso de contato esta de pe, e o que falta quando nao esta.

    O painel pergunta isto para avisar o corretor ANTES de ele perder um
    contato. Era o unico lugar do sistema que prometia uma coisa e nao
    cumpria — e calado.
    """
    return jsonify({"ok": True, "configurado": aviso.configurado(),
                    "falta": aviso.por_que_nao()})


@api.route("/aviso/testar", methods=["POST"])
def api_aviso_testar():
    """Manda um e-mail de teste e devolve o erro de verdade, se houver."""
    ok, recado = aviso.testar()
    return jsonify({"ok": ok, "recado": recado}), (200 if ok else 400)


def _achar_lead(tour, lead_id):
    for l in tour.get("leads_capturados", []):
        if l.get("id") == lead_id:
            return l
    return None


@api.route("/leads/<lead_id>", methods=["PUT", "DELETE"])
def api_lead(lead_id):
    """
    Marca como atendido, ou apaga.

    Apagar nao e conveniencia: e a LGPD. O titular pode pedir a exclusao dos
    dados dele a qualquer momento, e sem este caminho a unica saida seria editar
    o tour.json na mao.
    """
    tour = carregar_tour()
    lead = _achar_lead(tour, lead_id)
    if not lead:
        return jsonify({"ok": False, "erro": "Contato não encontrado."}), 404

    if request.method == "DELETE":
        tour["leads_capturados"] = [l for l in tour["leads_capturados"]
                                    if l.get("id") != lead_id]
        salvar_tour(tour)
        return jsonify({"ok": True})

    dados = request.get_json(silent=True) or {}
    if "atendido" in dados:
        lead["atendido"] = bool(dados["atendido"])
    salvar_tour(tour)
    return jsonify({"ok": True, "lead": lead})


@api.route("/leads.csv", methods=["GET"])
def api_leads_csv():
    """
    Os contatos em CSV, para entrar no CRM da imobiliaria.

    Sem isto o corretor le os contatos numa janelinha e digita a mao. Com 40
    leads isso deixa de ser viavel — e e onde o sistema perde para uma planilha.
    """
    import csv
    tour = carregar_tour()
    saida = io.StringIO()
    # ponto e virgula: o Excel em portugues abre virgula tudo numa coluna so
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow(["Nome", "Telefone", "E-mail", "Quando", "Atendido",
                       "Consentimento"])
    for l in tour.get("leads_capturados", []):
        escritor.writerow([l.get("nome", ""), l.get("telefone", ""),
                           l.get("email", ""),
                           l.get("quando") or l.get("recebido_em", ""),
                           "sim" if l.get("atendido") else "não",
                           l.get("consentimento", "")])
    nome = "contatos-%s.csv" % re.sub(r"[^a-zA-Z0-9]+", "-",
                                      tour.get("titulo", "imovel"))[:40].strip("-").lower()
    # BOM: sem ele o Excel no Windows estraga acento
    corpo = "﻿" + saida.getvalue()
    return Response(corpo, mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % nome})


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
            # o panorama, o poster de abertura, a miniatura do menu e — quando
            # existir — o mapa de profundidade que permite andar
            f = cena.get("fundo") or {}
            for chave in ("textura", "profundidade"):
                if f.get(chave):
                    caminho = os.path.join(pasta_cenas(), f[chave])
                    if os.path.exists(caminho):
                        z.write(caminho, "scenes/%s" % f[chave])
            for chave in ("arquivo", "profundidade", "miniatura", "esboco"):
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
tarefas.iniciar()


def inicializar():
    """
    Migracoes e faxina que precisam rodar antes de atender a primeira requisicao.

    Ficava dentro do `if __name__ == "__main__"`, e por isso NAO rodava sob um
    servidor WSGI — que importa o modulo em vez de executa-lo. Em producao as
    miniaturas, os esbocos e a adocao de imoveis sem dono simplesmente nao
    aconteciam. Agora os dois caminhos chamam esta funcao.
    """
    migrar_formato_antigo()
    completar_miniaturas()
    completar_esbocos()
    limpar_uploads_orfaos()
    limpar_cenas_orfas()
    if usuarios.completar_ids(PASTA_DADOS):
        adotar_imoveis_sem_dono()
    if not usuarios.ha_usuarios(PASTA_DADOS):
        print("  nenhuma conta ainda: a primeira e criada em /entrar")


if __name__ == "__main__":
    inicializar()
    print("")
    print("  Tour Virtual rodando (servidor de desenvolvimento)")
    print("  Imoveis: http://127.0.0.1:5000/imoveis")
    print("")
    # 127.0.0.1 de proposito, e nao localhost: no Windows o nome resolve para
    # IPv6 (::1) primeiro, o servidor so escuta IPv4, e cada requisicao espera
    # o timeout antes de tentar o IPv4 — medi 2 segundos por chamada.
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
