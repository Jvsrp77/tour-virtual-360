# -*- coding: utf-8 -*-
"""
Devolve as janelas ao panorama repintado.

O PROBLEMA. Na primeira rodada as janelas sumiram: a parede do fundo tinha
tres faixas de vidro e o modelo pintou parede lisa. A causa nao e descuido
dele — e falta de sinal. O guia que ele obedece e PROFUNDIDADE, e numa janela
o vidro esta exatamente a mesma distancia que a parede em volta: o cinza e o
mesmo nos dois. Nao havia como saber que ali era abertura.

O CONSERTO NAO E ADIVINHAR, E CALCULAR. O render guarda a distancia exata de
cada pixel, e a planta guarda cada janela em metros. Com os dois da para
refazer o ponto em que cada raio bateu e perguntar se ele caiu dentro de um
retangulo de janela. Nao se procura "pixel azulado": procura-se geometria.

A BORDA ENTRA ESFUMADA de proposito. Colar o recorte duro deixa um contorno
serrilhado de um pixel em volta de cada vidro — o olho acha a janela colada
antes de achar a janela.
"""
import cv2
import numpy as np

# A mesma convencao do resto do projeto: r = 1 / (1,542 d + 0,125).
A_DISP, B_DISP = 1.542, 0.125

# Igual a tolerancia do _textura() do tracador: a janela e desenhada com
# folga de 8 cm nos lados, e a mascara precisa casar com o que foi desenhado.
FOLGA = 0.08
ESFUMADO = 2.0          # desvio do borrao da borda, em pixels


def metros(guardado):
    """
    Desfaz o que disparidade_exata() fez. Essa funcao grava
    (1/m - 0,125)/1,542, entao a volta e 1/(1,542*g + 0,125) — e NAO a mesma
    formula de novo, que foi o meu erro: aplicar a ida duas vezes devolve um
    numero com cara de distancia que nao e distancia nenhuma.

    O valor guardado satura em [0, 1]: zero quer dizer "8 m ou mais" e um quer
    dizer "0,6 m ou menos". Alem de 8 m nao ha o que reconstruir.
    """
    return 1.0 / (A_DISP * np.clip(guardado, 0.0, 1.0) + B_DISP)


def direcoes(largura, altura):
    """
    O vetor unitario de cada pixel do equirretangular.

    A CONTA E A DO TRACADOR, letra por letra: ph = (0,5 - v) * pi, com a
    linha 0 apontando para CIMA. A convencao oposta — lat = (v - 0,5) * pi —
    tambem existe neste projeto, no profundidade.py e no repintar.py, e la ela
    e inofensiva porque extrair e tecer usam a mesma e a inversao se cancela.
    Aqui ela nao se cancela: este modulo converte pixel em METRO da planta, e
    com o sinal trocado a mascara procura a janela no ponto espelhado. Foi o
    que aconteceu na primeira versao — achou 0,02% do panorama e eu quase
    culpei o modelo por fechar as janelas.
    """
    u = (np.arange(largura, dtype=np.float32) + 0.5) / largura
    v = (np.arange(altura, dtype=np.float32) + 0.5) / altura
    th, ph = np.meshgrid((u * 2.0 - 1.0) * np.pi, (0.5 - v) * np.pi)
    c = np.cos(ph)
    return np.stack([c * np.sin(th), np.sin(ph), c * np.cos(th)],
                    -1).astype(np.float32)


def mascara(planta, ponto, disp, olho):
    """
    Quais pixels do panorama sao janela, dado o ponto de onde se olhou.

    `ponto` e a tupla da planta: (nome, x, z[, andar]). `olho` e a altura do
    olho acima do piso daquele andar.
    """
    altura, largura = disp.shape[:2]
    base = float(ponto[3]) if len(ponto) > 3 else 0.0
    o = np.array([ponto[1], base + olho, ponto[2]], np.float32)
    d = direcoes(largura, altura)
    t = metros(disp)[:, :, None]
    p = o[None, None, :] + d * t          # onde cada raio bateu, em metros

    m = np.zeros((altura, largura), bool)
    for x0, x1, z0, z1, y0, y1 in planta["janelas"]:
        m |= ((p[:, :, 0] >= min(x0, x1) - FOLGA)
              & (p[:, :, 0] <= max(x0, x1) + FOLGA)
              & (p[:, :, 2] >= min(z0, z1) - FOLGA)
              & (p[:, :, 2] <= max(z0, z1) + FOLGA)
              & (p[:, :, 1] >= y0) & (p[:, :, 1] <= y1))
    return m


def colar(repintado, original, m):
    """
    Poe de volta o conteudo da janela, com a borda esfumada.

    Volta o ORIGINAL e nao uma cor chapada porque o original ja tem o ceu
    certo para aquela vista — campo, mar ou cidade, escolhido na planta — e o
    caixilho desenhado no lugar.
    """
    peso = cv2.GaussianBlur(m.astype(np.float32), (0, 0), ESFUMADO)[:, :, None]
    saida = repintado.astype(np.float32) * (1.0 - peso) \
        + original.astype(np.float32) * peso
    return np.clip(saida, 0, 255).astype(np.uint8)
