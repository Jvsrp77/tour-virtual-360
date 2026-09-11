# -*- coding: utf-8 -*-
"""
Estima a area do comodo a partir do mapa de profundidade.

Todo anuncio de imovel precisa de metragem, e hoje ela sai de trena ou da
matricula. O tour ja tem a informacao necessaria: a profundidade de cada
direcao, calibrada pela altura da camera.

Como funciona: cada pixel vira um ponto 3D. Os que estao a ~1,5 m abaixo da
camera sao piso. Para cada direcao ao redor, a maior distancia horizontal de
piso e onde o piso encontra a parede. Isso desenha o contorno do comodo visto
de cima, e a area do poligono e a metragem.

A precisao depende da profundidade estimada, que e aproximada. O numero serve
como estimativa e como conferencia do que o anuncio declara, nao como medida
oficial.
"""
import os

os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "disabled")

import cv2
import numpy as np

ALTURA_CAMERA = 1.5        # altura do peito, como manda o guia de captura
TOLERANCIA = 0.28          # quanto um ponto pode fugir do plano do piso, em metros
DIRECOES = 360
RAIO_MAX = 14.0            # alem disso e ruido de profundidade, nao comodo


class ErroArea(Exception):
    pass


def _raio(disparidade):
    return 1.0 / (1.542 * disparidade + 0.125)


def _carregar_disparidade(caminho_png):
    dados = np.fromfile(caminho_png, dtype=np.uint8)
    png = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if png is None:
        raise ErroArea("Não consegui abrir o mapa de profundidade.")
    # 16 bits repartidos: R leva o byte alto, G o baixo
    alto = png[:, :, 2].astype(np.uint32)
    baixo = png[:, :, 1].astype(np.uint32)
    return (((alto << 8) | baixo).astype(np.float32) / 65535.0)


def medir(caminho_png, altura_camera=ALTURA_CAMERA):
    """
    Devolve a area estimada em m2 e os dados que sustentam o numero.
    """
    disp = _carregar_disparidade(caminho_png)
    H, W = disp.shape
    raio = _raio(disp)

    lon = (np.arange(W, dtype=np.float32) / W - 0.5) * 2 * np.pi
    lat = (np.arange(H, dtype=np.float32) / H - 0.5) * np.pi
    lonG, latG = np.meshgrid(lon, lat)

    # calibra pela faixa logo abaixo da camera: ali o piso esta a altura_camera
    faixa = raio[int(H * 0.92):]
    referencia = float(np.median(faixa)) if faixa.size else 0.0
    if referencia <= 0 or not np.isfinite(referencia):
        raise ErroArea("Não consegui calibrar a escala pelo chão.")
    raio = raio * (altura_camera / referencia)

    # +lat aponta para baixo no equirretangular
    altura = raio * np.sin(latG)                 # positivo = abaixo da camera
    horizontal = raio * np.cos(latG)

    piso = (np.abs(altura - altura_camera) < TOLERANCIA) & (latG > 0.05)
    piso &= (horizontal > 0.25) & (horizontal < RAIO_MAX)
    if piso.sum() < 2000:
        raise ErroArea(
            "Não encontrei piso suficiente neste ambiente. Capturas que não "
            "alcançam o chão não permitem estimar a área.")

    # Para cada direcao, caminha do chao para fora e para onde o piso acaba: ali
    # esta a parede. Pegar o ponto mais distante que "parece piso" nao serve —
    # num teste isso deu parede a 12 m e 102 m2 num quarto, porque profundidade
    # estimada erra feio no longe e um ponto solto vira comodo inteiro.
    LAT_INICIO, LAT_FIM = np.radians(72), np.radians(4)
    linhas = np.where((latG[:, 0] <= LAT_INICIO) & (latG[:, 0] >= LAT_FIM))[0]
    linhas = linhas[::-1]                      # do mais proximo do chao para cima
    if linhas.size < 20:
        raise ErroArea("O panorama não cobre o chão o suficiente para medir.")

    piso_col = piso[linhas]
    dist_col = horizontal[linhas]

    limite = np.zeros(W, np.float32)
    for x in range(W):
        coluna = piso_col[:, x]
        if not coluna.any():
            continue
        # comprimento da sequencia de piso que comeca junto ao chao
        fim = 0
        while fim < coluna.size and coluna[fim]:
            fim += 1
        if fim == 0:                            # movel encostado: tenta o 1o trecho
            inicio = int(np.argmax(coluna))
            fim = inicio
            while fim < coluna.size and coluna[fim]:
                fim += 1
            if fim - inicio < 6:
                continue
        limite[x] = dist_col[max(fim - 1, 0), x]

    vistos_col = (limite > 0.3) & (limite < RAIO_MAX)
    if vistos_col.sum() < W * 0.4:
        raise ErroArea(
            "O piso aparece em menos da metade das direções. Provavelmente há "
            "móvel tapando, ou a captura não cobriu a volta inteira.")

    # reamostra as colunas nas direcoes do contorno
    col_ang = (np.arange(W) / W - 0.5) * 2 * np.pi
    alvo = (np.arange(DIRECOES) / DIRECOES - 0.5) * 2 * np.pi
    contorno = np.interp(alvo, col_ang[vistos_col], limite[vistos_col],
                         period=2 * np.pi).astype(np.float32)
    contorno = cv2.GaussianBlur(contorno.reshape(1, -1), (0, 0), sigmaX=4)[0]
    vistos = np.ones(DIRECOES, bool)

    passo = 2 * np.pi / DIRECOES
    metros2 = float(0.5 * np.sum(contorno ** 2) * passo)
    perimetro = float(np.sum(np.sqrt(
        contorno ** 2 + np.roll(contorno, -1) ** 2 -
        2 * contorno * np.roll(contorno, -1) * np.cos(passo))))

    return {
        "area_m2": round(metros2, 1),
        "perimetro_m": round(perimetro, 1),
        "menor_distancia_m": round(float(contorno.min()), 2),
        "maior_distancia_m": round(float(contorno.max()), 2),
        "direcoes_com_piso": int(vistos.sum()),
        "contorno": [round(float(v), 2) for v in contorno],
    }
