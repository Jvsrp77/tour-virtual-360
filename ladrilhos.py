# -*- coding: utf-8 -*-
"""
Corta o panorama em LADRILHOS, para o visor baixar so o que esta na tela.

POR QUE EXISTE. O tracador entrega 8192x4096 e o publicar.py reduzia para 4096
antes de publicar, com um raciocinio que parecia certo: 8k inteiro sao 1,4 MB
por cena, e 87 cenas dariam 120 MB — inviavel em 4G. A conclusao e que estava
errada, porque existe um meio-termo: ninguem olha o panorama inteiro de uma
vez. Num campo de 100 graus, 72% da imagem esta fora da tela sempre.

Com ladrilhos o visor baixa so o pedaco visivel. Fica mais nitido E mais leve
ao mesmo tempo — o oposto da troca que o comentario antigo assumia:

    antes:  4096 de largura, 0,4 MB de cara, ampliada 1,7x numa tela de 1920
    agora:  8192 de largura, ~60 KB de cara, nativa

O formato e o do Pannellum, que ja estava embarcado e nunca foi usado: seis
faces de cubo, cada uma numa piramide de niveis, com os nomes f, r, b, l, u, d
que o proprio visor monta em `path`.

O EQUIRRETANGULAR CONTINUA SENDO GRAVADO. A caminhada do andar.html projeta a
foto numa malha e precisa dela inteira; os ladrilhos servem ao tour 360.
"""
import math
import os

import cv2
import numpy as np

# As seis faces, com o vetor que aponta para o centro de cada uma e os dois
# vetores que varrem a face (direita e baixo, na imagem).
#
# Convencao: y para cima, e o centro do equirretangular olhando para +z — a
# mesma do tracador e da trena. Conferida contra o panorama, nao deduzida: um
# sinal trocado aqui nao quebra nada, so espelha o imovel.
FACES = {
    "f": ((0, 0, 1), (1, 0, 0), (0, -1, 0)),
    "r": ((1, 0, 0), (0, 0, -1), (0, -1, 0)),
    "b": ((0, 0, -1), (-1, 0, 0), (0, -1, 0)),
    "l": ((-1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "u": ((0, 1, 0), (1, 0, 0), (0, 0, 1)),
    "d": ((0, -1, 0), (1, 0, 0), (0, 0, -1)),
}

LADO_DO_LADRILHO = 512
QUALIDADE = 88


def lado_do_cubo(largura_equirect):
    """
    Quantos pixels tem a aresta do cubo que preserva o detalhe do equirretangular.

    No equador, a largura inteira cobre 360 graus; uma face de cubo cobre 90.
    Manter a mesma densidade de pixel pede largura/4 — mas a projecao estica as
    bordas da face, e quem manda e o centro: largura/pi. Para 8192 da 2608.

    Multiplo de 8 para os niveis da piramide fecharem sem sobra de meio pixel.
    """
    return 8 * int(largura_equirect / math.pi / 8)


def _mapa_da_face(face, lado, alt_eq, larg_eq):
    """Para cada pixel da face, de onde ele vem no equirretangular."""
    centro, direita, baixo = (np.array(v, np.float32) for v in FACES[face])
    t = (np.arange(lado, dtype=np.float32) + 0.5) * 2.0 / lado - 1.0
    a = t[None, :, None]          # varre colunas
    b = t[:, None, None]          # varre linhas
    d = centro + a * direita + b * baixo

    x, y, z = d[..., 0], d[..., 1], d[..., 2]
    lon = np.arctan2(x, z)
    lat = np.arctan2(y, np.sqrt(x * x + z * z))
    mx = ((lon / (2 * math.pi) + 0.5) * larg_eq).astype(np.float32)
    my = ((0.5 - lat / math.pi) * alt_eq).astype(np.float32)
    return mx, my


def face_do_equirect(equirect, face, lado):
    """Uma face do cubo, amostrada do panorama."""
    alt, larg = equirect.shape[:2]
    mx, my = _mapa_da_face(face, lado, alt, larg)
    # BORDER_WRAP so resolve o x; o y nunca sai do intervalo porque |lat|<=pi/2
    return cv2.remap(equirect, mx, my, cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_WRAP)


def niveis(lado_cubo, lado_ladrilho=LADO_DO_LADRILHO):
    """
    Quantos niveis a piramide tem.

    A propriedade que importa esta escrita na condicao: o nivel 0 cabe num
    ladrilho so. E ele que aparece primeiro na tela, e se precisasse de quatro
    arquivos a primeira imagem custaria quatro idas a rede — justamente o que
    estes ladrilhos vieram evitar.

    O gerador do Pannellum calcula isto por logaritmo e depois corrige com um
    caso especial. Aqui a corrigir nao sobra: o laco ja garante a propriedade.
    """
    n = 1
    while lado_cubo / 2.0 ** (n - 1) > lado_ladrilho:
        n += 1
    return n


def _gravar(img, caminho, q=QUALIDADE):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        raise RuntimeError("falha ao codificar %s" % caminho)
    buf.tofile(caminho)          # imwrite falha calado em caminho com acento


def gerar(equirect, destino, lado_ladrilho=LADO_DO_LADRILHO):
    """
    Escreve a piramide inteira e devolve o bloco `multiRes` da cena.

    Os arquivos saem em <destino>/<nivel>/<face><linha>_<coluna>.jpg, que e o
    caminho que o Pannellum monta a partir de `path`.
    """
    alt, larg = equirect.shape[:2]
    lado = lado_do_cubo(larg)
    n = niveis(lado, lado_ladrilho)
    os.makedirs(destino, exist_ok=True)

    for face in FACES:
        cheia = face_do_equirect(equirect, face, lado)
        for nivel in range(n):
            tamanho = int(lado / 2 ** (n - 1 - nivel))
            img = (cheia if tamanho == lado
                   else cv2.resize(cheia, (tamanho, tamanho),
                                   interpolation=cv2.INTER_AREA))
            pasta = os.path.join(destino, str(nivel))
            os.makedirs(pasta, exist_ok=True)
            quantos = int(math.ceil(float(tamanho) / lado_ladrilho))
            for ly in range(quantos):
                for lx in range(quantos):
                    pedaco = img[ly * lado_ladrilho:(ly + 1) * lado_ladrilho,
                                 lx * lado_ladrilho:(lx + 1) * lado_ladrilho]
                    _gravar(pedaco, os.path.join(
                        pasta, "%s%d_%d.jpg" % (face, ly, lx)))

    return {
        "path": "/%l/%s%y_%x",
        "extension": "jpg",
        "tileResolution": lado_ladrilho,
        "maxLevel": n - 1,
        "cubeResolution": lado,
    }
