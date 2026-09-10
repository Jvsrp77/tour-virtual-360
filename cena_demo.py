# -*- coding: utf-8 -*-
"""
Gera uma cena 360 sintetica para testar o visualizador sem precisar de fotos.
Serve como demonstracao imediata do funcionamento do tour.
"""
import os
import uuid
import cv2
import numpy as np

L, A = 4096, 2048   # equirretangular 2:1


def _gradiente_vertical(img, y0, y1, cor_topo, cor_base):
    for y in range(y0, y1):
        t = (y - y0) / float(max(1, y1 - y0 - 1))
        img[y, :] = [int(cor_topo[i] + (cor_base[i] - cor_topo[i]) * t) for i in range(3)]


def _texto(img, txt, x, y, escala=3.0, cor=(255, 255, 255), esp=6):
    cv2.putText(img, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX, escala,
                (0, 0, 0), esp + 6, cv2.LINE_AA)
    cv2.putText(img, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX, escala, cor, esp, cv2.LINE_AA)


def gerar(pasta_saida, rotulo="AMBIENTE DEMO"):
    img = np.zeros((A, L, 3), dtype=np.uint8)

    horizonte_topo, horizonte_base = int(A * 0.30), int(A * 0.74)

    _gradiente_vertical(img, 0, horizonte_topo, (78, 62, 46), (150, 128, 104))       # teto
    _gradiente_vertical(img, horizonte_base, A, (48, 52, 62), (26, 28, 34))          # chao

    # quatro paredes, cada uma com uma cor, para a rotacao ficar evidente
    paredes = [
        ("NORTE", (176, 158, 138)),
        ("LESTE", (150, 165, 176)),
        ("SUL",   (168, 150, 168)),
        ("OESTE", (150, 172, 158)),
    ]
    largura_parede = L // 4
    for i, (nome, cor) in enumerate(paredes):
        x0 = i * largura_parede
        x1 = x0 + largura_parede
        img[horizonte_topo:horizonte_base, x0:x1] = cor

        # rodape e sanca
        cv2.rectangle(img, (x0, horizonte_base - 34), (x1, horizonte_base),
                      tuple(int(c * 0.72) for c in cor), -1)
        cv2.rectangle(img, (x0, horizonte_topo), (x1, horizonte_topo + 22),
                      tuple(int(c * 0.80) for c in cor), -1)

        # linha divisoria entre paredes (canto do comodo)
        cv2.line(img, (x1, horizonte_topo), (x1, horizonte_base),
                 tuple(int(c * 0.55) for c in cor), 5)

        # "janela" nas paredes pares, "porta" nas impares
        cx = x0 + largura_parede // 2
        if i % 2 == 0:
            jx, jy = 300, 210
            cv2.rectangle(img, (cx - jx, horizonte_topo + 150),
                          (cx + jx, horizonte_topo + 150 + jy * 2), (235, 225, 200), -1)
            cv2.rectangle(img, (cx - jx, horizonte_topo + 150),
                          (cx + jx, horizonte_topo + 150 + jy * 2), (90, 80, 70), 10)
            cv2.line(img, (cx, horizonte_topo + 150), (cx, horizonte_topo + 150 + jy * 2),
                     (90, 80, 70), 8)
        else:
            px, py = 190, 480
            cv2.rectangle(img, (cx - px, horizonte_base - py), (cx + px, horizonte_base),
                          (96, 78, 62), -1)
            cv2.rectangle(img, (cx - px, horizonte_base - py), (cx + px, horizonte_base),
                          (58, 46, 36), 10)
            cv2.circle(img, (cx + px - 50, horizonte_base - py // 2), 16, (210, 190, 120), -1)

        _texto(img, nome, cx - 130, horizonte_topo + 110, 3.0, (60, 50, 44), 8)

    _texto(img, rotulo, L // 2 - 420, int(A * 0.86), 3.4, (235, 235, 235), 8)
    _texto(img, "arraste para girar", L // 2 - 300, int(A * 0.92), 2.0, (170, 170, 175), 5)

    nome_arq = "cena_%s.jpg" % uuid.uuid4().hex[:12]
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise RuntimeError("falha ao gerar cena demo")
    buf.tofile(os.path.join(pasta_saida, nome_arq))
    return nome_arq, L, A
