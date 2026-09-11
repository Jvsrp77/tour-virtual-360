# -*- coding: utf-8 -*-
"""
Gera um mapa de profundidade equirretangular a partir de um panorama 360.

O modelo de profundidade so entende foto em perspectiva, entao o panorama e
recortado em varias vistas, cada uma passa pelo modelo, e os resultados voltam
para o equirretangular. Como profundidade monocular e relativa (cada vista tem
sua propria escala), as vistas sao alinhadas entre si pelas regioes que se
sobrepoem antes de serem fundidas.

O resultado permite ao visitante ANDAR pelo ambiente: com raio por pixel, o
panorama deixa de ser uma casca lisa e vira geometria, produzindo paralaxe.
"""
import os

os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "disabled")

import cv2
import numpy as np

MODELO = None
SESSAO = None

LADO_VISTA = 518          # multiplo de 14, exigencia do modelo
FOV_VISTA = 110.0         # >90 de proposito: gera sobreposicao para o alinhamento
MEDIA = np.array([0.485, 0.456, 0.406], np.float32)
DESVIO = np.array([0.229, 0.224, 0.225], np.float32)

# seis direcoes cobrindo a esfera (yaw, pitch)
DIRECOES = [(0, 0), (90, 0), (180, 0), (270, 0), (0, -90), (0, 90)]


class ErroProfundidade(Exception):
    pass


def caminho_modelo():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "modelos", "depth.onnx")


def modelo_disponivel():
    return os.path.exists(caminho_modelo())


def _sessao():
    global SESSAO
    if SESSAO is None:
        if not modelo_disponivel():
            raise ErroProfundidade(
                "O modelo de profundidade não está instalado. Rode "
                "'python baixar_modelo.py' uma vez para baixá-lo (94 MB).")
        import onnxruntime as ort
        provedores = ort.get_available_providers()
        preferidos = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider")
                      if p in provedores]
        SESSAO = ort.InferenceSession(caminho_modelo(), providers=preferidos)
    return SESSAO


def _rotacao(yaw_g, pitch_g):
    y, p = np.radians(yaw_g), np.radians(pitch_g)
    Rx = np.array([[1, 0, 0], [0, np.cos(p), -np.sin(p)], [0, np.sin(p), np.cos(p)]])
    Ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    return Ry @ Rx


def _recortar_vista(equi, yaw, pitch):
    """Projeta uma janela em perspectiva do panorama, como se fosse uma foto."""
    He, We = equi.shape[:2]
    f = (LADO_VISTA / 2.0) / np.tan(np.radians(FOV_VISTA) / 2.0)
    eixo = np.arange(LADO_VISTA, dtype=np.float32) - LADO_VISTA / 2.0
    u, v = np.meshgrid(eixo, eixo)
    d = np.stack([u, v, np.full_like(u, f)], -1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    d = d @ _rotacao(yaw, pitch).T

    lon = np.arctan2(d[..., 0], d[..., 2])
    lat = np.arcsin(np.clip(d[..., 1], -1, 1))
    mx = ((lon / (2 * np.pi)) + 0.5) * We
    my = ((lat / np.pi) + 0.5) * He
    return cv2.remap(equi, mx.astype(np.float32), my.astype(np.float32),
                     cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP), f


def _inferir(face):
    x = cv2.cvtColor(face, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    x = ((x - MEDIA) / DESVIO).transpose(2, 0, 1)[None]
    saida = _sessao().run(None, {"pixel_values": x})[0][0]
    if saida.shape[:2] != face.shape[:2]:
        saida = cv2.resize(saida, (face.shape[1], face.shape[0]), cv2.INTER_LINEAR)
    return saida.astype(np.float32)      # disparidade: maior = mais perto


def _direcoes_equirretangulares(largura, altura):
    lon = (np.arange(largura, dtype=np.float32) / largura - 0.5) * 2 * np.pi
    lat = (np.arange(altura, dtype=np.float32) / altura - 0.5) * np.pi
    lon, lat = np.meshgrid(lon, lat)
    return np.stack([np.cos(lat) * np.sin(lon),
                     np.sin(lat),
                     np.cos(lat) * np.cos(lon)], -1)


def gerar(caminho_panorama, largura_saida=1024, relatar=None):
    """
    Devolve (disparidade, previa_colorida) no tamanho largura_saida x largura_saida/2.
    A disparidade vem normalizada em 0..1, onde 1 e o ponto mais proximo.
    """
    aviso = relatar or (lambda p, e: None)
    aviso(8, "abrindo o panorama")
    dados = np.fromfile(caminho_panorama, dtype=np.uint8)
    equi = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if equi is None:
        raise ErroProfundidade("Não consegui abrir o panorama.")

    W, H = int(largura_saida), int(largura_saida) // 2
    dirs = _direcoes_equirretangulares(W, H)

    acumulado = np.zeros((H, W), np.float32)
    pesos = np.zeros((H, W), np.float32)

    for indice, (yaw, pitch) in enumerate(DIRECOES):
        aviso(15 + indice * 12, "analisando vista %d de %d" % (indice + 1, len(DIRECOES)))
        face, f = _recortar_vista(equi, yaw, pitch)
        disp = _inferir(face)

        # projeta cada direcao do equirretangular na camera desta vista
        p = dirs @ _rotacao(yaw, pitch)          # equivale a R^T aplicado a direita
        frente = p[..., 2] > 1e-6
        with np.errstate(divide="ignore", invalid="ignore"):
            u = f * p[..., 0] / p[..., 2] + LADO_VISTA / 2.0
            v = f * p[..., 1] / p[..., 2] + LADO_VISTA / 2.0

        dentro = (frente & (u >= 1) & (u < LADO_VISTA - 1)
                        & (v >= 1) & (v < LADO_VISTA - 1))
        if not dentro.any():
            continue

        amostra = cv2.remap(disp, np.where(dentro, u, 0).astype(np.float32),
                            np.where(dentro, v, 0).astype(np.float32),
                            cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

        # peso cai para as bordas da vista: o centro e mais confiavel
        centro = np.clip(p[..., 2], 0, 1)
        peso = np.where(dentro, centro ** 3, 0).astype(np.float32)

        if pesos.max() > 0:
            # alinha a escala desta vista com o que ja foi acumulado, usando a
            # sobreposicao. Sem isso cada vista traz sua propria escala arbitraria
            # e o resultado fica em degraus.
            comum = (peso > 0.05) & (pesos > 0.05)
            if comum.sum() > 500:
                a = amostra[comum]
                b = (acumulado / np.maximum(pesos, 1e-6))[comum]
                A = np.stack([a, np.ones_like(a)], 1)
                coef, *_ = np.linalg.lstsq(A, b, rcond=None)
                amostra = amostra * coef[0] + coef[1]

        acumulado += amostra * peso
        pesos += peso

    aviso(90, "juntando as vistas")
    disparidade = acumulado / np.maximum(pesos, 1e-6)
    disparidade = cv2.GaussianBlur(disparidade, (0, 0), 1.6)

    # normaliza descartando extremos, que costumam ser ruido de borda
    lo, hi = np.percentile(disparidade, [2, 98])
    disparidade = np.clip((disparidade - lo) / max(hi - lo, 1e-6), 0, 1)

    previa = cv2.applyColorMap((disparidade * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    return disparidade.astype(np.float32), previa


def salvar(disparidade, caminho_png):
    """
    Grava a profundidade num PNG comum, com os 16 bits repartidos em dois canais:
    R leva o byte alto e G o byte baixo.

    O navegador le PNG por canvas, que entrega 8 bits por canal — um PNG de 16 bits
    seria truncado na leitura e a profundidade sairia em degraus. Repartindo em dois
    canais, o JavaScript remonta o valor exato com (R << 8) | G.
    """
    valores = (np.clip(disparidade, 0, 1) * 65535).astype(np.uint32)
    alto = (valores >> 8).astype(np.uint8)
    baixo = (valores & 0xFF).astype(np.uint8)
    imagem = np.stack([np.zeros_like(alto), baixo, alto], axis=-1)   # BGR
    ok, buf = cv2.imencode(".png", imagem)
    if not ok:
        raise ErroProfundidade("Falha ao gravar o mapa de profundidade.")
    buf.tofile(caminho_png)
