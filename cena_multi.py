# -*- coding: utf-8 -*-
"""
Um comodo sintetico fotografado de VARIOS pontos.

Para que serve: mostrar, lado a lado, a diferenca entre um tour de um ponto so e
um tour de varios pontos. De um ponto so, andar obriga o programa a inventar o
que esta atras dos moveis, e a textura escorre. Com varios pontos, o visitante
esta sempre perto de um lugar realmente fotografado, e a imagem fica nitida.

Por que tracado de raios e nao imagem desenhada: os tres panoramas precisam ser
do MESMO comodo, com a paralaxe certa entre eles. Um desenho nao teria isso — o
movel apareceria deslocado de um jeito que nenhuma camera produziria, e o tour
ficaria incoerente justamente naquilo que ele quer demonstrar.

Como os tres saem do mesmo sistema de coordenadas, o norte deles coincide de
graca. Em captura de verdade esse alinhamento e trabalho.

  python cena_multi.py            grava os panoramas em fotos_multi_ponto/
"""
import os

import cv2
import numpy as np

LARGURA, ALTURA = 4096, 2048
OLHO = 1.55                      # altura dos olhos, em metros

# o comodo: 5,0 m x 4,0 m, pe-direito 2,7 m
SALA = (0.0, 0.0, 0.0, 5.0, 2.7, 4.0)      # x0 y0 z0 x1 y1 z1

# Os tres pontos de captura. Ficam a pelo menos 1 m de qualquer parede e fora de
# todo movel: a primeira tentativa pos um ponto a 80 cm da parede e ela engoliu
# metade da vista — fisicamente correto e visualmente inutil, que e exatamente o
# erro que um corretor comete ao fotografar de um canto.
PONTOS = [
    ("Sala sintetica - junto a porta", 1.50, 1.00),
    ("Sala sintetica - ao fundo",      2.50, 2.90),
    ("Sala sintetica - lado direito",  3.50, 1.90),
]

# Moveis como caixas. Existem para CRIAR OCLUSAO: e atras deles que a imagem de
# um ponto so nao tem dado, e e essa falta que o multi-ponto resolve.
MOVEIS = [
    # x0, y0, z0, x1, y1, z1, cor BGR, nome
    (0.15, 0.0, 1.10, 1.05, 0.80, 3.10, (78, 96, 132), "sofa"),
    (1.60, 0.0, 1.55, 2.60, 0.42, 2.45, (58, 82, 118), "mesa de centro"),
    (3.95, 0.0, 0.20, 4.85, 2.15, 1.40, (52, 66, 96), "estante"),
    (2.05, 0.0, 3.55, 3.45, 1.25, 3.92, (64, 88, 120), "aparador"),
    (0.20, 0.0, 0.10, 0.70, 1.30, 0.60, (70, 104, 146), "vaso alto"),
]

PAREDES = ("x0", "x1", "z0", "z1")


def _padrao(face, p, cor):
    """
    Textura por superficie. Nao e enfeite: parede lisa nao da ponto de
    referencia nenhum, nem para quem olha nem para o modelo de profundidade —
    foi medido, 69 pontos contra 4038 numa parede com quinas.
    """
    cor = np.array(cor, dtype=np.float32)
    saida = np.repeat(cor[None, :], p.shape[0], axis=0)

    if face == "chao":
        faixa = np.floor(p[:, 0] / 0.22).astype(np.int32)     # tabua corrida
        saida *= (0.88 + 0.12 * (faixa % 2))[:, None]
        veio = 0.06 * np.sin(p[:, 2] * 37.0) + 0.04 * np.sin(p[:, 0] * 91.0)
        saida *= (1.0 + veio)[:, None]
    elif face == "teto":
        # O teto ocupa um terco da imagem equirretangular. Liso, vira uma mancha
        # pale sem uma referencia sequer — e o modelo de profundidade tambem nao
        # tem o que agarrar ali. Uma luminaria e uma sanca resolvem.
        saida *= 1.06
        cx, cz = 2.5, 2.0
        r = np.hypot(p[:, 0] - cx, p[:, 2] - cz)
        saida[r < 0.34] = np.array([250, 250, 246], dtype=np.float32)
        aro = (r >= 0.34) & (r < 0.42)
        saida[aro] *= 0.72
        borda = ((p[:, 0] < 0.35) | (p[:, 0] > 4.65)
                 | (p[:, 2] < 0.35) | (p[:, 2] > 3.65))
        saida[borda] *= 0.90
    else:
        rodape = p[:, 1] < 0.11
        saida[rodape] *= 0.55
        saida *= (1.0 + 0.03 * np.sin(p[:, 0] * 8.0)
                  + 0.03 * np.sin(p[:, 2] * 8.0))[:, None]
        if face == "z1":                                      # janela ao fundo
            janela = ((p[:, 0] > 1.1) & (p[:, 0] < 3.2)
                      & (p[:, 1] > 0.95) & (p[:, 1] < 2.05))
            saida[janela] = np.array([242, 238, 226], dtype=np.float32)
        if face == "x0":                                      # quadro na lateral
            quadro = ((p[:, 2] > 2.3) & (p[:, 2] < 3.1)
                      & (p[:, 1] > 1.25) & (p[:, 1] < 1.95))
            saida[quadro] = np.array([46, 74, 132], dtype=np.float32)
    return saida


def _direcoes():
    """Direcao de cada pixel da projecao equirretangular."""
    u = (np.arange(LARGURA, dtype=np.float32) + 0.5) / LARGURA
    v = (np.arange(ALTURA, dtype=np.float32) + 0.5) / ALTURA
    theta = (u * 2.0 - 1.0) * np.pi                 # giro, -pi a pi
    phi = (0.5 - v) * np.pi                         # altura, +pi/2 a -pi/2
    th, ph = np.meshgrid(theta, phi)
    cos_ph = np.cos(ph)
    d = np.stack([cos_ph * np.sin(th), np.sin(ph), cos_ph * np.cos(th)], axis=-1)
    return d.reshape(-1, 3).astype(np.float32)


def _sair_da_sala(o, d):
    """Onde o raio encontra a parede, vindo de DENTRO."""
    x0, y0, z0, x1, y1, z1 = SALA
    limites = [(0, x0, "x0"), (0, x1, "x1"), (1, y0, "chao"),
               (1, y1, "teto"), (2, z0, "z0"), (2, z1, "z1")]
    melhor_t = np.full(d.shape[0], np.inf, dtype=np.float32)
    melhor_f = np.zeros(d.shape[0], dtype=np.int32)
    nomes = []
    for i, (eixo, valor, nome) in enumerate(limites):
        nomes.append(nome)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (valor - o[eixo]) / d[:, eixo]
        t = np.where(np.isfinite(t) & (t > 1e-4), t, np.inf)
        troca = t < melhor_t
        melhor_t = np.where(troca, t, melhor_t)
        melhor_f = np.where(troca, i, melhor_f)
    return melhor_t, melhor_f, nomes


def _bater_na_caixa(o, d, caixa):
    """Entrada do raio na caixa, ou infinito. Teste de fatias, o padrao."""
    baixo = np.array(caixa[0:3], dtype=np.float32)
    alto = np.array(caixa[3:6], dtype=np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        ta = (baixo[None, :] - o[None, :]) / d
        tb = (alto[None, :] - o[None, :]) / d
    t1 = np.minimum(ta, tb)
    t2 = np.maximum(ta, tb)
    entra = np.nanmax(np.where(np.isnan(t1), -np.inf, t1), axis=1)
    sai = np.nanmin(np.where(np.isnan(t2), np.inf, t2), axis=1)
    return np.where((sai >= entra) & (entra > 1e-4), entra, np.inf)


def _face_da_caixa(p, caixa):
    """Qual lado da caixa foi atingido, para sombrear diferente."""
    x0, y0, z0, x1, y1, z1 = caixa[0:6]
    dist = np.stack([np.abs(p[:, 0] - x0), np.abs(p[:, 0] - x1),
                     np.abs(p[:, 1] - y1), np.abs(p[:, 2] - z0),
                     np.abs(p[:, 2] - z1)], axis=1)
    return np.argmin(dist, axis=1)


def render(x, z):
    """Panorama equirretangular visto de (x, OLHO, z)."""
    o = np.array([x, OLHO, z], dtype=np.float32)
    d = _direcoes()

    t, face_i, nomes = _sair_da_sala(o, d)
    dono = np.full(d.shape[0], -1, dtype=np.int32)
    for k, movel in enumerate(MOVEIS):
        tm = _bater_na_caixa(o, d, movel)
        perto = tm < t
        t = np.where(perto, tm, t)
        dono = np.where(perto, k, dono)

    ponto = o[None, :] + d * t[:, None]
    cor = np.zeros((d.shape[0], 3), dtype=np.float32)

    for i, nome in enumerate(nomes):
        sel = (dono < 0) & (face_i == i)
        if not sel.any():
            continue
        if nome in PAREDES:
            base = (150, 146, 140)
        elif nome == "chao":
            base = (92, 104, 122)
        else:
            base = (206, 204, 200)
        cor[sel] = _padrao(nome, ponto[sel], base)

    for k, movel in enumerate(MOVEIS):
        sel = dono == k
        if not sel.any():
            continue
        lado = _face_da_caixa(ponto[sel], movel)
        brilho = np.array([0.80, 0.92, 1.12, 0.86, 0.98], dtype=np.float32)[lado]
        cor[sel] = np.array(movel[6], dtype=np.float32)[None, :] * brilho[:, None]

    # luz que cai com a distancia: sem isso o comodo fica chapado e o modelo de
    # profundidade perde a unica pista de escala que a imagem oferece
    queda = 1.0 / (1.0 + 0.055 * np.clip(t, 0, 40) ** 1.35)
    cor *= (0.58 + 0.62 * queda)[:, None]

    img = np.clip(cor, 0, 255).astype(np.uint8).reshape(ALTURA, LARGURA, 3)
    return cv2.GaussianBlur(img, (0, 0), 0.6)      # tira o serrilhado das quinas


def main():
    saida = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "fotos_multi_ponto")
    os.makedirs(saida, exist_ok=True)
    for i, (nome, x, z) in enumerate(PONTOS):
        img = render(x, z)
        caminho = os.path.join(saida, "ponto_%d.jpg" % i)
        # imwrite NAO grava em caminho com acento no Windows, e falha CALADO:
        # devolve False e some com o arquivo. A pasta deste projeto tem "Área"
        # no caminho. O resto do codigo ja usa imencode + tofile por isto.
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise RuntimeError("falha ao codificar %s" % caminho)
        buf.tofile(caminho)
        print("  %-34s (%.1f, %.1f) -> %s" % (nome, x, z,
                                              os.path.basename(caminho)))
    print()
    print("  %d panoramas de %dx%d em %s" % (len(PONTOS), LARGURA, ALTURA, saida))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
