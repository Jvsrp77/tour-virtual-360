# -*- coding: utf-8 -*-
"""
Marca da imobiliaria no chao do panorama (o "nadir patch").

Toda foto 360 profissional cobre o ponto exatamente abaixo da camera. Ali fica o
tripe, o pe de quem fotografou, ou — no nosso caso — o preenchimento sintetico
de uma captura em uma fileira so, que nao alcanca o chao.

Medido no quarto de teste: cerca de 40% da altura do equirretangular e
preenchimento, sem nitidez nenhuma. A marca cobre a parte pior disso e ainda
reforca a marca de quem publicou.

Nao inventa conteudo: substitui area sem informacao por um logotipo declarado.
Diferente de gerar piso com IA, que afirmaria algo falso sobre o imovel.
"""
import os

os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "disabled")

import cv2
import numpy as np

RAIO_PADRAO = 32.0        # graus a partir do polo inferior
SUAVIDADE = 0.22          # fracao do raio usada para dissolver a borda


class ErroMarca(Exception):
    pass


def _quadrado_do_logo(logo, lado):
    """Encaixa o logotipo num quadrado transparente, sem distorcer a proporcao."""
    if logo.shape[2] == 3:
        logo = cv2.cvtColor(logo, cv2.COLOR_BGR2BGRA)

    escala = min(lado / logo.shape[1], lado / logo.shape[0]) * 0.72
    novo = (max(1, int(logo.shape[1] * escala)), max(1, int(logo.shape[0] * escala)))
    logo = cv2.resize(logo, novo, interpolation=cv2.INTER_AREA)

    tela = np.zeros((lado, lado, 4), np.uint8)
    y = (lado - logo.shape[0]) // 2
    x = (lado - logo.shape[1]) // 2
    tela[y:y + logo.shape[0], x:x + logo.shape[1]] = logo
    return tela


def cor_do_piso(panorama, raio):
    """
    Cor do piso no anel em volta do polo, ignorando movel escuro e sombra.

    A mediana crua do anel puxa para cinza: ali entram pe de cama, sombra e
    rodape. So a metade mais clara do anel e piso de fato — medido no quarto de
    teste, isso troca um disco cinza chapado por um disco da cor do piso.
    """
    H, W = panorama.shape[:2]
    lat = (np.arange(H, dtype=np.float32) / H - 0.5) * np.pi
    latG = np.repeat(lat[:, None], W, 1)
    anel = (latG > (np.pi / 2 - raio * 1.45)) & (latG <= (np.pi / 2 - raio * 0.95))
    px = panorama[anel].reshape(-1, 3)
    if px.shape[0] < 100:
        return np.array([60, 60, 60], np.float32)
    lum = px.astype(np.float32) @ np.array([0.114, 0.587, 0.299], np.float32)
    return np.median(px[lum >= np.percentile(lum, 60)], axis=0).astype(np.float32)


def tampar(panorama, raio_graus=46.0, suavidade=0.45):
    """
    Tapa o polo inferior com a cor do proprio piso.

    Uma captura em uma fileira nao alcanca o chao sob a camera, e o preenchimento
    por esticamento deixa ali um leque de cunhas escuras — o "degrade preto" que
    aparece ao olhar para baixo. Esta funcao troca o leque por uma superficie lisa
    da cor certa: nao inventa detalhe, so remove artefato.

    Nao recupera o piso. Para isso sao tres fileiras na captura, ou a marca da
    imobiliaria cobrindo a area. Medido no quarto de teste, a energia de cunha cai
    de 34,7 para 9,9 (-72%).
    """
    H, W = panorama.shape[:2]
    if abs(W / float(H) - 2.0) > 0.1:
        raise ErroMarca("Só vale para panorama 360 completo (2:1).")
    raio = np.radians(max(20.0, min(70.0, float(raio_graus))))
    cor = cor_do_piso(panorama, raio)

    lat = (np.arange(H, dtype=np.float32) / H - 0.5) * np.pi
    latG = np.repeat(lat[:, None], W, 1)
    t = np.clip((latG - (np.pi / 2 - raio)) / raio, 0, 1)
    peso = np.clip(t / suavidade, 0, 1)
    peso = (peso * peso * (3 - 2 * peso))[..., None]     # dissolve nas duas pontas
    saida = panorama.astype(np.float32) * (1 - peso) + cor.reshape(1, 1, 3) * peso
    return np.clip(saida, 0, 255).astype(np.uint8)


def aplicar(panorama, logo, raio_graus=RAIO_PADRAO, cor_fundo=(28, 30, 34)):
    """
    Devolve o panorama com um disco no polo inferior.

    Sem logotipo (`logo=None`) tapa o polo com a cor do piso: serve para quem
    ainda nao tem marca, e o leque de cunhas some do mesmo jeito.

    O disco e desenhado direto no equirretangular: cada pixel da faixa de baixo
    vira coordenada polar no chao — a distancia ao polo virou raio, a longitude
    virou angulo. E o inverso da projecao que o visualizador faz.
    """
    if logo is None:
        return tampar(panorama, raio_graus)
    H, W = panorama.shape[:2]
    if abs(W / float(H) - 2.0) > 0.1:
        raise ErroMarca("A marca no chão só vale para panorama 360 completo (2:1).")

    raio = np.radians(max(8.0, min(60.0, float(raio_graus))))
    lat_inicio = np.pi / 2 - raio
    linha_inicio = int((lat_inicio / np.pi + 0.5) * H)
    altura_faixa = H - linha_inicio
    if altura_faixa < 8:
        return panorama

    lado = max(64, int(W * raio / np.pi))
    arte = _quadrado_do_logo(logo, lado)

    lon = (np.arange(W, dtype=np.float32) / W - 0.5) * 2 * np.pi
    lat = (np.arange(linha_inicio, H, dtype=np.float32) / H - 0.5) * np.pi
    lonG, latG = np.meshgrid(lon, lat)

    # t: 0 no polo, 1 na borda do disco
    t = (np.pi / 2 - latG) / raio
    u = (0.5 + 0.5 * t * np.sin(lonG)) * (lado - 1)
    v = (0.5 - 0.5 * t * np.cos(lonG)) * (lado - 1)

    amostra = cv2.remap(arte, u.astype(np.float32), v.astype(np.float32),
                        cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                        borderValue=(0, 0, 0, 0))

    # fundo do disco, para nao deixar o borrao aparecendo em volta do logotipo
    fundo = np.zeros((altura_faixa, W, 3), np.uint8)
    fundo[:] = cor_fundo

    alfa_logo = amostra[:, :, 3:4].astype(np.float32) / 255.0
    arte_bgr = amostra[:, :, :3].astype(np.float32)
    disco = fundo * (1 - alfa_logo) + arte_bgr * alfa_logo

    # dissolve a borda externa do disco para nao virar um circulo recortado
    borda = np.clip((1.0 - t) / SUAVIDADE, 0.0, 1.0)[..., None]
    faixa = panorama[linha_inicio:].astype(np.float32)
    panorama = panorama.copy()
    panorama[linha_inicio:] = (faixa * (1 - borda) + disco * borda).astype(np.uint8)
    return panorama
