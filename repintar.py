# -*- coding: utf-8 -*-
"""
Repintar o panorama: a planta manda no LAYOUT, o modelo manda na APARENCIA.

O PROBLEMA QUE ESTE MODULO RESOLVE. O tracador entrega geometria correta em
metros e aparencia de diagrama: todo movel e uma caixa alinhada aos eixos, nao
ha sombra, e as texturas sao senos. Modelo de imagem faz o oposto — aparencia
convincente, geometria inventada. Juntar os dois exige um intermediario, e e
ele que mora aqui.

POR QUE NAO REPINTAR O EQUIRRETANGULAR DIRETO. Porque nenhum modelo de imagem
foi treinado em equirretangular. Entregando a esfera achatada, ele devolve
polos entortados e a emenda de 0 grau com um lado diferente do outro — a
mesma costura visivel que ja derrubou a captura por celular aqui. Entao o
panorama e quebrado em VISTAS EM PERSPECTIVA, que e o que o modelo entende,
cada uma e repintada, e o resultado e tecido de volta na esfera.

A SOBREPOSICAO E DE PROPOSITO. As vistas cobrem 110 graus num arranjo que
precisaria de bem menos. O excesso existe porque duas vistas repintadas
separadamente NAO concordam na fronteira — o modelo nao sabe o que o vizinho
fez. Com sobreposicao larga, a transicao acontece ao longo de dezenas de graus
em vez de numa linha, e a mistura por peso esconde o desacordo. E o mesmo
motivo pelo qual profundidade.py usa 110 graus para fundir as suas seis vistas.

O QUE ESTE MODULO NAO FAZ. Ele nao chama modelo nenhum. `repintor` e uma
funcao que entra de fora: recebe (vista BGR, profundidade da vista, descricao
do comodo) e devolve a vista repintada. O padrao e a identidade, que devolve a
vista como veio — assim o encanamento inteiro se testa sem API, sem chave e
sem custo, e o dia em que um modelo entrar, o que ja foi provado continua
provado.

A PROFUNDIDADE AQUI E EXATA, e isso e uma vantagem rara. Os modelos de
repintura sao guiados por mapa de profundidade, e quase todo mundo precisa
ESTIMAR o seu com uma segunda rede. render() devolve a distancia real de cada
pixel, porque ela sai do proprio tracado. O guia e verdade, nao palpite.
"""
import numpy as np

import cv2

LADO = 1024               # lado da vista entregue ao modelo, em pixels
FOV = 110.0               # graus; > o necessario, para sobrepor (ver acima)


def direcoes_padrao():
    """
    Oito vistas que cobrem a esfera com folga: seis em volta, uma para cima,
    uma para baixo.

    Seis ao redor com 110 graus cada da 660 graus para cobrir 360 — quase o
    dobro. Nao e desperdicio: e a margem de mistura. Com quatro vistas de 110
    a sobreposicao cairia para 20 graus de cada lado e a emenda voltaria a
    aparecer como uma faixa, em vez de se diluir.
    """
    return ([(yaw, 0.0) for yaw in (0.0, 60.0, 120.0, 180.0, 240.0, 300.0)]
            + [(0.0, -90.0), (0.0, 90.0)])


def _rotacao(yaw_g, pitch_g):
    """Mesma convencao de profundidade.py: +y aponta para BAIXO na imagem."""
    y, p = np.radians(yaw_g), np.radians(pitch_g)
    rx = np.array([[1, 0, 0],
                   [0, np.cos(p), -np.sin(p)],
                   [0, np.sin(p), np.cos(p)]], np.float64)
    ry = np.array([[np.cos(y), 0, np.sin(y)],
                   [0, 1, 0],
                   [-np.sin(y), 0, np.cos(y)]], np.float64)
    return ry @ rx


def _foco(lado, fov):
    return (lado / 2.0) / np.tan(np.radians(fov) / 2.0)


def extrair(equi, yaw, pitch, lado=LADO, fov=FOV):
    """
    Uma janela em perspectiva do panorama, como se fosse uma foto tirada dali.

    Serve tanto para a imagem quanto para a profundidade: o que muda e so a
    interpolacao, e por isso ela e escolhida pelo tipo do que entrou. Vizinho
    mais proximo em profundidade, porque misturar distancias na borda de um
    movel inventa um valor que nao existe nem no movel nem no fundo.
    """
    alt_e, larg_e = equi.shape[:2]
    f = _foco(lado, fov)
    eixo = np.arange(lado, dtype=np.float32) - lado / 2.0 + 0.5
    u, v = np.meshgrid(eixo, eixo)
    d = np.stack([u, v, np.full_like(u, f)], -1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    d = d @ _rotacao(yaw, pitch).T

    lon = np.arctan2(d[..., 0], d[..., 2])
    lat = np.arcsin(np.clip(d[..., 1], -1, 1))
    mx = (((lon / (2 * np.pi)) + 0.5) * larg_e - 0.5).astype(np.float32)
    my = (((lat / np.pi) + 0.5) * alt_e - 0.5).astype(np.float32)
    interp = cv2.INTER_NEAREST if equi.ndim == 2 else cv2.INTER_CUBIC
    return cv2.remap(equi, mx, my, interp, borderMode=cv2.BORDER_WRAP)


def _peso_da_vista(lado):
    """
    Peso de mistura: cheio no centro da vista, zero na borda.

    Coseno levantado nos dois eixos. O que importa nao e a forma exata e sim
    chegar a ZERO na borda: com peso residual na beirada, a ultima coluna de
    uma vista entra na media e marca uma linha fina — que e exatamente a
    costura que se quer evitar.
    """
    t = (np.arange(lado, dtype=np.float32) + 0.5) / lado
    janela = 0.5 - 0.5 * np.cos(2 * np.pi * t)       # Hann: zero nas pontas
    return np.outer(janela, janela) + 1e-6


def tecer(vistas, largura, altura, lado=LADO, fov=FOV):
    """
    Costura as vistas em perspectiva de volta num equirretangular.

    Para cada pixel da esfera: a direcao dele, girada para o referencial de
    cada vista. Se cair na frente da camera e dentro do quadro, aquela vista
    opina, com o peso de _peso_da_vista(). A saida e a media ponderada.

    `vistas` e uma lista de (yaw, pitch, imagem).
    """
    lon = ((np.arange(largura, dtype=np.float32) + 0.5) / largura - 0.5) * 2 * np.pi
    lat = ((np.arange(altura, dtype=np.float32) + 0.5) / altura - 0.5) * np.pi
    lon, lat = np.meshgrid(lon, lat)
    dirs = np.stack([np.cos(lat) * np.sin(lon),
                     np.sin(lat),
                     np.cos(lat) * np.cos(lon)], -1).astype(np.float32)

    f = _foco(lado, fov)
    peso_base = _peso_da_vista(lado)
    canais = 1 if vistas[0][2].ndim == 2 else vistas[0][2].shape[2]
    soma = np.zeros((altura, largura, canais), np.float32)
    pesos = np.zeros((altura, largura), np.float32)

    for yaw, pitch, img in vistas:
        # para o referencial da vista: a transposta desfaz o giro da extracao
        local = dirs @ _rotacao(yaw, pitch)
        z = local[..., 2]
        # atras da camera nao se ve; o 1e-6 evita dividir por zero no equador
        frente = z > 1e-6
        zz = np.where(frente, z, 1.0)
        u = local[..., 0] / zz * f + lado / 2.0 - 0.5
        v = local[..., 1] / zz * f + lado / 2.0 - 0.5
        dentro = frente & (u >= 0) & (u <= lado - 1) & (v >= 0) & (v <= lado - 1)
        if not dentro.any():
            continue

        plano = img.reshape(img.shape[0], img.shape[1], canais).astype(np.float32)
        amostra = cv2.remap(plano, u.astype(np.float32), v.astype(np.float32),
                            cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        amostra = amostra.reshape(altura, largura, canais)
        w = cv2.remap(peso_base, u.astype(np.float32), v.astype(np.float32),
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                      borderValue=0.0)
        w = np.where(dentro, w, 0.0).astype(np.float32)
        soma += amostra * w[:, :, None]
        pesos += w

    # Buraco de cobertura nao pode virar preto silencioso: se um pixel ficou
    # sem vista nenhuma, isso e defeito do arranjo de direcoes e tem de doer
    # no teste, nao sair como mancha no tour.
    vazio = pesos <= 1e-5
    pesos = np.maximum(pesos, 1e-5)
    saida = soma / pesos[:, :, None]
    if vazio.any():
        saida[vazio] = 0.0
    return (saida[:, :, 0] if canais == 1 else saida), vazio


def identidade(vista, profundidade, descricao):
    """Repintor que nao repinta. E o padrao, e e o que torna isto testavel."""
    return vista


def repintar(equi, profundidade_equi, descricao="",
             repintor=identidade, direcoes=None, lado=LADO, fov=FOV):
    """
    O panorama inteiro, passado vista a vista pelo `repintor`.

    Devolve (equirretangular repintado, mascara dos pixels sem cobertura).
    Com o repintor padrao a saida e o proprio panorama de volta, a menos da
    reamostragem — e e isso que o teste de ida e volta mede.
    """
    altura, largura = equi.shape[:2]
    direcoes = direcoes_padrao() if direcoes is None else direcoes
    prontas = []
    for yaw, pitch in direcoes:
        vista = extrair(equi, yaw, pitch, lado, fov)
        prof = extrair(profundidade_equi, yaw, pitch, lado, fov)
        prontas.append((yaw, pitch, repintor(vista, prof, descricao)))
    return tecer(prontas, largura, altura, lado, fov)
