# -*- coding: utf-8 -*-
"""
O repintor que chama um modelo de imagem no Replicate.

ONDE ISTO SE ENCAIXA. repintar.py quebra o panorama em vistas de perspectiva e
tece de volta; ele nao sabe pintar nada. Aqui mora a unica parte que fala com
fora: recebe (vista, guia de profundidade, descricao) e devolve a vista
repintada.

DOIS FEITIOS DE MODELO, e a diferenca importa para o resultado:

  "interior"      manda so a VISTA e o texto. O modelo estima a profundidade
                  dele (os de interior costumam usar DPT-Large). Mais simples,
                  e joga fora a nossa melhor carta.

  "profundidade"  manda o NOSSO guia como imagem de controle. A profundidade
                  daqui e exata — sai do tracado de raios, nao de uma rede que
                  estima — entao o layout que o modelo obedece e a planta de
                  verdade, e nao um palpite sobre um desenho de caixas.

DOIS JEITOS DE ENDERECAR, porque o Replicate tem dois:

  REPINTOR_MODELO = "dono/nome"   modelo oficial, chamado pelo NOME. Preferir
                                  este: nome nao vence, id de versao vence.
  REPINTOR_VERSAO = "<id>"        modelo da comunidade, preso a uma versao.

A CHAVE E DO DONO. Sai de variavel de ambiente e nunca e escrita em arquivo,
em log ou em commit. Sem ela este modulo se recusa a rodar e diz o que falta —
nao ha chave embutida, nem padrao, nem "modo de teste" que mande dados para
fora sem querer.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

import cv2
import numpy as np

ESPERA_MAXIMA = 300        # segundos por vista; acima disso algo travou
INTERVALO = 2.0
API = "https://api.replicate.com/v1"


class SemChave(RuntimeError):
    pass


def _png_base64(img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("falha ao codificar a imagem")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _pedir(url, cabecalhos, corpo=None):
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    cab = dict(cabecalhos)
    if dados is not None:
        cab["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=dados, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        # O corpo do erro diz O QUE esta errado (campo que nao existe, modelo
        # que nao existe, credito acabado). Engolir isso e deixar o dono com
        # "HTTP 422" e nada mais.
        detalhe = ""
        try:
            detalhe = erro.read().decode("utf-8")[:400]
        except Exception:
            pass
        raise RuntimeError("Replicate respondeu %s: %s" % (erro.code, detalhe))


def _baixar(url):
    with urllib.request.urlopen(url, timeout=180) as r:
        dados = r.read()
    img = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("o modelo devolveu algo que nao e imagem")
    return img


def _config():
    chave = os.environ.get("REPLICATE_API_TOKEN")
    if not chave:
        raise SemChave(
            "falta REPLICATE_API_TOKEN.\n"
            "  1) pegue o token em replicate.com/account/api-tokens\n"
            '  2) rode  setx REPLICATE_API_TOKEN "seu_token"\n'
            "  3) abra uma janela NOVA do terminal (setx so vale nas novas)\n"
            "A chave e sua: ela nao entra em arquivo nenhum deste projeto.")
    modelo = os.environ.get("REPINTOR_MODELO")
    versao = os.environ.get("REPINTOR_VERSAO")
    if not modelo and not versao:
        raise SemChave(
            "falta dizer QUAL modelo. Escolha um:\n"
            '  setx REPINTOR_MODELO "black-forest-labs/flux-depth-dev"   '
            "(oficial, obedece a profundidade)\n"
            "  setx REPINTOR_VERSAO \"<id>\"   (modelo da comunidade)")
    feitio = os.environ.get("REPINTOR_FEITIO", "profundidade")
    if feitio not in ("profundidade", "interior"):
        raise SemChave("REPINTOR_FEITIO deve ser 'profundidade' ou 'interior'")
    return chave, modelo, versao, feitio


def de_replicate(forca=None):
    chave, modelo, versao, feitio = _config()
    cab = {"Authorization": "Bearer " + chave}
    url = ("%s/models/%s/predictions" % (API, modelo) if modelo
           else "%s/predictions" % API)

    def repintor(vista, guia, descricao):
        entrada = {"prompt": descricao or
                   "interior fotografico, moveis reais, luz natural"}
        if feitio == "profundidade":
            entrada["control_image"] = _png_base64(guia)
        else:
            entrada["image"] = _png_base64(vista)
        if forca is not None:
            entrada["prompt_strength"] = forca

        corpo = {"input": entrada}
        if versao and not modelo:
            corpo["version"] = versao

        tarefa = _pedir(url, cab, corpo)
        limite = time.time() + ESPERA_MAXIMA
        while tarefa.get("status") in ("starting", "processing"):
            if time.time() > limite:
                raise RuntimeError("o modelo passou de %ds sem responder"
                                   % ESPERA_MAXIMA)
            time.sleep(INTERVALO)
            tarefa = _pedir(tarefa["urls"]["get"], cab)
        if tarefa.get("status") != "succeeded":
            raise RuntimeError("o modelo falhou: %s"
                               % str(tarefa.get("error"))[:300])

        saida = tarefa.get("output")
        endereco = saida[0] if isinstance(saida, list) else saida
        if not endereco:
            raise RuntimeError("o modelo terminou sem devolver imagem")
        nova = _baixar(endereco)
        if nova.shape[:2] != vista.shape[:2]:
            nova = cv2.resize(nova, (vista.shape[1], vista.shape[0]),
                              interpolation=cv2.INTER_CUBIC)
        return nova

    return repintor
