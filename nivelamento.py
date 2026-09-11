# -*- coding: utf-8 -*-
"""
Nivela o horizonte de um panorama equirretangular.

Quem fotografa com o celular na mao quase nunca fica exatamente nivelado. Num
panorama torto, o chao "escorrega" quando o visitante gira — desconforto fisico
que aparece acima de uns 2 graus de inclinacao.

Como se descobre onde e "para baixo": pelas verticais da propria cena. Batente
de porta, quina de parede e lateral de armario sao verticais reais. Cada uma
dessas linhas, vista da camera, define um plano que passa pelo centro optico; a
direcao vertical do mundo esta contida em todos esses planos ao mesmo tempo.
Achar essa direcao e achar a gravidade.

Profundidade monocular tambem daria uma estimativa, mas e relativa e imprecisa:
num teste o ajuste de plano no piso deu planaridade 0,22, ruim demais para
confiar. As verticais sao geometria direta.
"""
import os

os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "disabled")

import cv2
import numpy as np

LADO_VISTA = 512
FOV_VISTA = 90.0
VISTAS = 8
TOLERANCIA_VERTICAL = 32.0     # graus: quanto a linha pode fugir da vertical na vista
MIN_SEGMENTOS = 12
LIMITE_INLIER = np.radians(2.5)


class ErroNivelamento(Exception):
    pass


def _rotacao_yaw(yaw_graus):
    y = np.radians(yaw_graus)
    return np.array([[np.cos(y), 0, np.sin(y)],
                     [0, 1, 0],
                     [-np.sin(y), 0, np.cos(y)]], dtype=np.float64)


def _vista(equi, yaw):
    He, We = equi.shape[:2]
    f = (LADO_VISTA / 2.0) / np.tan(np.radians(FOV_VISTA) / 2.0)
    eixo = np.arange(LADO_VISTA, dtype=np.float32) - LADO_VISTA / 2.0
    u, v = np.meshgrid(eixo, eixo)
    d = np.stack([u, v, np.full_like(u, f)], -1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    d = d @ _rotacao_yaw(yaw).T
    lon = np.arctan2(d[..., 0], d[..., 2])
    lat = np.arcsin(np.clip(d[..., 1], -1, 1))
    mx = ((lon / (2 * np.pi)) + 0.5) * We
    my = ((lat / np.pi) + 0.5) * He
    return cv2.remap(equi, mx.astype(np.float32), my.astype(np.float32),
                     cv2.INTER_AREA, borderMode=cv2.BORDER_WRAP)


def _normais_das_verticais(equi):
    """
    Devolve a normal do plano de cada segmento quase vertical encontrado.
    A direcao vertical do mundo e perpendicular a todas elas.
    """
    detector = cv2.createLineSegmentDetector()
    f = (LADO_VISTA / 2.0) / np.tan(np.radians(FOV_VISTA) / 2.0)
    centro = LADO_VISTA / 2.0
    normais = []

    for i in range(VISTAS):
        yaw = i * (360.0 / VISTAS)
        cinza = cv2.cvtColor(_vista(equi, yaw), cv2.COLOR_BGR2GRAY)
        linhas = detector.detect(cinza)[0]
        if linhas is None:
            continue
        R = _rotacao_yaw(yaw)

        for l in linhas.reshape(-1, 4):
            x1, y1, x2, y2 = l
            dx, dy = x2 - x1, y2 - y1
            comprimento = float(np.hypot(dx, dy))
            if comprimento < LADO_VISTA * 0.12:
                continue                       # curta demais: costuma ser textura
            angulo = abs(np.degrees(np.arctan2(abs(dx), abs(dy))))
            if angulo > TOLERANCIA_VERTICAL:
                continue                       # nao parece vertical nesta vista

            a = np.array([x1 - centro, y1 - centro, f])
            b = np.array([x2 - centro, y2 - centro, f])
            a, b = R @ a, R @ b
            n = np.cross(a, b)
            norma = np.linalg.norm(n)
            if norma < 1e-9:
                continue
            # segmentos longos pesam mais: sao bordas de verdade, nao ruido
            normais.append((n / norma, comprimento))
    return normais


def _direcao_vertical(normais):
    """RANSAC: procura a direcao perpendicular ao maior numero de normais."""
    if len(normais) < MIN_SEGMENTOS:
        raise ErroNivelamento(
            "Não encontrei linhas verticais suficientes nesta cena (%d). Paredes "
            "lisas e sem quinas não dão referência de prumo." % len(normais))

    vetores = np.array([n for n, _ in normais])
    pesos = np.array([c for _, c in normais])
    aleatorio = np.random.default_rng(12345)
    melhor, melhor_peso = None, -1.0

    for _ in range(600):
        i, j = aleatorio.integers(0, len(vetores), 2)
        if i == j:
            continue
        v = np.cross(vetores[i], vetores[j])
        norma = np.linalg.norm(v)
        if norma < 1e-6:
            continue
        v = v / norma
        if v[1] < 0:                 # +y aponta para baixo no equirretangular
            v = -v
        # a camera nao esta de cabeca para baixo: descarta solucoes absurdas
        if np.degrees(np.arccos(np.clip(v[1], -1, 1))) > 40:
            continue
        erro = np.abs(vetores @ v)
        dentro = erro < LIMITE_INLIER
        peso = float(pesos[dentro].sum())
        if peso > melhor_peso:
            melhor_peso, melhor = peso, (v, dentro)

    if melhor is None:
        raise ErroNivelamento("As linhas encontradas não concordam com uma direção de prumo.")

    v, dentro = melhor
    # refina com todos os inliers, ponderando pelo comprimento
    A = vetores[dentro] * pesos[dentro, None]
    _, _, Vt = np.linalg.svd(A, full_matrices=False)
    v = Vt[-1] / np.linalg.norm(Vt[-1])
    if v[1] < 0:
        v = -v
    return v, int(dentro.sum()), len(vetores)


def _rotacao_entre(origem, destino):
    origem = origem / np.linalg.norm(origem)
    destino = destino / np.linalg.norm(destino)
    eixo = np.cross(origem, destino)
    seno = np.linalg.norm(eixo)
    cosseno = float(np.dot(origem, destino))
    if seno < 1e-9:
        return np.eye(3) if cosseno > 0 else -np.eye(3)
    eixo = eixo / seno
    K = np.array([[0, -eixo[2], eixo[1]],
                  [eixo[2], 0, -eixo[0]],
                  [-eixo[1], eixo[0], 0]])
    return np.eye(3) + seno * K + (1 - cosseno) * (K @ K)


def _girar_panorama(equi, R):
    """Reamostra o panorama como se a camera tivesse sido rotacionada por R."""
    H, W = equi.shape[:2]
    lon = (np.arange(W, dtype=np.float32) / W - 0.5) * 2 * np.pi
    lat = (np.arange(H, dtype=np.float32) / H - 0.5) * np.pi
    lonG, latG = np.meshgrid(lon, lat)
    d = np.stack([np.cos(latG) * np.sin(lonG),
                  np.sin(latG),
                  np.cos(latG) * np.cos(lonG)], -1)
    d = d @ R                                   # R^T aplicado a direita
    lon2 = np.arctan2(d[..., 0], d[..., 2])
    lat2 = np.arcsin(np.clip(d[..., 1], -1, 1))
    mx = ((lon2 / (2 * np.pi)) + 0.5) * W
    my = ((lat2 / np.pi) + 0.5) * H
    return cv2.remap(equi, mx.astype(np.float32), my.astype(np.float32),
                     cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)


def medir(equi):
    """Quantos graus o panorama esta fora do prumo, sem alterar nada."""
    v, dentro, total = _direcao_vertical(_normais_das_verticais(equi))
    graus = float(np.degrees(np.arccos(np.clip(v[1], -1, 1))))
    return {"inclinacao": round(graus, 2), "linhas_usadas": dentro,
            "linhas_encontradas": total, "direcao": v}


def nivelar(equi, minimo=0.8):
    """
    Endireita o panorama. Devolve (imagem, informacao).
    Abaixo de `minimo` graus nao mexe: reamostrar de graca so perderia nitidez.
    """
    info = medir(equi)
    if info["inclinacao"] < minimo:
        info["aplicado"] = False
        return equi, info
    R = _rotacao_entre(info["direcao"], np.array([0.0, 1.0, 0.0]))
    info["aplicado"] = True
    return _girar_panorama(equi, R), info
