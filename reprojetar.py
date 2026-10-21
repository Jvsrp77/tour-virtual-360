# -*- coding: utf-8 -*-
"""
Gera o panorama de um ponto a partir do panorama JA REPINTADO de outro.

POR QUE ISTO EXISTE. Repintar cada ponto por conta propria produz comodos que
nao combinam: as cenas 10 e 11 ficam a quatro metros uma da outra, na mesma
sala, e sairam com mobilias diferentes. Dentro de uma cena as seis vistas se
sobrepoem 140 graus e concordam; ENTRE cenas nao ha sobreposicao nenhuma, e
cada uma e pintada sem saber o que a vizinha virou. Andando de um ponto ao
outro, a sala troca de movel.

A SAIDA NAO E PINTAR MELHOR, E PINTAR MENOS. Um comodo so precisa ser
imaginado UMA vez; os outros pontos dele mostram a MESMA sala de outro lugar,
e isso e geometria, nao imaginacao. Com a distancia exata de cada pixel — que
o tracador ja entrega — da para levar a aparencia de um ponto ao outro:

    P = origem_A + direcao_A * distancia_A        (onde a superficie esta)
    direcao_B = (P - origem_B) / |P - origem_B|   (de onde B a ve)

O QUE NAO SE RESOLVE ASSIM, e e honesto dizer: o que A nao enxergou. Atras do
sofa, o lado escondido da parede, o chao que o movel tapava. De B aquilo
aparece, e nao ha pixel nenhum guardado. Esses furos saem marcados, para quem
chama decidir — a camada de fundo deste projeto ja reconstroi oclusao, e e
para la que eles vao.
"""
import cv2
import numpy as np

A_DISP, B_DISP = 1.542, 0.125

# Quanto a distancia vista de A pode divergir da distancia ate P sem que o
# ponto seja considerado escondido. Folga de 12 cm porque as duas medidas vem
# de grades diferentes e a borda de um movel nunca cai no mesmo pixel.
TOLERANCIA = 0.12


def metros(guardado):
    """Desfaz disparidade_exata(): g = (1/m - 0,125)/1,542."""
    return 1.0 / (A_DISP * np.clip(guardado, 0.0, 1.0) + B_DISP)


def direcoes(largura, altura):
    """A convencao do tracador: ph = (0,5 - v) * pi, linha 0 para cima."""
    u = (np.arange(largura, dtype=np.float32) + 0.5) / largura
    v = (np.arange(altura, dtype=np.float32) + 0.5) / altura
    th, ph = np.meshgrid((u * 2.0 - 1.0) * np.pi, (0.5 - v) * np.pi)
    c = np.cos(ph)
    return np.stack([c * np.sin(th), np.sin(ph), c * np.cos(th)],
                    -1).astype(np.float32)


def _pixel_da_direcao(d, largura, altura):
    """Direcao unitaria -> coluna e linha no equirretangular."""
    lon = np.arctan2(d[..., 0], d[..., 2])
    lat = np.arcsin(np.clip(d[..., 1], -1.0, 1.0))
    mx = ((lon / np.pi) * 0.5 + 0.5) * largura - 0.5
    my = (0.5 - lat / np.pi) * altura - 0.5
    return mx.astype(np.float32), my.astype(np.float32)


# Alem desta latitude, a cena de origem nao foi repintada: e calota preenchida
# com cor chapada. Ver repintar.tapar_polos().
CALOTA = 70.0


def levar(pano_a, disp_a, origem_a, disp_b, origem_b, calota=CALOTA):
    """
    Devolve (panorama visto de B, furo), levando a aparencia de A.

    `origem_*` sao (x, y, z) em metros, com y ja somando a altura do olho.
    """
    altura, largura = disp_b.shape[:2]
    oa = np.asarray(origem_a, np.float32)
    ob = np.asarray(origem_b, np.float32)

    db = direcoes(largura, altura)
    p = ob[None, None, :] + db * metros(disp_b)[:, :, None]

    v = p - oa[None, None, :]
    r = np.linalg.norm(v, axis=-1)
    da = v / np.maximum(r, 1e-6)[:, :, None]

    mx, my = _pixel_da_direcao(da, pano_a.shape[1], pano_a.shape[0])
    levado = cv2.remap(pano_a, mx, my, cv2.INTER_CUBIC,
                       borderMode=cv2.BORDER_WRAP)

    # O TESTE DE VISIBILIDADE. O que A via naquela direcao estava a que
    # distancia? Se era mais PERTO do que P, entao havia algo na frente: P
    # esta escondido de A e nao ha cor dele guardada em lugar nenhum.
    visto_de_a = cv2.remap(metros(disp_a), mx, my, cv2.INTER_NEAREST,
                           borderMode=cv2.BORDER_WRAP)
    furo = visto_de_a < (r - TOLERANCIA)
    # ceu e fundo distante saturam em 8 m nos dois lados: ali a comparacao
    # nao significa nada, e marcar furo faria o modelo repintar a vista
    furo &= (r < 7.5)

    # A CALOTA DA FONTE TAMBEM E FURO, e isto nao e detalhe.
    #
    # O zenite e o nadir de A nao foram repintados: sao cor chapada, tapando
    # o que o modelo inventaria se perguntassem. Levados para B, eles nao
    # ficam no teto de B — caem no MEIO da imagem, como manchas cinzas de
    # borda dura. Medido entre as cenas 10 e 12: 1,5% dos pixels de B buscam
    # cor na calota de A, e e exatamente onde as manchas apareceram. Como
    # pixel chapado passa no teste de visibilidade (a distancia bate), ele
    # nao era marcado, e a reconstrucao de oclusao passava reto por ele.
    lat_a = np.degrees(np.arcsin(np.clip(da[..., 1], -1.0, 1.0)))
    furo |= np.abs(lat_a) > calota
    return levado, furo
