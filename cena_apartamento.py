# -*- coding: utf-8 -*-
"""
Um apartamento inteiro em 360, gerado por tracado de raios.

Por que existe: o acervo de imagens do projeto foi apagado, e sem imagem nao ha
o que demonstrar. Isto reconstroi um acervo do zero — e de quebra resolve dois
problemas que as fotos de verdade tinham.

O QUE ISTO FAZ MELHOR QUE UMA FOTO:

1. Varios pontos de captura POR COMODO, com a paralaxe fisicamente certa entre
   eles. Numa captura real isso exige voltar ao imovel e refotografar.
2. Profundidade EXATA. O modelo de IA deduz profundidade da imagem e erra no
   contorno dos moveis — e aquele erro e a origem do borrao ao caminhar. Aqui a
   distancia e conhecida: sai do proprio raio.
3. O norte dos panoramas coincide de graca, porque todos saem do mesmo sistema
   de coordenadas. Em captura real, alinhar isso e trabalho.

O QUE ISTO NAO E: nao e fotografia. Serve para demonstrar navegacao, medicao e
caminhada — nao para julgar qualidade fotografica. Quem olhar vai ver que e
sintetico, e deve ver mesmo.

  python cena_apartamento.py                 grava em fotos_apartamento/
  python cena_apartamento.py 4096            em outra largura
"""
import math
import os
import sys

import cv2
import numpy as np

LARGURA = 8192                   # "o maior detalhamento possivel": 8k equirretangular
OLHO = 1.50                      # igual a ALTURA_CAMERA do andar.html, para a
                                 # calibracao pelo chao bater sem erro de escala
LARGURA_PROF = 1024              # mesma resolucao que o pipeline de IA entrega

import plantas

PE_DIREITO = plantas.PE_DIREITO

# ----------------------------------------------------------------- materiais
#
# Cor base em BGR. O desenho fino vem de `_textura`, que e onde mora o
# detalhamento: parede lisa nao da referencia nenhuma para quem olha nem para
# quem mede — foi medido neste projeto, 69 pontos de interesse contra 4038.
MATERIAIS = {
    "parede":     (176, 174, 168),
    "jantar":     (168, 170, 178),
    "cozinha":    (186, 186, 182),
    "parede_q1":  (168, 176, 182),
    "banheiro":   (190, 186, 178),
    "servico":    (182, 182, 180),
    "parede_q2":  (170, 172, 184),
    "piso":       (96, 112, 134),
    "porcelanato": (178, 180, 182),
    "teto":       (212, 211, 208),
    "madeira":    (62, 92, 132),
    "madeira_esc": (44, 62, 92),
    "estofado":   (96, 104, 122),
    "estofado_b": (120, 128, 146),
    "roupa_cama": (198, 202, 208),     # 238 puro estourava em branco chapado
    "metal":      (150, 152, 156),
    "vidro":      (232, 228, 214),
    "tapete":     (78, 96, 128),
    "pedra":      (72, 74, 78),
    "planta":     (62, 110, 74),
    "livro_a":    (58, 66, 148),
    "louca":      (238, 238, 236),
    # Branco de guarda-roupa. Nao e "louca" nem "roupa_cama": um
    # painel do chao ao teto em 238 chapado le como PAREDE, e o
    # quarto perde o movel que mais ocupa espaco nele.
    "laminado":   (206, 208, 210),

    # --- a partir daqui, os materiais do loft e da casa de praia. Todos com
    # desenho proprio em _textura: cor chapada le como plastico, e o que da
    # leitura a uma cena sem sombra e a textura, nao a cor.
    "tijolo":     (56, 70, 126),
    "concreto":   (142, 143, 141),
    # Medido no render da cozinha: marmore, azulejo, laminado e a parede
    # ficavam todos no mesmo valor, e com a luz do teto a bancada saturava em
    # branco chapado. Um ambiente em que tudo tem o mesmo tom nao tem
    # profundidade — e a coifa de inox sumia dentro do armario.
    "marmore":    (216, 215, 210),
    "azulejo":    (206, 204, 198),
    "cortina":    (204, 208, 212),
    "couro":      (54, 76, 114),
    "inox":       (162, 164, 166),   # mais escuro que o armario branco
    "tela":       (26, 25, 24),
    "quadro":     (120, 120, 120),      # a cor sai do proprio desenho
    "madeira_clara": (138, 168, 196),
    "palha":      (122, 162, 198),
}

# ------------------------------------------------------------ a planta em uso
#
# O tracador le estes globais. `usar()` os troca antes de cada imovel — a
# renderizacao e sequencial, entao nao ha duas plantas no ar ao mesmo tempo.
# A alternativa, passar a planta por parametro em toda funcao, encheria sete
# assinaturas de um dado que nao muda dentro de um render.
PLANTA = None
LARG = FUNDO = 0.0
ZONAS = CAIXAS = JANELAS = LUZES = PONTOS = ()
_PAREDE_DA_ZONA = _PISO_DA_ZONA = ()
_LIMITES = ()


def usar(planta):
    """Aponta o tracador para uma planta. Devolve ela mesma, para encadear."""
    global PLANTA, LARG, FUNDO, ZONAS, CAIXAS, JANELAS, LUZES, PONTOS
    global _PAREDE_DA_ZONA, _PISO_DA_ZONA, _LIMITES, VISTA
    PLANTA = planta
    VISTA = planta.get("vista", "campo")
    LARG, FUNDO = planta["larg"], planta["fundo"]
    ZONAS = planta["zonas"]
    CAIXAS = planta["caixas"]
    JANELAS = planta["janelas"]
    LUZES = planta["luzes"]
    PONTOS = planta["pontos"]
    _PAREDE_DA_ZONA = [z[5] for z in ZONAS]
    _PISO_DA_ZONA = [z[6] for z in ZONAS]
    _LIMITES = ((0, 0.0, "parede"), (0, LARG, "parede"), (1, 0.0, "piso"),
                (1, PE_DIREITO, "teto"), (2, 0.0, "parede"), (2, FUNDO, "parede"))
    return planta


# ------------------------------------------------------------------ texturas

def _ruido(p, escala, amp):
    """Variacao suave e deterministica. Tira o aspecto de plastico."""
    return 1.0 + amp * (np.sin(p[:, 0] * escala) * np.sin(p[:, 2] * escala * 1.7)
                        + 0.6 * np.sin(p[:, 1] * escala * 2.3))


# O que existe do lado de fora. Cada entrada e (zenite, horizonte, terreno) em
# BGR — o ceu la em cima, a neblina na linha do horizonte, e o que fica abaixo
# dela. Tres cores bastam porque e tudo distante: perto da janela nao ha nada.
#
# Por que virou tabela. A vista era uma so, verde, chapada no codigo. Um imovel
# de praia com campo na janela e um erro que o comprador ve antes de ver o
# imovel — e e justamente pela janela que ele decide se quer morar ali.
VISTAS = {
    "campo":  ((196, 148, 104), (232, 222, 208), (104, 118, 100)),
    "mar":    ((190, 134,  76), (238, 231, 216), (146, 114,  48)),
    "cidade": ((192, 156, 124), (216, 213, 212), (132, 132, 130)),
}

VISTA = "campo"          # trocada por usar(), conforme a planta pede


def _relevo_da_vista(d, abaixo, chao):
    """
    O que separa mar de campo de cidade ABAIXO da linha do horizonte.

    Acima dela e tudo ceu e muda pouco. O que o olho usa para dizer "isto e
    mar" ou "isto e cidade" esta embaixo: a agua vem em bandas que se apertam
    ao chegar no horizonte, e a cidade tem silhueta recortada. Sem isso as
    tres vistas sao a mesma mancha em cores diferentes.
    """
    if VISTA == "mar":
        # As bandas se apertam perto do horizonte sozinhas: 1/abaixo cresce
        # sem limite ali. E perspectiva de graca — a mesma razao pela qual as
        # ondas parecem mais juntas quanto mais longe estao.
        banda = np.sin(1.9 / np.maximum(abaixo[:, 0], 0.025))
        return chao * (1.0 + 0.055 * banda)[:, None]

    if VISTA == "cidade":
        # A silhueta. Predios de alturas diferentes conforme o azimute, e o
        # raio que passa por baixo do topo bate em predio, nao em chao. Sem
        # recorte, "cidade" e so um cinza — e cinza chapado le como parede,
        # que e o defeito que a janela existia para resolver.
        az = np.arctan2(d[:, 0], d[:, 2])
        topo = (0.055 + 0.045 * np.sin(az * 7.0)
                + 0.022 * np.sin(az * 23.0 + 1.1)
                + 0.012 * np.sin(az * 53.0))
        predio = abaixo[:, 0] < topo
        if predio.any():
            chao = chao.copy()
            face = 0.84 + 0.16 * (np.floor(az * 9.0) % 3.0) / 2.0
            chao[predio] *= face[predio][:, None]
            # janelas acesas: pontinhos claros na face, em grade
            luz = (np.sin(az * 180.0) > 0.88) & predio
            chao[luz] = np.minimum(chao[luz] * 1.5, 255.0)
    return chao


def _faces(face, quantos):
    """
    A face que o raio achou, sempre como vetor.

    POR QUE ISTO EXISTE. `face` chega de dois lugares com dois formatos: da
    casca vem um INTEIRO (a parede inteira e aquela face), e das caixas vem um
    VETOR com uma face por raio. Nenhuma textura usava a face ate agora, entao
    a diferenca nunca incomodou — a primeira que usasse estouraria com
    "truth value of an array is ambiguous", e seria no meio de um render.
    """
    return np.broadcast_to(np.asarray(face), (quantos,))


def _horizontal(p, face):
    """
    O eixo que corre na horizontal sobre a superficie achada.

    Fiada de tijolo, veio de tabua e trama de palha correm ao longo da parede,
    nao pelos eixos do mundo. Numa parede de x constante quem corre e o z; numa
    de z constante, o x. Sem isto, o tijolo de uma parede sai em fiada e o da
    parede vizinha sai em coluna.
    """
    ehx = np.isin(_faces(face, p.shape[0]), (0, 1))
    return np.where(ehx, p[:, 2], p[:, 0])


def _ceu(d):
    """
    O que se ve pela janela.

    Ate aqui a janela era um retangulo bege CHAPADO na parede: iluminava o
    comodo e nao mostrava nada. Olhando de qualquer angulo aparecia a mesma
    mancha clara, e "vista" nao existia — o que e justamente o oposto do que
    uma janela e.

    Nao ha mundo la fora para tracar: modelar rua, vizinhanca e horizonte
    custaria mais que a casa inteira, e seria cenario inventado com cara de
    documento. O que ha e ceu e terreno distantes, escolhidos pela DIRECAO do
    raio — para cima, ceu; para baixo, chao.

    Isso basta para a janela virar abertura, e o motivo e o olho, nao a
    imagem: o que diz ao cerebro que aquilo e fora e a vista MUDAR quando a
    cabeca vira. Um painel chapado nao muda; um ceu por direcao, sim.
    """
    dy = np.clip(d[:, 1], -1.0, 1.0)
    # BGR, porque o panorama inteiro sai em BGR para o OpenCV gravar. A vista
    # cai no campo se vier nome desconhecido: aqui, no meio de um render de
    # meia hora, nao e lugar de estourar — quem recusa nome errado e o
    # conferir(), antes de o render comecar.
    cores = VISTAS.get(VISTA, VISTAS["campo"])
    zenite = np.array(cores[0], np.float32)
    horizonte = np.array(cores[1], np.float32)
    terreno = np.array(cores[2], np.float32)

    acima = np.clip(dy, 0.0, 1.0)[:, None]
    abaixo = np.clip(-dy, 0.0, 1.0)[:, None]
    # a subida ao zenite e mais rapida que a descida ao chao: e assim que um
    # ceu real se comporta visto de dentro de casa, com o horizonte lavado
    ceu = horizonte * (1.0 - acima ** 0.55) + zenite * (acima ** 0.55)
    chao = horizonte * (1.0 - abaixo ** 0.8) + terreno * (abaixo ** 0.8)
    chao = _relevo_da_vista(d, abaixo, chao)
    return np.where(dy[:, None] > 0.0, ceu, chao)


def _textura(material, p, face, cor, dirs=None, casca=False):
    """
    A cor de cada ponto de superficie.

    `casca` diz se o que foi atingido e a casca do imovel — as seis faces
    externas — ou uma caixa de dentro. So a casca ganha janela: movel encostado
    na parede da janela nao vira ceu, e piso nao vira ceu nunca.
    """
    saida = np.repeat(np.array(cor, np.float32)[None, :], p.shape[0], axis=0)

    if material == "piso":
        # tabua corrida: junta escura a cada 19 cm e veio da madeira ao longo
        tabua = np.floor(p[:, 2] / 0.19)
        junta = np.abs(p[:, 2] / 0.19 - tabua - 0.5) > 0.47
        saida *= (0.90 + 0.10 * (tabua.astype(np.int32) % 3))[:, None]
        veio = 0.05 * np.sin(p[:, 0] * 23.0 + tabua * 2.1) + 0.03 * np.sin(p[:, 0] * 97.0)
        saida *= (1.0 + veio)[:, None]
        saida[junta] *= 0.72
    elif material == "porcelanato":
        # piso de cozinha: placas de 45 cm com rejunte
        gx = np.abs((p[:, 0] / 0.45) % 1.0 - 0.5) > 0.47
        gz = np.abs((p[:, 2] / 0.45) % 1.0 - 0.5) > 0.47
        saida *= _ruido(p, 6.0, 0.03)[:, None]
        saida[gx | gz] *= 0.80
    elif material == "tapete":
        anel = np.hypot(p[:, 0] - 2.05, p[:, 2] - 2.25)
        saida *= (0.88 + 0.12 * (np.floor(anel / 0.16).astype(np.int32) % 2))[:, None]
        saida *= _ruido(p, 40.0, 0.05)[:, None]
    elif material in ("parede", "parede_q1", "parede_q2", "cozinha"):
        saida *= _ruido(p, 3.5, 0.02)[:, None]
        saida[p[:, 1] < 0.10] *= 0.55                    # rodape
        if material == "cozinha":
            faixa = (p[:, 1] > 0.94) & (p[:, 1] < 1.52)  # azulejo atras da pia
            gx = np.abs((p[:, 0] / 0.20) % 1.0 - 0.5) > 0.44
            gy = np.abs((p[:, 1] / 0.20) % 1.0 - 0.5) > 0.44
            saida[faixa] *= 1.06
            saida[faixa & (gx | gy)] *= 0.86
    elif material == "teto":
        for lx, ly, lz, _ in [l for l in LUZES if l[1] > 2.3]:
            r = np.hypot(p[:, 0] - lx, p[:, 2] - lz)
            saida[r < 0.26] = np.array([252, 252, 248], np.float32)
            saida[(r >= 0.26) & (r < 0.33)] *= 0.74
    elif material in ("madeira", "madeira_esc"):
        saida *= (1.0 + 0.045 * np.sin(p[:, 1] * 61.0 + p[:, 0] * 7.0))[:, None]
    elif material == "laminado":
        # O primeiro render do quarto saiu com o guarda-roupa MARROM, porque
        # ele estava de "madeira" e o painel das fotos do dono e branco. A
        # correcao obvia — branco chapado — trocaria de defeito: o proprio
        # "roupa_cama" ja anota que 238 puro estoura, e um painel do chao ao
        # teto sem variacao nenhuma fica indistinguivel do reboco claro.
        # Dai a fresta: e ela que diz ao olho que aquilo tem porta.
        porta = np.abs((p[:, 0] / 0.45) % 1.0 - 0.5) > 0.47
        saida *= _ruido(p, 8.0, 0.012)[:, None]
        saida *= (1.0 - 0.06 * np.clip((2.4 - p[:, 1]) / 2.4, 0, 1))[:, None]
        saida[porta] *= 0.80
        saida[p[:, 1] < 0.08] *= 0.70          # rodape do movel
    elif material == "tijolo":
        # Fiada corrida, com a junta a meio tijolo em fiada alternada — e o
        # travamento que qualquer parede de tijolo de verdade tem. Em fiadas
        # alinhadas a parede le como ladrilho, nao como alvenaria.
        alto, comp = 0.077, 0.252
        eixo = _horizontal(p, face)
        fiada = np.floor(p[:, 1] / alto)
        u = (eixo + (fiada % 2.0) * (comp / 2.0)) / comp
        # cada peca com seu tom: barro nao sai do forno duas vezes igual
        tom = ((np.floor(u) * 7.0 + fiada * 13.0) * 0.37) % 1.0
        saida *= (0.86 + 0.28 * tom)[:, None]
        saida *= _ruido(p, 34.0, 0.05)[:, None]
        junta = ((np.abs((p[:, 1] / alto) % 1.0 - 0.5) > 0.42)
                 | (np.abs(u % 1.0 - 0.5) > 0.47))
        saida[junta] = np.array([148, 150, 152], np.float32)
    elif material == "concreto":
        # Concreto aparente guarda a marca da forma: as juntas das tabuas e os
        # furos dos tirantes. Liso, vira parede pintada de cinza.
        saida *= _ruido(p, 2.2, 0.055)[:, None]
        saida *= _ruido(p, 11.0, 0.03)[:, None]
        saida[np.abs((p[:, 1] / 0.22) % 1.0 - 0.5) > 0.47] *= 0.90
        eixo = _horizontal(p, face)
        furo = ((np.abs((eixo / 0.66) % 1.0 - 0.5) < 0.030)
                & (np.abs((p[:, 1] / 0.66) % 1.0 - 0.5) < 0.030))
        saida[furo] *= 0.74
    elif material == "marmore":
        # O veio e o marmore. Uma pedra clara sem veio e Corian, e o olho sabe
        # a diferenca mesmo sem saber o nome.
        # Os TRES eixos entram. A primeira versao usava so x e z, e numa
        # parede o z e constante: o veio saiu em listra vertical, igual em
        # toda a altura. Com y dentro da conta, qualquer plano — parede,
        # tampo ou lateral — corta a pedra num angulo diferente, que e o que
        # acontece quando se serra um bloco de marmore de verdade.
        t = (p[:, 0] * 1.9 + p[:, 2] * 1.3 + p[:, 1] * 1.55
             + 0.55 * np.sin(p[:, 2] * 3.3 + p[:, 1] * 2.1)
             + 0.40 * np.sin(p[:, 0] * 5.1 - p[:, 1] * 1.7)
             + 0.18 * np.sin(p[:, 0] * 13.0 + p[:, 2] * 11.0))
        veio = np.abs(np.sin(t * 2.2))
        saida *= (0.97 + 0.05 * veio)[:, None]
        saida[veio < 0.035] *= 0.74                 # veio principal, fino
        saida[np.abs(np.sin(t * 7.0 + 1.3)) < 0.020] *= 0.88   # os secundarios
        saida *= _ruido(p, 26.0, 0.015)[:, None]
        saida[_faces(face, p.shape[0]) == 3] *= 1.05       # tampo polido
    elif material == "azulejo":
        eixo = _horizontal(p, face)
        fiada = np.floor(p[:, 1] / 0.10)
        u = (eixo + (fiada % 2.0) * 0.10) / 0.20
        # o vidrado clareia de baixo para cima dentro de CADA peca: e o
        # reflexo da peca, e e o que faz ler como ceramica e nao como pintura
        saida *= (0.95 + 0.09 * ((p[:, 1] / 0.10) % 1.0))[:, None]
        saida *= _ruido(p, 14.0, 0.018)[:, None]
        rejunte = ((np.abs(u % 1.0 - 0.5) > 0.465)
                   | (np.abs((p[:, 1] / 0.10) % 1.0 - 0.5) > 0.44))
        saida[rejunte] *= 0.84
    elif material == "cortina":
        # Prega vertical, e o pe mais escuro que a cabeceira. Tecido chapado
        # le como placa de isopor encostada na parede.
        eixo = _horizontal(p, face)
        saida *= (1.0 + 0.11 * np.sin(eixo * 34.0))[:, None]
        saida *= (0.80 + 0.26 * np.clip(p[:, 1] / 2.2, 0, 1))[:, None]
        saida *= _ruido(p, 60.0, 0.02)[:, None]
    elif material == "couro":
        saida *= _ruido(p, 85.0, 0.05)[:, None]
        saida *= _ruido(p, 23.0, 0.04)[:, None]
        assento = _faces(face, p.shape[0]) == 3
        # o assento marca com o uso, e marca mais no meio
        saida[assento] *= (1.04 + 0.05 * np.sin(p[assento][:, 0] * 9.0)
                           * np.sin(p[assento][:, 2] * 11.0))[:, None]
    elif material == "inox":
        eixo = _horizontal(p, face)
        saida *= (1.0 + 0.05 * np.sin(eixo * 420.0))[:, None]   # escovado
        saida *= _ruido(p, 6.0, 0.03)[:, None]
        if dirs is not None:
            # O que separa aco de plastico cinza e o brilho MUDAR com o
            # angulo. Nao ha normal aqui para um especular de verdade, entao
            # serve a inclinacao do olhar: assumido como aproximacao, e o
            # bastante para o inox parar de parecer papel.
            saida *= (1.0 + 0.30 * np.clip(dirs[:, 1] + 0.25, 0, 1) ** 2)[:, None]
    elif material == "tela":
        saida *= (0.92 + 0.16 * np.clip(p[:, 1] / 2.0, 0, 1))[:, None]
        if dirs is not None:
            # vidro preto devolve o teto quando o olhar passa rasante
            saida += (np.clip(0.5 - np.abs(dirs[:, 1]), 0, 0.5) * 92.0)[:, None]
    elif material == "quadro":
        # Campos de cor, do jeito de uma tela abstrata. Quem olha nao precisa
        # reconhecer a obra: precisa que a parede pare de ser so parede.
        # Campos GRANDES. Em 11 cm a tela virava mosaico de azulejo colorido,
        # que chama mais atencao que o imovel — e quadro na parede existe para
        # a parede parar de ser so parede, nao para disputar com ela.
        eixo = _horizontal(p, face)
        k = np.floor(eixo / 0.38) + np.floor(p[:, 1] / 0.46) * 5.0
        saida = np.stack([(k * 53.0) % 70.0 + 118.0,
                          (k * 29.0) % 62.0 + 124.0,
                          (k * 71.0) % 78.0 + 112.0], axis=1).astype(np.float32)
        saida *= _ruido(p, 9.0, 0.05)[:, None]
    elif material == "madeira_clara":
        eixo = _horizontal(p, face)
        tabua = np.floor(eixo / 0.14)
        saida *= (0.94 + 0.08 * (tabua % 3.0) / 2.0)[:, None]
        saida *= (1.0 + 0.05 * np.sin(p[:, 1] * 53.0 + tabua * 2.7))[:, None]
        saida[np.abs((eixo / 0.14) % 1.0 - 0.5) > 0.47] *= 0.86
    elif material == "palha":
        # trama cruzada: e o xadrez que diz fibra, e nenhuma outra coisa aqui
        # tem xadrez
        eixo = _horizontal(p, face)
        saida *= (1.0 + 0.15 * np.sin(eixo * 52.0) * np.sin(p[:, 1] * 52.0))[:, None]
        saida *= _ruido(p, 70.0, 0.04)[:, None]
    elif material in ("estofado", "estofado_b"):
        saida *= _ruido(p, 55.0, 0.035)[:, None]
    elif material == "roupa_cama":
        vinco = (0.045 * np.sin(p[:, 0] * 14.0) + 0.035 * np.sin(p[:, 2] * 19.0)
                 + 0.02 * np.sin(p[:, 0] * 53.0))
        saida *= (1.0 + vinco)[:, None]
    elif material == "livro_a":
        # Lombadas ao longo da ESTANTE, e nao do eixo z do mundo. O livro_a e
        # anterior ao _horizontal() e ficou de fora daquela correcao — e
        # ninguem viu, porque ate agora a caixa dos livros vivia enterrada
        # dentro da carcaca da estante e raio nenhum chegava nela. Na estante
        # da mansao, que e comprida no x, as lombadas sairiam atravessadas.
        eixo = _horizontal(p, face)
        larg = 0.032
        k = np.floor(eixo / larg)
        # Paleta CONTIDA. A versao anterior sorteava matiz cheia, e numa
        # estante inteira saia uma parede de neon que roubava a sala. Lombada
        # de livro e papel e tecido: varia mais de valor do que de cor.
        saida = np.stack([96.0 + 86.0 * ((k * 0.37) % 1.0),
                          104.0 + 78.0 * ((k * 0.71) % 1.0),
                          110.0 + 74.0 * ((k * 0.19) % 1.0)],
                         axis=1).astype(np.float32)
        # nem todo livro tem a mesma altura: o topo da fileira nao sai reto
        recuo = 0.10 + 0.17 * ((k * 0.53) % 1.0)
        saida[(p[:, 1] % 0.62) > (0.62 - recuo)] *= 0.52
        saida[np.abs((eixo / larg) % 1.0 - 0.5) > 0.44] *= 0.62
    elif material == "planta":
        # Folhagem: manchas irregulares e vaos escuros entre as folhas. A
        # versao anterior era um xadrez regular — e xadrez nenhum existe em
        # planta nenhuma, entao a caixa lia como caixa pintada de verde.
        eixo = _horizontal(p, face)
        f1 = np.sin(eixo * 23.0 + p[:, 1] * 17.0)
        f2 = np.sin(eixo * 41.0 - p[:, 1] * 53.0 + 1.3)
        f3 = np.sin(eixo * 11.0 + p[:, 1] * 7.0 + 2.1)
        folha = 0.50 * f1 + 0.33 * f2 + 0.17 * f3
        saida *= (0.80 + 0.45 * (folha * 0.5 + 0.5))[:, None]
        # o escuro entre as folhas e o que da volume a uma massa verde
        saida[folha < -0.45] *= 0.42
        saida *= _ruido(p, 55.0, 0.05)[:, None]
    elif material == "vidro":
        # Sem transparencia de verdade (o tracado nao refrata), o que faz o
        # olho aceitar o vidro e o degrade vertical mais a moldura. Chapado ele
        # lia como parede clara e tapava o banheiro inteiro.
        saida *= (0.80 + 0.26 * np.clip(p[:, 1] / 2.0, 0, 1))[:, None]
        saida *= np.array([1.02, 1.00, 0.95], np.float32)[None, :]   # verde do vidro
        saida *= (1.0 + 0.05 * np.sin(p[:, 1] * 24.0))[:, None]
        borda = (p[:, 1] < 0.16) | (p[:, 1] > 1.88)
        saida[borda] *= 0.62

    # Janelas de verdade. Antes havia uma "luz de janela" sem janela nenhuma na
    # parede: iluminava a sala e nao aparecia. Alem de estranho, tirava do
    # visitante a unica referencia que diz para que lado ele esta olhando.
    #
    # ISTO FICAVA DENTRO DO RAMO DOS MATERIAIS DE PAREDE, e por isso so valia
    # para "parede", "parede_q1", "parede_q2" e "cozinha". No dia em que um
    # comodo ganhou parede de concreto, a varanda perdeu os dois vaos para o
    # mar — a parede engolia a propria janela, e o imovel de praia ficava sem
    # praia. Agora vale para o material que for, e o que decide e a CASCA.
    #
    # So a casca, e so nas quatro faces de parede: movel encostado embaixo da
    # janela nao vira ceu, e o piso nao vira ceu nunca. As faces 2 e 3 da
    # casca sao piso e teto.
    if casca and face in (0, 1, 4, 5):
        for x0, x1, z0, z1, y0, y1 in JANELAS:
            dentro = ((p[:, 0] >= x0 - 0.08) & (p[:, 0] <= x1 + 0.08)
                      & (p[:, 2] >= z0 - 0.08) & (p[:, 2] <= z1 + 0.08)
                      & (p[:, 1] >= y0) & (p[:, 1] <= y1))
            if not dentro.any():
                continue
            if dirs is None:
                saida[dentro] = np.array([236, 233, 224], np.float32)
            else:
                saida[dentro] = _ceu(dirs[dentro])
            # caixilho: duas folhas, com montante no meio
            q = p[dentro]
            eixo = q[:, 0] if x1 - x0 > z1 - z0 else q[:, 2]
            a0, a1 = (x0, x1) if x1 - x0 > z1 - z0 else (z0, z1)
            meio = np.abs(eixo - (a0 + a1) / 2.0) < 0.035
            trav = np.abs(q[:, 1] - (y0 + y1) / 2.0) < 0.030
            moldura = ((eixo < a0 + 0.06) | (eixo > a1 - 0.06)
                       | (q[:, 1] < y0 + 0.06) | (q[:, 1] > y1 - 0.06))
            escuro = np.array([116, 118, 120], np.float32)
            idx = np.nonzero(dentro)[0]
            saida[idx[meio | trav | moldura]] = escuro
    return saida


# ---------------------------------------------- amostra de material para a 3D
#
# A maquete e feita de caixas de cor chapada, e o panorama e feito das texturas
# daqui. Mesma casa, duas aparencias — e quem olha as duas telas acha que sao
# imoveis diferentes.
#
# A saida e dar a maquete um LADRILHO de cada material, gerado por esta mesma
# _textura(). Nao e aproximacao: e o mesmo desenho, so que amostrado num
# retalho e repetido.
#
# O tamanho do retalho, por material, e um multiplo do periodo do desenho — 4
# tijolos, 5 azulejos, 5 tabuas. Assim a repeticao fecha sem emenda visivel.
# Material sem periodo (ruido, veio, couro) usa um metro e a emenda some no
# proprio ruido.
# Materiais cujo desenho vive no chao, no plano X-Z.
DEITADOS = ("piso", "porcelanato", "tapete", "pedra")

LADRILHO = {
    "tijolo": 1.008,          # 4 x 0,252
    "azulejo": 1.000,         # 5 x 0,20
    "piso": 0.950,            # 5 x 0,19
    "porcelanato": 0.900,     # 2 x 0,45
    "madeira_clara": 0.980,   # 7 x 0,14
    "laminado": 0.900,        # 2 x 0,45
    "concreto": 0.880,        # 4 x 0,22
    "livro_a": 0.992,         # 31 x 0,032
}


def amostra_do_material(material, lado=256):
    """
    Um retalho quadrado do material, pronto para ladrilhar na maquete 3D.

    Devolve BGR, como todo o resto deste modulo. `face` vai como 5 (plano de z
    constante) porque e assim que a maioria das superficies da maquete aparece;
    materiais que dependem da face mudam pouco entre uma e outra.
    """
    if material not in MATERIAIS:
        raise KeyError(material)
    metros = LADRILHO.get(material, 1.0)
    a = np.linspace(0.0, metros, lado, endpoint=False)
    b = np.linspace(metros, 0.0, lado, endpoint=False)
    ga, gb = np.meshgrid(a, b)
    if material in DEITADOS:
        # Piso e tapete desenham no plano X-Z. Amostrados em pe, com o z preso,
        # viravam listra: o tapete saiu parecendo tabua corrida.
        p = np.stack([ga.ravel(), np.zeros(ga.size),
                      gb.ravel()], axis=1).astype(np.float32)
    else:
        # Em pe, mas acima do rodape: comecando no chao, a faixa escura dos
        # primeiros 10 cm entrava na amostra e se repetia a cada metro de
        # parede, como se a casa tivesse rodape no meio.
        p = np.stack([ga.ravel(), (gb + 0.6).ravel(),
                      np.full(ga.size, 0.5)], axis=1).astype(np.float32)
    # dirs constante: a maquete nao tem raio, e o brilho do inox viraria
    # listra se variasse com a linha da amostra
    dirs = np.full((p.shape[0], 3), 0.0, np.float32)
    dirs[:, 1] = 0.25
    dirs[:, 2] = 0.97
    cor = _textura(material, p, 5, MATERIAIS[material], dirs)
    return np.clip(cor, 0, 255).astype(np.uint8).reshape(lado, lado, 3)


# ------------------------------------------------------------------- traçado

def _direcoes(linha0, linha1, largura, altura):
    u = (np.arange(largura, dtype=np.float32) + 0.5) / largura
    v = (np.arange(linha0, linha1, dtype=np.float32) + 0.5) / altura
    th, ph = np.meshgrid((u * 2.0 - 1.0) * np.pi, (0.5 - v) * np.pi)
    c = np.cos(ph)
    return np.stack([c * np.sin(th), np.sin(ph), c * np.cos(th)],
                    axis=-1).reshape(-1, 3).astype(np.float32)


def _casca(o, d):
    """Onde o raio encontra a casca do apartamento, vindo de dentro."""
    t = np.full(d.shape[0], np.inf, np.float32)
    face = np.zeros(d.shape[0], np.int32)
    for i, (eixo, valor, _) in enumerate(_LIMITES):
        with np.errstate(divide="ignore", invalid="ignore"):
            tt = (valor - o[eixo]) / d[:, eixo]
        tt = np.where(np.isfinite(tt) & (tt > 1e-4), tt, np.inf)
        troca = tt < t
        t = np.where(troca, tt, t)
        face = np.where(troca, i, face)
    return t, face


def _inverso(d):
    """
    1/d para o teste de fatias, calculado UMA vez por fatia de imagem.

    A versao anterior dividia dentro do laco das caixas: com 70 caixas eram 140
    divisoes por raio, e divisao e a operacao mais cara aqui. Pre-calculando,
    sobram 3 divisoes e o resto vira multiplicacao — foi o que permitiu triplicar
    o numero de comodos sem triplicar o tempo.

    Componente zero vira 1e-12 em vez de gerar infinito: assim nenhum produto da
    NaN mais adiante, e o raio paralelo ao plano simplesmente nao o encontra.
    """
    seguro = np.where(np.abs(d) < 1e-12, 1e-12, d)
    return (1.0 / seguro).astype(np.float32)


def _caixa(o, inv, c):
    """Entrada do raio na caixa, ou infinito. Teste de fatias, eixo a eixo."""
    entra = np.full(inv.shape[0], -np.inf, np.float32)
    sai = np.full(inv.shape[0], np.inf, np.float32)
    for eixo in range(3):
        a = (c[eixo] - o[eixo]) * inv[:, eixo]
        b = (c[eixo + 3] - o[eixo]) * inv[:, eixo]
        np.maximum(entra, np.minimum(a, b), out=entra)
        np.minimum(sai, np.maximum(a, b), out=sai)
    return np.where((sai >= entra) & (entra > 1e-4), entra, np.inf)


class _Rascunho(object):
    """
    Os vetores de trabalho do tracado, alocados UMA vez por fatia.

    POR QUE EXISTE. A versao anterior criava uns quinze vetores novos por
    caixa — e com 322 caixas numa casa de 520 m2, em 8k, sao mais de vinte mil
    alocacoes de 16 MB por panorama. Medido: o custo estava quase todo em
    pedir e devolver memoria, nao em calcular.
    """

    def __init__(self, linhas, largura):
        f = (linhas, largura)
        self.a = np.empty(f, np.float32)
        self.b = np.empty(f, np.float32)
        self.tmp = np.empty(f, np.float32)
        self.entra = np.empty(f, np.float32)
        self.sai = np.empty(f, np.float32)
        self.m1 = np.empty(f, bool)
        self.m2 = np.empty(f, bool)


def _tangentes_da_fatia(d):
    """A inclinacao do olhar mais baixa e mais alta desta fatia de linhas."""
    def tg(dy):
        return dy / math.sqrt(max(1.0 - dy * dy, 1e-12))
    return tg(float(d[:, 1].min())), tg(float(d[:, 1].max()))


def _fora_da_faixa(o, c, tan0, tan1):
    """
    Nenhum raio desta fatia alcanca esta caixa?

    Um raio que sai do olho a uma inclinacao `tan` e chega a uma distancia
    horizontal `dh` esta na altura o[1] + dh*tan. A caixa so pode ser atingida
    se a altura dela cruzar o intervalo que sai das distancias e das
    inclinacoes extremas — e isso e barato de conferir, uma vez por caixa, em
    vez de quatro milhoes de vezes.

    Erra sempre para o lado de MANTER a caixa: os quatro cantos da pegada dao
    o alcance maximo, e o ponto mais proximo da pegada da o minimo.
    """
    dx = max(c[0] - o[0], 0.0, o[0] - c[3])
    dz = max(c[2] - o[2], 0.0, o[2] - c[5])
    perto = math.hypot(dx, dz)
    longe = max(math.hypot(cx - o[0], cz - o[2])
                for cx in (c[0], c[3]) for cz in (c[2], c[5]))
    alturas = [o[1] + dd * tt for dd in (perto, longe) for tt in (tan0, tan1)]
    return c[4] < min(alturas) or c[1] > max(alturas)


def _colunas_da_caixa(o, c, largura):
    """
    Em que colunas da imagem esta caixa pode aparecer.

    A coluna do equirretangular E o azimute: a coluna k olha para
    th = ((k+0,5)/largura*2 - 1)*pi. Uma caixa vista de fora ocupa um arco de
    menos de meia volta, e fora dele nao ha o que testar — um movel a cinco
    metros cabe em 3% das colunas.

    Com a camera DENTRO da pegada da caixa (um tapete sob os pes, a parede em
    volta) o arco e a volta inteira, e a resposta e "todas".
    """
    ox, oz = float(o[0]), float(o[2])
    if c[0] - 1e-6 <= ox <= c[3] + 1e-6 and c[2] - 1e-6 <= oz <= c[5] + 1e-6:
        return ((0, largura),)

    angs = sorted(math.atan2(cx - ox, cz - oz)
                  for cx in (c[0], c[3]) for cz in (c[2], c[5]))
    # o maior vao entre cantos vizinhos e o lado de FORA do arco
    vao, onde = -1.0, 0
    for i in range(4):
        g = angs[(i + 1) % 4] - angs[i] + (2.0 * math.pi if i == 3 else 0.0)
        if g > vao:
            vao, onde = g, i
    if onde == 3:
        inicio, fim = angs[0], angs[3]
    else:
        inicio, fim = angs[onde + 1], angs[onde] + 2.0 * math.pi

    c0 = (inicio / math.pi + 1.0) * 0.5 * largura
    c1 = (fim / math.pi + 1.0) * 0.5 * largura
    if c1 - c0 >= largura - 4:
        return ((0, largura),)
    ini = (int(math.floor(c0)) - 2) % largura
    qtd = int(math.ceil(c1 - c0)) + 4
    if ini + qtd <= largura:
        return ((ini, ini + qtd),)
    return ((ini, largura), (0, ini + qtd - largura))


def _caixa_em(o, inv, c, t, dono, k, r, ca, cb):
    """
    O teste de fatias de sempre, so que num recorte de colunas e sem alocar.

    Faz exatamente a mesma conta que _caixa(): mesma ordem, mesmos tipos. O
    resultado tem de sair identico bit a bit, e ha teste que confere isso.
    """
    entra, sai = r.entra[:, ca:cb], r.sai[:, ca:cb]
    A, B, T = r.a[:, ca:cb], r.b[:, ca:cb], r.tmp[:, ca:cb]
    m1, m2 = r.m1[:, ca:cb], r.m2[:, ca:cb]
    entra.fill(-np.inf)
    sai.fill(np.inf)
    for eixo in range(3):
        iv = inv[:, ca:cb, eixo]
        np.multiply(iv, c[eixo] - o[eixo], out=A)
        np.multiply(iv, c[eixo + 3] - o[eixo], out=B)
        np.minimum(A, B, out=T)
        np.maximum(A, B, out=B)
        np.maximum(entra, T, out=entra)
        np.minimum(sai, B, out=sai)
    np.greater_equal(sai, entra, out=m1)
    np.greater(entra, 1e-4, out=m2)
    np.logical_and(m1, m2, out=m1)
    np.less(entra, t[:, ca:cb], out=m2)
    np.logical_and(m1, m2, out=m1)
    np.copyto(t[:, ca:cb], entra, where=m1)
    np.copyto(dono[:, ca:cb], k, where=m1)


def _todas_as_caixas(o, inv, d, t, dono, linhas, largura, r):
    """Passa a fatia por todas as caixas, pulando as que nao podem aparecer."""
    inv2 = inv.reshape(linhas, largura, 3)
    t2 = t.reshape(linhas, largura)
    dono2 = dono.reshape(linhas, largura)
    tan0, tan1 = _tangentes_da_fatia(d)
    for k, c in enumerate(CAIXAS):
        if _fora_da_faixa(o, c, tan0, tan1):
            continue
        for ca, cb in _colunas_da_caixa(o, c, largura):
            if cb > ca:
                _caixa_em(o, inv2, c, t2, dono2, k, r, ca, cb)


def _face_caixa(p, c):
    d = np.stack([np.abs(p[:, 0] - c[0]), np.abs(p[:, 0] - c[3]),
                  np.abs(p[:, 1] - c[1]), np.abs(p[:, 1] - c[4]),
                  np.abs(p[:, 2] - c[2]), np.abs(p[:, 2] - c[5])], axis=1)
    return np.argmin(d, axis=1)


_NORMAIS = np.array([[-1, 0, 0], [1, 0, 0], [0, -1, 0],
                     [0, 1, 0], [0, 0, -1], [0, 0, 1]], np.float32)
_NORMAIS_CASCA = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0],
                           [0, -1, 0], [0, 0, 1], [0, 0, -1]], np.float32)


def _zona(p):
    """
    Em qual comodo cai cada ponto. Sai direto de ZONAS, e nao de comparacoes
    escritas a mao — com quatro quadrantes dava para improvisar, com sete
    comodos a mao errada azuleja o quarto errado. Aconteceu.
    """
    z = np.zeros(p.shape[0], np.int32)
    for i, (_, x0, x1, z0, z1, _, _) in enumerate(ZONAS):
        dentro = ((p[:, 0] >= x0 - 0.2) & (p[:, 0] <= x1 + 0.2)
                  & (p[:, 2] >= z0 - 0.2) & (p[:, 2] <= z1 + 0.2))
        z[dentro] = i
    return z


_PAREDE_DA_ZONA = [z[5] for z in ZONAS]
_PISO_DA_ZONA = [z[6] for z in ZONAS]


def _iluminar(p, n):
    """
    Difusa das luzes, com queda pela distancia, sobre um ambiente alto.

    O ambiente e alto de proposito. A primeira versao usava 0,26 e o TETO saia
    quase preto: a luminaria fica 10 cm abaixo dele, entao para qualquer ponto
    do teto que nao esteja bem embaixo dela o angulo e rasante e a difusa da
    quase zero. Fisicamente correto e visualmente errado — num comodo real a luz
    que bate no teto vem do que ricocheteia no piso e nas paredes, que este
    modelo nao calcula. O ambiente faz o papel desse ricochete.

    Sem raio de sombra: em 8k o custo nao se paga, e o que da leitura a cena e a
    textura, nao a sombra.
    """
    luz = np.full(p.shape[0], 0.46, np.float32)
    for lx, ly, lz, forca in LUZES:
        v = np.stack([lx - p[:, 0], ly - p[:, 1], lz - p[:, 2]], axis=1)
        dist = np.sqrt((v * v).sum(axis=1)) + 1e-6
        lamb = np.clip((v * n).sum(axis=1) / dist, 0.0, 1.0)
        luz += 0.62 * forca * lamb / (1.0 + 0.16 * dist ** 1.6)
    # o teto quase nunca recebe difusa: recebe o ricochete, e pouco mais
    teto = n[:, 1] < -0.9
    luz[teto] = np.maximum(luz[teto], 0.72)
    return np.clip(luz, 0.0, 1.08)      # 1,35 estourava a parede clara em branco


def render(x, z, largura=LARGURA):
    """Devolve (panorama BGR, distancia em metros por pixel)."""
    altura = largura // 2
    o = np.array([x, OLHO, z], np.float32)
    img = np.empty((altura, largura, 3), np.uint8)
    dist_total = np.empty((altura, largura), np.float32)

    passo = max(1, 2 ** 22 // largura)               # fatias, para caber na memoria
    rascunho = None
    for y0 in range(0, altura, passo):
        y1 = min(altura, y0 + passo)
        d = _direcoes(y0, y1, largura, altura)
        inv = _inverso(d)
        t, face = _casca(o, d)
        dono = np.full(d.shape[0], -1, np.int32)
        if rascunho is None or rascunho.a.shape != (y1 - y0, largura):
            rascunho = _Rascunho(y1 - y0, largura)
        _todas_as_caixas(o, inv, d, t, dono, y1 - y0, largura, rascunho)

        p = o[None, :] + d * t[:, None]
        cor = np.zeros((d.shape[0], 3), np.float32)
        n = np.zeros((d.shape[0], 3), np.float32)

        for i, (_, _, nome) in enumerate(_LIMITES):
            sel = (dono < 0) & (face == i)
            if not sel.any():
                continue
            n[sel] = _NORMAIS_CASCA[i]
            if nome in ("parede", "piso"):
                # parede e piso mudam de material conforme o comodo
                tabela = _PAREDE_DA_ZONA if nome == "parede" else _PISO_DA_ZONA
                grupo = _zona(p[sel])
                base = np.nonzero(sel)[0]
                for g, mat in enumerate(tabela):
                    s2 = grupo == g
                    if s2.any():
                        idx = base[s2]
                        cor[idx] = _textura(mat, p[idx], i, MATERIAIS[mat],
                                            d[idx], casca=True)
            else:
                cor[sel] = _textura(nome, p[sel], i, MATERIAIS[nome],
                                    d[sel], casca=True)

        for k, c in enumerate(CAIXAS):
            sel = dono == k
            if not sel.any():
                continue
            lado = _face_caixa(p[sel], c)
            n[sel] = _NORMAIS[lado]
            mat = c[6]
            if mat == "parede":
                grupo = _zona(p[sel])
                base = np.nonzero(sel)[0]
                for g, m2 in enumerate(_PAREDE_DA_ZONA):
                    s2 = grupo == g
                    if s2.any():
                        # `lado[s2]`, e nao `lado`: os pontos vao recortados
                        # por comodo e as faces tem de ir junto. Passava o
                        # vetor inteiro desde sempre, e nao doia porque
                        # nenhuma textura olhava a face — o primeiro material
                        # que olhou (tijolo na adega, concreto na academia)
                        # derrubou o render com "could not be broadcast".
                        cor[base[s2]] = _textura(m2, p[base[s2]], lado[s2],
                                                 MATERIAIS[m2], d[base[s2]])
            else:
                cor[sel] = _textura(mat, p[sel], lado, MATERIAIS[mat],
                                    d[sel])

        cor *= _iluminar(p, n)[:, None]
        img[y0:y1] = np.clip(cor, 0, 255).astype(np.uint8).reshape(y1 - y0, largura, 3)
        dist_total[y0:y1] = t.reshape(y1 - y0, largura)

    return cv2.GaussianBlur(img, (0, 0), 0.5), dist_total


def disparidade_exata(dist, largura=LARGURA_PROF):
    """
    Converte distancia em metros para a disparidade que o visor espera.

    O andar.html reconstroi o raio com r = 1/(1,542·d + 0,125). Invertendo,
    d = (1/r − 0,125)/1,542. Fora dos limites o valor satura: acima de 8 m e
    abaixo de 0,6 m a convencao nao representa, exatamente como no modelo de IA.
    """
    pequeno = cv2.resize(dist, (largura, largura // 2), interpolation=cv2.INTER_AREA)
    with np.errstate(divide="ignore", invalid="ignore"):
        d = (1.0 / np.maximum(pequeno, 1e-3) - 0.125) / 1.542
    return np.clip(np.nan_to_num(d), 0.0, 1.0).astype(np.float32)


def _gravar(img, caminho, q=93):
    ok, buf = cv2.imencode(os.path.splitext(caminho)[1], img,
                           [cv2.IMWRITE_JPEG_QUALITY, q]
                           if caminho.endswith(".jpg") else [])
    if not ok:
        raise RuntimeError("falha ao codificar %s" % caminho)
    buf.tofile(caminho)          # imwrite nao grava em caminho com acento


# Meia largura de ombro, igual ao RAIO_CORPO do maquete.html. Repetido aqui de
# proposito: quem edita uma planta precisa saber por que um corredor de 50 cm
# nao serve, sem ter de abrir o visor para descobrir.
RAIO_CORPO = 0.28

# Altura a partir da qual um movel barra o corpo, igual ao visor. Tapete e
# soleira nao contam — atravessar um tapete nao incomoda ninguem.
ALTURA_QUE_BARRA = 0.35


def comodos_sem_acesso(planta, passo=0.06):
    """
    Os comodos aos quais nao se chega A PE, saindo do primeiro ponto livre.

    POR QUE ISTO EXISTE. O conferir() ja recusava camera dentro de movel, e
    isso funcionava. Mas ele nunca perguntou se da para ANDAR de um comodo ao
    outro — e a casa de 520 m2 passou em tudo, renderizou tres horas e meia,
    foi publicada, e so quando alguem caminhou apareceu que nove dos vinte e
    tres comodos eram inalcancaveis. Um deles, a sala intima de 44,8 m2,
    estava lacrada: eu havia feito as duas paredes dela sem vao nenhum.

    Os outros oito eram MOVEL TAPANDO PORTA. Uma cadeira de jantar encostada
    na parede fechava sozinha o acesso a cozinha, ao lavabo e a lavanderia:
    porta de 80 cm, corpo de 56, cadeira de 46.

    E a mesma familia de defeito dos moveis engolidos — nada quebra, nada
    acusa, so nao funciona.

    A regra e a do visor, nao uma inventada aqui: barra o que tem mais de
    `ALTURA_QUE_BARRA` de altura, com folga de `RAIO_CORPO` em volta.
    """
    larg, fundo = planta["larg"], planta["fundo"]
    nx, nz = int(larg / passo), int(fundo / passo)
    x = ((np.arange(nx) + 0.5) * passo)[:, None]
    z = ((np.arange(nz) + 0.5) * passo)[None, :]

    livre = ((x > 0.2) & (x < larg - 0.2) & (z > 0.2) & (z < fundo - 0.2))
    for c in planta["caixas"]:
        if c[4] - c[1] <= ALTURA_QUE_BARRA:
            continue
        livre &= ~((x > c[0] - RAIO_CORPO) & (x < c[3] + RAIO_CORPO)
                   & (z > c[2] - RAIO_CORPO) & (z < c[5] + RAIO_CORPO))

    # Comeca onde a caminhada comeca: o primeiro ponto de captura em que cabe
    # um corpo. E a mesma escolha que o pontoDeEntrada() do visor faz.
    inicio = None
    for _nome, px, pz in planta["pontos"]:
        i, j = int(px / passo), int(pz / passo)
        if 0 <= i < nx and 0 <= j < nz and livre[i, j]:
            inicio = (i, j)
            break
    if inicio is None:
        return [z[0] for z in planta["zonas"]]

    visto = np.zeros_like(livre)
    pilha = [inicio]
    visto[inicio] = True
    while pilha:
        i, j = pilha.pop()
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = i + di, j + dj
            if 0 <= a < nx and 0 <= b < nz and livre[a, b] and not visto[a, b]:
                visto[a, b] = True
                pilha.append((a, b))

    sem = []
    for nome, x0, x1, z0, z1, _parede, _piso in planta["zonas"]:
        faixa = visto[int(x0 / passo):int(x1 / passo),
                      int(z0 / passo):int(z1 / passo)]
        if not faixa.any():
            sem.append(nome)
    return sem


def conferir(planta):
    """
    Recusa renderizar com ponto de captura ruim.

    Vale o custo: renderizar 14 panoramas de 8k leva meia hora, e ja aconteceu
    de descobrir so no fim que a camera estava DENTRO da cama — o colchao virava
    o chao inteiro. Aqui a checagem custa milissegundos e diz o nome do ponto.
    """
    problemas = []
    vista = planta.get("vista", "campo")
    if vista not in VISTAS:
        # Antes do render, e nao depois. Nome errado aqui custaria meia hora de
        # maquina para sair um imovel de praia com campo na janela.
        problemas.append("vista %r nao existe (ha %s)"
                         % (vista, ", ".join(sorted(VISTAS))))
    for nome in comodos_sem_acesso(planta):
        problemas.append("%s: nao da para chegar andando" % nome)
    for nome, x, z in planta["pontos"]:
        pior = float("inf")
        for c in planta["caixas"]:
            if c[1] > OLHO or c[4] < 0.60:      # movel baixo nao atrapalha a vista
                continue
            dx = max(c[0] - x, 0.0, x - c[3])
            dz = max(c[2] - z, 0.0, z - c[5])
            pior = min(pior, (dx * dx + dz * dz) ** 0.5)
        casca = min(x, planta["larg"] - x, z, planta["fundo"] - z)
        if pior < 0.02:
            problemas.append("%s: DENTRO de um móvel" % nome)
        elif min(pior, casca) < 0.40:
            problemas.append("%s: só %.2f m de folga" % (nome, min(pior, casca)))
    return problemas


def _ja_renderizado(saida, i):
    """
    O ponto ja esta no disco, com foto E profundidade?

    Custou uma hora para virar codigo: uma mansao de 88 pontos leva mais de
    sessenta minutos, e qualquer coisa que interrompa — fechar o terminal,
    reiniciar, a maquina dormir — jogava fora tudo o que ja estava pronto.
    Retomar e o que torna render longo utilizavel.

    Exige os DOIS arquivos: um ponto que gravou a foto e morreu antes do mapa
    de profundidade esta pela metade, e metade e pior do que nada, porque
    parece pronto.
    """
    foto = os.path.join(saida, "ponto_%d.jpg" % i)
    prof = os.path.join(saida, "dist_%d.npy" % i)
    return os.path.exists(foto) and os.path.exists(prof)


def render_planta(planta, largura):
    saida = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "fotos_" + planta["pasta"])
    os.makedirs(saida, exist_ok=True)
    usar(planta)
    print("  %s — %.1f x %.1f m, %d cômodos, %d pontos, %dx%d"
          % (planta["nome"], LARG, FUNDO, len(ZONAS), len(PONTOS),
             largura, largura // 2))
    for i, (nome, x, z) in enumerate(PONTOS):
        if _ja_renderizado(saida, i):
            print("    %2d  %-36s ja estava pronto" % (i, nome))
            continue
        img, dist = render(x, z, largura)
        _gravar(img, os.path.join(saida, "ponto_%d.jpg" % i))
        np.save(os.path.join(saida, "dist_%d.npy" % i), disparidade_exata(dist))
        print("    %2d  %-36s (%.2f, %.2f)  ate %.1f m"
              % (i, nome, x, z, float(np.percentile(dist, 99))))
    print("    gravado em %s\n" % saida)


def main():
    """
      python cena_apartamento.py [largura] [nome-da-planta ...]
    """
    args = sys.argv[1:]
    largura = LARGURA
    if args and args[0].isdigit():
        largura = int(args.pop(0))
    escolhidas = [f() for f in plantas.TODAS]
    if args:
        escolhidas = [p for p in escolhidas
                      if any(a.lower() in p["pasta"] for a in args)]
        if not escolhidas:
            print("  nenhuma planta casa com %s" % args)
            return 1

    for planta in escolhidas:
        ruins = conferir(planta)
        if ruins:
            print("  %s NAO vai ser renderizada:" % planta["nome"])
            for r in ruins:
                print("    %s" % r)
            return 1

    for planta in escolhidas:
        render_planta(planta, largura)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
