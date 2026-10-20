# -*- coding: utf-8 -*-
"""
O repintor que chama um modelo de imagem, guiado pela profundidade da cena.

ONDE ISTO SE ENCAIXA. repintar.py quebra o panorama em vistas de perspectiva
e tece de volta; ele nao sabe pintar nada. Aqui mora a unica parte que fala
com fora: recebe (vista, profundidade, descricao) e devolve a vista repintada.

POR QUE CONTROLNET DE PROFUNDIDADE, e nao so "img2img com forca baixa". Forca
baixa preserva a aparencia — que e justamente o que se quer JOGAR FORA, porque
a aparencia atual e um diagrama de caixas. Forca alta inventa outro comodo. O
que se quer manter e a GEOMETRIA, e e isso que o mapa de profundidade carrega:
o modelo fica livre para trocar a caixa marrom por um sofa de verdade, desde
que o sofa ocupe o mesmo volume, na mesma distancia.

E a profundidade daqui e EXATA — vem do tracado de raios, nao de uma rede que
estima. Quem faz isso a partir de foto precisa estimar, e herda o erro.

A CHAVE E DO DONO. Ela sai de variavel de ambiente e nunca e escrita em
arquivo, em log ou em commit. Sem ela, este modulo se recusa a rodar e diz o
que falta — nao ha chave embutida, nem padrao, nem "modo de teste" que mande
dados para fora sem querer.
"""
import base64
import io as _io
import json
import os
import time
import urllib.error
import urllib.request

import cv2
import numpy as np

ESPERA_MAXIMA = 180        # segundos por vista; acima disso algo travou
INTERVALO = 2.0


class SemChave(RuntimeError):
    pass


def _png_base64(img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("falha ao codificar a imagem")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _baixar(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        dados = r.read()
    arr = np.frombuffer(dados, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("o modelo devolveu algo que nao e imagem")
    return img


def _post(url, corpo, cabecalhos):
    req = urllib.request.Request(
        url, data=json.dumps(corpo).encode("utf-8"),
        headers=dict(cabecalhos, **{"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url, cabecalhos):
    req = urllib.request.Request(url, headers=cabecalhos)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def de_replicate(versao=None, forca=0.82):
    """
    Repintor servido pelo Replicate, com ControlNet de profundidade.

    `versao` e o id da versao do modelo no Replicate. Fica como parametro e
    nao fixo no codigo porque esses ids mudam quando o modelo e atualizado, e
    um id vencido daria erro no meio de um lote de 49 cenas.
    """
    chave = os.environ.get("REPLICATE_API_TOKEN")
    versao = versao or os.environ.get("REPINTOR_VERSAO")
    if not chave:
        raise SemChave(
            "falta REPLICATE_API_TOKEN. Crie a conta, pegue o token e rode\n"
            "  setx REPLICATE_API_TOKEN \"seu_token\"\n"
            "numa janela nova. A chave e sua: ela nao entra em arquivo nenhum "
            "deste projeto.")
    if not versao:
        raise SemChave(
            "falta REPINTOR_VERSAO: o id da versao do modelo de repintura no "
            "Replicate (um modelo de img2img com ControlNet de profundidade).")
    cab = {"Authorization": "Token " + chave}

    def repintor(vista, profundidade, descricao):
        corpo = {"version": versao, "input": {
            "image": _png_base64(vista),
            "control_image": _png_base64(profundidade),
            "prompt": descricao,
            "prompt_strength": forca,
        }}
        tarefa = _post("https://api.replicate.com/v1/predictions", corpo, cab)
        limite = time.time() + ESPERA_MAXIMA
        while tarefa.get("status") in ("starting", "processing"):
            if time.time() > limite:
                raise RuntimeError("o modelo passou de %ds sem responder"
                                   % ESPERA_MAXIMA)
            time.sleep(INTERVALO)
            tarefa = _get(tarefa["urls"]["get"], cab)
        if tarefa.get("status") != "succeeded":
            raise RuntimeError("o modelo falhou: %s"
                               % str(tarefa.get("error"))[:200])
        saida = tarefa.get("output")
        url = saida[0] if isinstance(saida, list) else saida
        nova = _baixar(url)
        if nova.shape[:2] != vista.shape[:2]:
            nova = cv2.resize(nova, (vista.shape[1], vista.shape[0]),
                              interpolation=cv2.INTER_CUBIC)
        return nova

    return repintor
