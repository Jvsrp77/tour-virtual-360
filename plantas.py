# -*- coding: utf-8 -*-
"""
As plantas dos imoveis sinteticos, como DADO.

Antes a planta vivia solta no cena_apartamento.py, em variaveis de modulo. Com
um imovel dava; com tres, cada troca exigiria editar o tracador — e o tracador
nao tem nada a ver com onde fica o sofa. Aqui cada planta e uma funcao que
devolve um dicionario, e o tracador so consome.

Convencao: x e a largura, z a profundidade, y a altura. Tudo em metros, com a
origem no canto. Caixa e (x0, y0, z0, x1, y1, z1, material).
"""

PE_DIREITO = 2.70

# Ate que distancia de um ponto de captura a imagem ainda se sustenta. Metade
# do alcance do passeio (PASSEIO_CHEIO = 2,50 m no andar.html), porque o pior
# lugar do passeio e sempre o meio do caminho entre dois pontos.
RAIO_DE_COBERTURA = 1.25
PAREDE = 0.12


def _px(x, trechos):
    """Parede de x constante, partida em trechos. O vao entre eles e a porta."""
    return [(x, 0.0, a, x + PAREDE, PE_DIREITO, b, "parede") for a, b in trechos]


def _pz(z, trechos):
    return [(a, 0.0, z, b, PE_DIREITO, z + PAREDE, "parede") for a, b in trechos]


# A mesma altura de olho do tracador e do andar.html. Repetida aqui de
# proposito: quem edita esta planta nao deveria precisar abrir o tracador para
# entender por que um movel baixo nao bloqueia um ponto de captura.
OLHO = 1.55


def _cabe_camera(x, z, caixas, larg, fundo, folga):
    """
    Espelha o criterio de cena_apartamento.conferir().

    Movel de menos de 60 cm nao atrapalha a vista de quem esta em pe, e o que
    comeca acima da altura dos olhos tambem nao. O resto precisa de folga.
    """
    if min(x, larg - x, z, fundo - z) < folga:
        return False
    for c in caixas:
        if c[1] > OLHO or c[4] < 0.60:
            continue
        dx = max(c[0] - x, 0.0, x - c[3])
        dz = max(c[2] - z, 0.0, z - c[5])
        if (dx * dx + dz * dz) ** 0.5 < folga:
            return False
    return True


def _eixo(a, b, passo):
    """As posicoes ao longo de um lado, com espacamento nunca maior que `passo`."""
    import math
    if b - a <= passo:
        return [(a + b) / 2.0]
    n = int(math.ceil((b - a) / passo))
    return [a + (b - a) * k / n for k in range(n + 1)]


def _pontos_por_cobertura(zonas, caixas, larg, fundo, raio, folga=0.45):
    """
    Escolhe pontos de captura ate que todo lugar onde se pode andar esteja a
    menos de `raio` de algum deles.

    POR QUE NAO GRADE. Tentei grade primeiro e ela erra de um jeito que nao se
    ve no codigo: o filtro de folga REMOVE candidatos perto de movel e nunca os
    repoe. Medido nesta mansao: o hall vazio ficou com nove pontos e a suite
    mobiliada com dois — exatamente ao contrario do necessario, porque comodo
    cheio e onde a foto mais esconde coisa atras dos moveis.

    Aqui o criterio e o que importa de verdade: nenhum lugar caminhavel pode
    ficar longe de um ponto. Escolhe-se sempre o candidato MAIS DISTANTE do que
    ja foi escolhido, ate que o pior caso caiba no raio. Comodo cheio recebe
    mais pontos por consequencia, e nao por regra especial.
    """
    pontos = []
    for nome, x0, x1, z0, z1, _parede, _piso in zonas:
        candidatos = []
        for x in _eixo(x0 + folga, x1 - folga, 0.35):
            for z in _eixo(z0 + folga, z1 - folga, 0.35):
                if _cabe_camera(x, z, caixas, larg, fundo, folga):
                    candidatos.append((x, z))
        if not candidatos:
            continue

        # comeca pelo mais central: e o ponto que um fotografo escolheria
        cx, cz = (x0 + x1) / 2.0, (z0 + z1) / 2.0
        escolhidos = [min(candidatos,
                          key=lambda p: (p[0] - cx) ** 2 + (p[1] - cz) ** 2)]
        longe = [((c[0] - escolhidos[0][0]) ** 2
                  + (c[1] - escolhidos[0][1]) ** 2) ** 0.5 for c in candidatos]
        while True:
            k = max(range(len(candidatos)), key=lambda i: longe[i])
            if longe[k] <= raio:
                break
            novo = candidatos[k]
            escolhidos.append(novo)
            for i, c in enumerate(candidatos):
                d = ((c[0] - novo[0]) ** 2 + (c[1] - novo[1]) ** 2) ** 0.5
                if d < longe[i]:
                    longe[i] = d

        for k, (x, z) in enumerate(escolhidos, 1):
            pontos.append(("%s - %d" % (nome, k), round(x, 2), round(z, 2)))
    return pontos


# ------------------------------------------------------ 1. apartamento padrao

def apartamento():
    larg, fundo = 12.0, 9.0
    wx1, wx2, wx3, wz1 = 4.40, 8.20, 6.30, 4.50
    zonas = [
        ("Sala de estar",   0.00, wx1,  0.00, wz1,   "parede",    "piso"),
        ("Cozinha",         wx1,  wx2,  0.00, wz1,   "cozinha",   "porcelanato"),
        ("Sala de jantar",  wx2,  larg, 0.00, wz1,   "jantar",    "piso"),
        ("Quarto 1",        0.00, wx1,  wz1,  fundo, "parede_q1", "piso"),
        ("Banheiro",        wx1,  wx3,  wz1,  fundo, "banheiro",  "porcelanato"),
        ("Área de serviço", wx3,  wx2,  wz1,  fundo, "servico",   "porcelanato"),
        ("Suíte",           wx2,  larg, wz1,  fundo, "parede_q2", "piso"),
    ]
    caixas = []
    caixas += _px(wx1, [(0.0, 1.90), (2.80, 6.00), (6.90, fundo)])
    caixas += _px(wx2, [(0.0, 1.60), (2.50, 7.20), (8.10, fundo)])
    caixas += _px(wx3, [(wz1, 5.40), (6.30, fundo)])
    caixas += _pz(wz1, [(0.0, 1.30), (2.20, 5.10), (6.00, 9.60), (10.50, larg)])
    caixas += [
        (0.25, 0.00, 1.10, 1.15, 0.38, 3.40, "estofado"),
        (0.25, 0.38, 1.10, 0.52, 0.98, 3.40, "estofado_b"),
        (0.25, 0.38, 1.10, 1.15, 0.72, 1.42, "estofado_b"),
        (0.25, 0.38, 3.08, 1.15, 0.72, 3.40, "estofado_b"),
        (1.45, 0.00, 1.70, 3.05, 0.012, 3.05, "tapete"),
        (1.75, 0.012, 2.00, 2.60, 0.42, 2.70, "madeira"),
        (3.40, 0.00, 0.40, 4.32, 2.05, 2.00, "madeira_esc"),
        (3.48, 0.00, 0.48, 4.26, 0.30, 1.92, "livro_a"),
        (3.48, 0.62, 0.48, 4.26, 0.92, 1.92, "livro_a"),
        (3.48, 1.24, 0.48, 4.26, 1.54, 1.92, "livro_a"),
        (1.90, 0.00, 0.14, 3.20, 0.52, 0.50, "madeira"),
        (2.10, 0.52, 0.20, 3.00, 1.10, 0.26, "pedra"),
        (0.28, 0.00, 3.90, 0.74, 0.90, 4.36, "planta"),

        (4.62, 0.00, 0.20, 5.28, 0.88, 3.60, "madeira"),
        (4.62, 0.88, 0.20, 5.32, 0.94, 3.60, "pedra"),
        (4.62, 1.55, 0.20, 5.12, 2.25, 1.90, "madeira"),
        (4.64, 0.90, 1.95, 5.30, 0.99, 2.75, "metal"),
        (7.35, 0.00, 0.25, 8.08, 1.85, 0.98, "metal"),
        (6.05, 0.00, 1.85, 7.35, 0.74, 2.85, "madeira"),
        (6.05, 0.74, 1.85, 7.35, 0.81, 2.85, "louca"),
        (6.20, 0.00, 2.00, 6.58, 0.45, 2.38, "madeira_esc"),
        (6.20, 0.45, 2.00, 6.58, 0.95, 2.07, "madeira_esc"),
        (6.85, 0.00, 2.00, 7.23, 0.45, 2.38, "madeira_esc"),
        (6.85, 0.45, 2.00, 7.23, 0.95, 2.07, "madeira_esc"),

        (9.30, 0.00, 1.55, 11.10, 0.72, 3.05, "madeira"),
        (9.30, 0.72, 1.55, 11.10, 0.79, 3.05, "louca"),
        (9.45, 0.00, 1.20, 9.85, 0.45, 1.55, "madeira_esc"),
        (10.35, 0.00, 1.20, 10.75, 0.45, 1.55, "madeira_esc"),
        (9.45, 0.00, 3.05, 9.85, 0.45, 3.40, "madeira_esc"),
        (10.35, 0.00, 3.05, 10.75, 0.45, 3.40, "madeira_esc"),
        (8.45, 0.00, 0.25, 9.05, 0.85, 1.95, "madeira_esc"),
        (11.30, 0.00, 3.60, 11.80, 1.35, 4.20, "planta"),

        (0.30, 0.00, 6.55, 2.35, 0.52, 8.70, "estofado"),
        (0.30, 0.52, 6.55, 2.35, 0.62, 8.70, "roupa_cama"),
        (0.30, 0.52, 8.35, 2.35, 0.80, 8.70, "estofado_b"),
        (2.55, 0.00, 8.20, 3.05, 0.55, 8.70, "madeira"),
        (3.35, 0.00, 6.95, 4.28, 2.15, 8.05, "madeira_esc"),
        (0.30, 0.00, 4.80, 1.55, 0.75, 5.40, "madeira"),
        (0.75, 0.00, 5.45, 1.15, 0.46, 5.85, "madeira_esc"),

        (4.62, 0.00, 4.75, 5.55, 0.82, 5.35, "louca"),
        (4.62, 0.82, 4.75, 5.60, 0.88, 5.35, "pedra"),
        (4.64, 0.88, 4.95, 5.20, 1.02, 5.20, "louca"),
        (4.62, 1.35, 4.80, 5.58, 2.05, 4.86, "vidro"),
        (5.85, 0.00, 4.75, 6.25, 0.78, 5.45, "louca"),
        (4.62, 0.00, 7.20, 6.25, 0.10, 8.90, "porcelanato"),
        (4.62, 0.10, 7.18, 4.70, 1.95, 8.90, "vidro"),
        (4.62, 0.10, 7.12, 5.60, 1.95, 7.20, "vidro"),
        (5.56, 0.10, 7.12, 5.64, 1.95, 7.24, "metal"),

        (6.42, 0.00, 4.75, 7.15, 0.92, 5.45, "louca"),
        (7.25, 0.00, 4.75, 8.05, 0.95, 5.45, "metal"),
        (6.42, 1.60, 4.75, 8.08, 2.25, 5.20, "madeira"),
        (6.60, 0.00, 8.10, 7.90, 1.10, 8.30, "metal"),

        (8.55, 0.00, 6.35, 10.45, 0.52, 8.55, "estofado"),
        (8.55, 0.52, 6.35, 10.45, 0.62, 8.55, "roupa_cama"),
        (8.55, 0.52, 8.20, 10.45, 0.80, 8.55, "estofado_b"),
        (10.65, 0.00, 8.05, 11.15, 0.55, 8.55, "madeira"),
        (8.35, 0.00, 4.75, 9.15, 2.15, 5.85, "madeira_esc"),
        (10.75, 0.00, 5.10, 11.55, 0.78, 5.95, "estofado"),
        (10.75, 0.44, 5.10, 11.55, 1.05, 5.30, "estofado_b"),
    ]
    janelas = [
        (1.20, 3.00, 0.00, 0.00, 0.95, 2.10),
        (5.60, 7.00, 0.00, 0.00, 1.05, 2.05),
        (9.40, 11.00, 0.00, 0.00, 0.95, 2.10),
        (larg, larg, 1.40, 3.00, 1.00, 2.05),
        (1.00, 2.60, fundo, fundo, 1.00, 2.05),
        (5.00, 5.80, fundo, fundo, 1.35, 2.10),
        (6.80, 7.70, fundo, fundo, 1.25, 2.10),
        (9.40, 11.00, fundo, fundo, 1.00, 2.05),
    ]
    luzes = [
        (2.20, 2.55, 2.20, 1.00), (6.30, 2.55, 2.20, 0.95),
        (10.10, 2.55, 2.20, 0.95), (2.20, 2.55, 6.80, 0.90),
        (5.40, 2.55, 6.80, 0.85), (7.30, 2.55, 6.80, 0.85),
        (10.10, 2.55, 6.80, 0.90),
        (2.10, 1.60, 0.25, 0.70), (10.20, 1.60, 0.25, 0.65),
        (11.75, 1.55, 2.20, 0.60), (1.80, 1.55, 8.75, 0.60),
        (10.20, 1.55, 8.75, 0.60),
    ]
    pontos = [
        ("Sala de estar - junto à porta", 2.05, 1.30),
        ("Sala de estar - junto à estante", 2.60, 3.70),
        ("Cozinha - junto à bancada", 5.90, 1.10),
        ("Cozinha - junto à mesa", 5.65, 3.90),
        ("Sala de jantar - entrada", 8.90, 3.85),
        ("Sala de jantar - junto à janela", 11.30, 1.05),
        ("Quarto 1 - entrada", 3.05, 5.35),
        ("Quarto 1 - junto à cama", 2.90, 6.25),
        ("Banheiro", 5.55, 6.35),
        ("Banheiro - junto à pia", 5.00, 5.95),
        ("Área de serviço", 7.35, 6.40),
        ("Área de serviço - ao fundo", 7.30, 7.60),
        ("Suíte - entrada", 9.90, 5.80),
        ("Suíte - junto à janela", 11.00, 7.60),
    ]
    return dict(nome="Apartamento 3 dormitórios", pasta="apto_padrao",
                larg=larg, fundo=fundo, zonas=zonas, caixas=caixas,
                janelas=janelas, luzes=luzes, pontos=pontos,
                descricao="Sala de estar, sala de jantar, cozinha, quarto, "
                          "suíte, banheiro e área de serviço. Dois pontos de "
                          "captura em cada cômodo.")


# ----------------------------------------------------------- 2. apto compacto

def compacto():
    """
    Dois ambientes: sala/jantar integrada de um lado, cozinha, banheiro e
    quarto do outro.

    A primeira versao tinha 8,0 x 6,2 m e nao coube: o banheiro ficou com 1,3 m
    de profundidade, quase todo ocupado por louca, e a conferencia acusou quatro
    pontos apertados e um DENTRO da cama. Ampliado para 9,0 x 7,6 m.
    """
    larg, fundo = 9.0, 7.6
    wx1, wz1, wz2 = 4.80, 3.00, 5.00
    zonas = [
        ("Sala integrada", 0.00, wx1,  0.00, fundo, "parede",    "piso"),
        ("Cozinha",        wx1,  larg, 0.00, wz1,   "cozinha",   "porcelanato"),
        ("Banheiro",       wx1,  larg, wz1,  wz2,   "banheiro",  "porcelanato"),
        ("Quarto",         wx1,  larg, wz2,  fundo, "parede_q1", "piso"),
    ]
    caixas = []
    caixas += _px(wx1, [(0.0, 1.00), (1.90, 3.70), (4.50, 6.00), (6.90, fundo)])
    caixas += [(wx1, 0.0, wz1, larg, PE_DIREITO, wz1 + PAREDE, "parede"),
               (wx1, 0.0, wz2, larg, PE_DIREITO, wz2 + PAREDE, "parede")]
    caixas += [
        # sala integrada: estar na frente, refeicoes ao fundo
        (0.25, 0.00, 1.20, 1.15, 0.38, 3.60, "estofado"),
        (0.25, 0.38, 1.20, 0.52, 0.98, 3.60, "estofado_b"),
        (0.25, 0.38, 1.20, 1.15, 0.72, 1.52, "estofado_b"),
        (0.25, 0.38, 3.28, 1.15, 0.72, 3.60, "estofado_b"),
        (1.45, 0.00, 1.60, 3.30, 0.012, 3.60, "tapete"),
        (1.80, 0.012, 2.10, 2.70, 0.42, 2.90, "madeira"),
        (1.90, 0.00, 0.14, 3.40, 0.52, 0.50, "madeira"),
        (2.15, 0.52, 0.20, 3.15, 1.10, 0.26, "pedra"),
        (3.70, 0.00, 0.45, 4.62, 2.05, 2.20, "madeira_esc"),
        (3.78, 0.00, 0.52, 4.55, 0.30, 2.13, "livro_a"),
        (3.78, 0.64, 0.52, 4.55, 0.94, 2.13, "livro_a"),
        (1.60, 0.00, 4.90, 3.40, 0.72, 6.10, "madeira"),
        (1.60, 0.72, 4.90, 3.40, 0.79, 6.10, "louca"),
        (1.75, 0.00, 4.50, 2.15, 0.45, 4.90, "madeira_esc"),
        (2.85, 0.00, 4.50, 3.25, 0.45, 4.90, "madeira_esc"),
        (1.75, 0.00, 6.10, 2.15, 0.45, 6.50, "madeira_esc"),
        (2.85, 0.00, 6.10, 3.25, 0.45, 6.50, "madeira_esc"),
        (0.30, 0.00, 6.90, 0.78, 1.05, 7.38, "planta"),
        # cozinha
        (4.92, 0.00, 0.20, 5.70, 0.88, 2.80, "madeira"),
        (4.92, 0.88, 0.20, 5.74, 0.94, 2.80, "pedra"),
        (4.92, 1.55, 0.20, 5.42, 2.25, 1.60, "madeira"),
        (4.94, 0.90, 1.75, 5.68, 0.99, 2.45, "metal"),
        (8.15, 0.00, 0.25, 8.88, 1.82, 0.98, "metal"),
        (6.60, 0.00, 1.40, 7.90, 0.74, 2.40, "madeira"),
        (6.60, 0.74, 1.40, 7.90, 0.81, 2.40, "louca"),
        (6.75, 0.00, 1.55, 7.15, 0.45, 1.95, "madeira_esc"),
        (7.35, 0.00, 1.55, 7.75, 0.45, 1.95, "madeira_esc"),
        # banheiro
        (4.92, 0.00, 3.30, 6.00, 0.82, 3.85, "louca"),
        (4.92, 0.82, 3.30, 6.04, 0.88, 3.85, "pedra"),
        (4.94, 0.88, 3.45, 5.50, 1.02, 3.72, "louca"),
        (4.92, 1.35, 3.32, 6.02, 2.05, 3.38, "vidro"),
        (6.35, 0.00, 3.30, 6.75, 0.78, 3.95, "louca"),
        (7.30, 0.00, 3.25, 8.88, 0.10, 4.90, "porcelanato"),
        (7.26, 0.10, 3.25, 7.34, 1.95, 4.90, "vidro"),
        (7.30, 0.10, 3.21, 8.88, 1.95, 3.29, "vidro"),
        # quarto
        (5.20, 0.00, 6.00, 7.00, 0.52, 7.45, "estofado"),
        (5.20, 0.52, 6.00, 7.00, 0.62, 7.45, "roupa_cama"),
        (5.20, 0.52, 7.15, 7.00, 0.80, 7.45, "estofado_b"),
        (7.20, 0.00, 6.95, 7.70, 0.55, 7.45, "madeira"),
        (8.10, 0.00, 5.30, 8.90, 2.10, 7.10, "madeira_esc"),
    ]
    janelas = [
        (1.20, 3.00, 0.00, 0.00, 0.95, 2.10),
        (6.20, 7.60, 0.00, 0.00, 1.05, 2.05),
        (1.00, 2.80, fundo, fundo, 1.00, 2.05),
        (5.60, 7.20, fundo, fundo, 1.00, 2.05),
        (larg, larg, 3.60, 4.40, 1.35, 2.10),
    ]
    luzes = [
        (2.40, 2.55, 2.10, 1.00), (2.40, 2.55, 5.60, 0.92),
        (6.90, 2.55, 1.50, 0.92), (6.90, 2.55, 4.00, 0.85),
        (6.90, 2.55, 6.40, 0.90),
        (2.10, 1.60, 0.25, 0.70), (6.90, 1.60, 0.25, 0.62),
        (1.90, 1.55, 7.35, 0.60), (6.40, 1.55, 7.35, 0.60),
        (8.75, 1.55, 4.00, 0.55),
    ]
    pontos = [
        ("Sala integrada - entrada", 2.20, 0.95),
        ("Sala integrada - junto ao sofá", 2.35, 2.60),
        ("Sala integrada - canto de refeições", 2.50, 3.95),
        ("Sala integrada - ao fundo", 3.95, 6.60),
        ("Cozinha", 6.30, 0.80),
        ("Cozinha - junto à mesa", 8.35, 2.20),
        ("Banheiro", 6.30, 4.40),
        ("Quarto - entrada", 5.95, 5.55),
        ("Quarto - junto à janela", 7.55, 6.30),
    ]
    return dict(nome="Apartamento compacto 2 dormitórios", pasta="apto_compacto",
                larg=larg, fundo=fundo, zonas=zonas, caixas=caixas,
                janelas=janelas, luzes=luzes, pontos=pontos,
                descricao="Sala e cozinha integradas, quarto e banheiro. "
                          "Nove pontos de captura.")


# -------------------------------------------------------------- 3. cobertura

def cobertura():
    """Planta maior, com varanda gourmet e dois ambientes sociais."""
    larg, fundo = 14.0, 10.0
    wx1, wx2, wz1 = 5.20, 9.60, 5.00
    zonas = [
        ("Living",          0.00, wx1,  0.00, wz1,   "parede",    "piso"),
        ("Varanda gourmet", wx1,  wx2,  0.00, wz1,   "servico",   "porcelanato"),
        ("Cozinha",         wx2,  larg, 0.00, wz1,   "cozinha",   "porcelanato"),
        ("Home office",     0.00, wx1,  wz1,  fundo, "jantar",    "piso"),
        ("Suíte master",    wx1,  wx2,  wz1,  fundo, "parede_q2", "piso"),
        ("Banheiro",        wx2,  larg, wz1,  fundo, "banheiro",  "porcelanato"),
    ]
    caixas = []
    caixas += _px(wx1, [(0.0, 1.55), (2.60, 6.10), (7.20, fundo)])
    caixas += _px(wx2, [(0.0, 1.70), (2.80, 6.30), (7.40, fundo)])
    caixas += _pz(wz1, [(0.0, 1.60), (2.70, 6.30), (7.40, 10.90), (12.00, larg)])
    caixas += [
        # living
        (0.25, 0.00, 1.30, 1.20, 0.38, 4.10, "estofado"),
        (0.25, 0.38, 1.30, 0.52, 0.98, 4.10, "estofado_b"),
        (1.55, 0.00, 1.90, 3.60, 0.012, 3.70, "tapete"),
        (1.90, 0.012, 2.30, 2.95, 0.42, 3.10, "madeira"),
        (2.05, 0.00, 0.14, 3.60, 0.52, 0.50, "madeira"),
        (2.30, 0.52, 0.20, 3.35, 1.16, 0.26, "pedra"),
        (4.15, 0.00, 0.45, 5.08, 2.05, 2.30, "madeira_esc"),
        (4.22, 0.00, 0.52, 5.01, 0.30, 2.23, "livro_a"),
        (4.22, 0.64, 0.52, 5.01, 0.94, 2.23, "livro_a"),
        (4.22, 1.28, 0.52, 5.01, 1.58, 2.23, "livro_a"),
        (0.30, 0.00, 4.35, 0.78, 1.15, 4.83, "planta"),
        # varanda gourmet
        (5.40, 0.00, 0.22, 6.10, 0.92, 3.10, "pedra"),
        (5.40, 0.92, 0.22, 6.14, 0.98, 3.10, "pedra"),
        (5.42, 0.94, 1.10, 6.08, 1.03, 2.10, "metal"),        # churrasqueira
        (7.10, 0.00, 1.60, 8.90, 0.74, 3.00, "madeira"),      # mesa
        (7.10, 0.74, 1.60, 8.90, 0.81, 3.00, "louca"),
        (7.25, 0.00, 1.25, 7.65, 0.45, 1.60, "madeira_esc"),
        (8.35, 0.00, 1.25, 8.75, 0.45, 1.60, "madeira_esc"),
        (7.25, 0.00, 3.00, 7.65, 0.45, 3.35, "madeira_esc"),
        (8.35, 0.00, 3.00, 8.75, 0.45, 3.35, "madeira_esc"),
        # cozinha
        (9.75, 0.00, 0.22, 10.45, 0.88, 3.40, "madeira"),
        (9.75, 0.88, 0.22, 10.49, 0.94, 3.40, "pedra"),
        (9.75, 1.55, 0.22, 10.25, 2.25, 2.10, "madeira"),
        (13.15, 0.00, 0.30, 13.90, 1.85, 1.05, "metal"),
        (11.30, 0.00, 1.80, 12.80, 0.90, 2.90, "pedra"),      # ilha
        # home office
        (0.25, 0.00, 5.30, 0.95, 0.74, 7.90, "madeira"),      # bancada em L
        (0.95, 0.00, 5.30, 2.85, 0.74, 5.95, "madeira"),
        (1.55, 0.00, 6.10, 1.95, 0.46, 6.50, "madeira_esc"),
        (3.30, 0.00, 5.20, 4.25, 2.10, 6.35, "madeira_esc"),  # armario
        (3.30, 0.00, 7.40, 4.95, 0.42, 9.40, "estofado"),     # sofa cama
        (3.30, 0.42, 7.40, 4.95, 0.52, 9.40, "roupa_cama"),
        # suite master
        (5.60, 0.00, 6.60, 7.70, 0.52, 9.10, "estofado"),
        (5.60, 0.52, 6.60, 7.70, 0.62, 9.10, "roupa_cama"),
        (5.60, 0.52, 8.70, 7.70, 0.82, 9.10, "estofado_b"),
        (7.95, 0.00, 8.55, 8.45, 0.55, 9.10, "madeira"),
        (5.35, 0.00, 8.55, 5.85, 0.55, 9.10, "madeira"),
        (8.60, 0.00, 5.20, 9.48, 2.15, 7.10, "madeira_esc"),
        (5.35, 0.00, 5.25, 6.55, 0.78, 6.05, "estofado"),     # poltrona
        # banheiro
        (9.75, 0.00, 5.25, 11.25, 0.82, 5.90, "louca"),
        (9.75, 0.82, 5.25, 11.30, 0.88, 5.90, "pedra"),
        (9.75, 1.35, 5.28, 11.28, 2.05, 5.34, "vidro"),
        (11.70, 0.00, 5.25, 12.10, 0.78, 5.95, "louca"),
        (12.55, 0.00, 5.20, 13.90, 0.55, 7.40, "louca"),      # banheira
        (9.75, 0.00, 8.20, 11.60, 0.10, 9.85, "porcelanato"),
        (9.75, 0.10, 8.14, 11.60, 2.00, 8.22, "vidro"),
    ]
    janelas = [
        (1.30, 3.40, 0.00, 0.00, 0.95, 2.15),
        (6.20, 8.80, 0.00, 0.00, 0.85, 2.20),
        (10.80, 12.80, 0.00, 0.00, 1.00, 2.05),
        (0.00, 0.00, 5.60, 7.80, 1.00, 2.10),
        (5.80, 7.60, fundo, fundo, 1.00, 2.05),
        (12.30, 13.60, fundo, fundo, 1.30, 2.10),
        (larg, larg, 6.40, 7.80, 1.20, 2.05),
    ]
    luzes = [
        (2.50, 2.55, 2.40, 1.00), (7.30, 2.55, 2.40, 0.95),
        (11.70, 2.55, 2.40, 0.95), (2.40, 2.55, 7.40, 0.90),
        (7.30, 2.55, 7.50, 0.92), (11.70, 2.55, 7.40, 0.85),
        (2.30, 1.60, 0.25, 0.70), (7.40, 1.55, 0.25, 0.72),
        (11.70, 1.60, 0.25, 0.62), (0.25, 1.55, 6.70, 0.60),
        (6.70, 1.55, 9.75, 0.60), (13.75, 1.55, 7.10, 0.58),
    ]
    pontos = [
        ("Living - entrada", 2.30, 1.20),
        ("Living - junto ao sofá", 2.60, 3.35),
        ("Varanda gourmet - churrasqueira", 6.85, 1.05),
        ("Varanda gourmet - mesa", 6.60, 3.85),
        ("Cozinha - ilha", 11.40, 1.10),
        ("Cozinha - junto à bancada", 11.30, 3.95),
        ("Home office - bancada", 2.35, 6.75),
        ("Home office - sofá-cama", 2.30, 8.80),
        ("Suíte master - entrada", 7.05, 5.95),
        ("Suíte master - junto à janela", 8.40, 7.90),
        ("Banheiro - bancada", 10.60, 6.70),
        ("Banheiro - banheira", 11.80, 8.70),
    ]
    return dict(nome="Cobertura com varanda gourmet", pasta="cobertura",
                larg=larg, fundo=fundo, zonas=zonas, caixas=caixas,
                janelas=janelas, luzes=luzes, pontos=pontos,
                descricao="Living, varanda gourmet com churrasqueira, cozinha "
                          "com ilha, home office, suíte master e banheiro com "
                          "banheira. Doze pontos de captura.")


# ------------------------------------------------------------- 4. mansao

def mansao():
    """
    Uma casa grande, com circulacao longa ligando as duas alas.

    Por que ela existe: as tres primeiras plantas sao apartamentos, e nelas
    tudo esta perto de tudo. Imovel grande muda o problema de lugar — entre a
    sala e a suite ha vinte metros de corredor, e e ali que a captura decide
    se o passeio funciona ou nao. Um apartamento perdoa captura esparsa; uma
    mansao nao.

    E ela custa o que custa: trinta e tres pontos de captura contra os catorze
    do apartamento. Esse numero e a informacao mais util desta planta.
    """
    larg, fundo = 22.0, 15.0
    wz1, wz2 = 6.50, 8.30            # corredor entre as duas alas
    # ala da frente
    ax1, ax2, ax3 = 4.20, 12.00, 17.50
    # ala dos fundos
    bx1, bx2, bx3, bx4 = 6.00, 9.00, 15.50, 18.50

    zonas = [
        ("Hall de entrada", 0.00, ax1,  0.00, wz1,   "parede",    "porcelanato"),
        ("Sala de estar",   ax1,  ax2,  0.00, wz1,   "parede",    "piso"),
        ("Sala de jantar",  ax2,  ax3,  0.00, wz1,   "jantar",    "piso"),
        ("Escritório",      ax3,  larg, 0.00, wz1,   "parede_q2", "piso"),
        ("Circulação",      0.00, larg, wz1,  wz2,   "parede",    "porcelanato"),
        ("Cozinha",         0.00, bx1,  wz2,  fundo, "cozinha",   "porcelanato"),
        ("Área de serviço", bx1,  bx2,  wz2,  fundo, "servico",   "porcelanato"),
        ("Suíte master",    bx2,  bx3,  wz2,  fundo, "parede_q1", "piso"),
        ("Banheiro",        bx3,  bx4,  wz2,  fundo, "banheiro",  "porcelanato"),
        ("Quarto 2",        bx4,  larg, wz2,  fundo, "parede_q2", "piso"),
    ]

    caixas = []
    # paredes da ala da frente (o vao entre trechos e a porta)
    caixas += _px(ax1, [(0.00, 2.30), (3.30, wz1 + PAREDE)])
    caixas += _px(ax2, [(0.00, 1.90), (2.90, wz1 + PAREDE)])
    caixas += _px(ax3, [(0.00, 3.10), (4.10, wz1 + PAREDE)])
    # parede entre a ala da frente e o corredor
    caixas += _pz(wz1, [(0.00, 1.40), (2.40, 6.10), (7.10, 13.90),
                        (14.90, 19.30), (20.30, larg)])
    # parede entre o corredor e a ala dos fundos
    caixas += _pz(wz2, [(0.00, 2.60), (3.60, 7.10), (8.10, 11.30),
                        (12.30, 16.60), (17.60, 19.80), (20.80, larg)])
    # paredes da ala dos fundos
    caixas += _px(bx1, [(wz2, 10.60), (11.60, fundo)])
    caixas += _px(bx2, [(wz2, fundo)])
    caixas += _px(bx3, [(wz2, 10.20), (11.20, fundo)])
    caixas += _px(bx4, [(wz2, fundo)])

    caixas += [
        # --- sala de estar: dois sofas e mesa de centro, longe dos pontos
        (5.00, 0.00, 0.30, 5.90, 0.40, 3.60, "estofado"),
        (5.00, 0.40, 0.30, 5.28, 0.95, 3.60, "estofado_b"),
        (9.90, 0.00, 0.30, 10.80, 0.40, 3.60, "estofado"),
        (10.52, 0.40, 0.30, 10.80, 0.95, 3.60, "estofado_b"),
        (6.60, 0.00, 1.20, 9.20, 0.012, 2.80, "tapete"),
        (7.20, 0.012, 1.60, 8.60, 0.40, 2.40, "madeira"),
        (6.40, 0.00, 5.70, 9.60, 0.55, 6.25, "madeira_esc"),
        (6.90, 0.55, 5.85, 9.10, 0.62, 6.10, "vidro"),
        (4.45, 0.00, 5.40, 4.95, 0.95, 6.30, "planta"),

        # --- hall: aparador e espelho
        (0.30, 0.00, 2.60, 0.72, 0.85, 4.20, "madeira_esc"),
        (0.30, 0.85, 2.70, 0.40, 2.00, 4.10, "vidro"),
        (3.30, 0.00, 5.60, 3.95, 1.05, 6.25, "planta"),

        # --- sala de jantar: mesa grande de oito lugares
        (13.90, 0.00, 1.50, 16.30, 0.74, 3.50, "madeira"),
        (13.90, 0.74, 1.50, 16.30, 0.80, 3.50, "vidro"),
        (12.60, 0.00, 1.70, 13.05, 0.46, 2.15, "estofado"),
        (12.60, 0.46, 1.70, 13.05, 1.02, 1.80, "estofado_b"),
        (12.60, 0.00, 2.85, 13.05, 0.46, 3.30, "estofado"),
        (12.60, 0.46, 2.85, 13.05, 1.02, 2.95, "estofado_b"),
        (17.05, 0.00, 1.70, 17.40, 0.46, 2.15, "estofado"),
        (17.05, 0.00, 2.85, 17.40, 0.46, 3.30, "estofado"),
        (12.20, 0.00, 5.30, 16.90, 0.50, 5.95, "madeira_esc"),
        (12.40, 0.50, 5.45, 16.70, 1.35, 5.80, "louca"),

        # --- escritorio: mesa em L e estante
        (18.10, 0.00, 1.10, 21.40, 0.74, 1.80, "madeira"),
        (20.60, 0.00, 1.80, 21.40, 0.74, 3.60, "madeira"),
        (18.30, 0.74, 1.25, 19.60, 0.80, 1.65, "vidro"),
        (17.80, 0.00, 4.90, 21.60, 2.10, 5.50, "madeira_esc"),
        (17.95, 0.00, 5.00, 21.45, 0.32, 5.40, "livro_a"),
        (17.95, 0.66, 5.00, 21.45, 0.98, 5.40, "livro_a"),
        (17.95, 1.32, 5.00, 21.45, 1.64, 5.40, "livro_a"),

        # --- circulacao: aparador comprido e plantas, rente as paredes
        (2.90, 0.00, 6.75, 5.40, 0.82, 7.05, "madeira_esc"),
        (11.60, 0.00, 7.80, 13.40, 0.82, 8.10, "madeira_esc"),
        (0.25, 0.00, 6.80, 0.85, 1.10, 7.40, "planta"),
        (21.20, 0.00, 7.60, 21.80, 1.10, 8.20, "planta"),

        # --- cozinha: ilha central e bancadas
        (0.30, 0.00, 8.70, 1.00, 0.90, 13.60, "cozinha"),
        (0.30, 0.90, 8.70, 1.00, 0.96, 13.60, "pedra"),
        (0.30, 1.60, 8.70, 0.95, 2.30, 11.40, "madeira"),
        (2.90, 0.00, 11.60, 5.30, 0.92, 13.10, "madeira_esc"),
        (2.90, 0.92, 11.60, 5.30, 0.98, 13.10, "pedra"),
        (5.20, 0.00, 8.70, 5.85, 1.95, 10.60, "metal"),
        (1.60, 0.00, 14.10, 4.40, 0.78, 14.70, "madeira"),

        # --- area de servico: tanque e maquinas
        (6.30, 0.00, 14.00, 8.70, 0.88, 14.70, "servico"),
        (6.30, 0.88, 14.00, 8.70, 0.94, 14.70, "pedra"),
        (6.30, 0.00, 8.60, 7.20, 0.85, 9.50, "metal"),
        (7.40, 0.00, 8.60, 8.30, 0.85, 9.50, "metal"),

        # --- suite master: cama de casal e armario
        (11.30, 0.00, 12.40, 13.30, 0.52, 14.50, "madeira_esc"),
        (11.30, 0.52, 12.40, 13.30, 0.74, 14.50, "roupa_cama"),
        (11.45, 0.74, 13.90, 12.15, 0.86, 14.35, "roupa_cama"),
        (12.45, 0.74, 13.90, 13.15, 0.86, 14.35, "roupa_cama"),
        (9.20, 0.00, 12.20, 9.85, 2.30, 14.70, "madeira_esc"),
        (14.60, 0.00, 8.60, 15.35, 2.30, 11.40, "madeira_esc"),
        (9.30, 0.00, 8.60, 10.90, 0.012, 11.30, "tapete"),

        # --- banheiro: banheira, pia e box
        (15.70, 0.00, 13.30, 18.30, 0.62, 14.80, "louca"),
        (15.70, 0.00, 8.55, 18.30, 0.86, 9.25, "madeira_esc"),
        (15.70, 0.86, 8.55, 18.30, 0.92, 9.25, "pedra"),
        (16.00, 0.92, 8.70, 17.10, 1.06, 9.10, "louca"),
        (15.70, 0.00, 10.20, 17.10, 2.10, 11.60, "vidro"),

        # --- quarto 2: cama de solteiro e escrivaninha
        (18.80, 0.00, 12.90, 20.20, 0.50, 14.70, "madeira_esc"),
        (18.80, 0.50, 12.90, 20.20, 0.70, 14.70, "roupa_cama"),
        (18.95, 0.70, 14.20, 19.60, 0.82, 14.60, "roupa_cama"),
        (20.90, 0.00, 8.60, 21.70, 0.74, 10.40, "madeira"),
        (18.70, 0.00, 8.60, 19.35, 2.20, 10.60, "madeira_esc"),
    ]

    janelas = [
        (0.60, 2.40, 0.00, 0.00, 1.00, 2.10),
        (5.20, 7.40, 0.00, 0.00, 0.85, 2.30),
        (8.80, 11.00, 0.00, 0.00, 0.85, 2.30),
        (13.40, 16.20, 0.00, 0.00, 1.00, 2.20),
        (18.40, 21.00, 0.00, 0.00, 1.00, 2.20),
        (0.00, 0.00, 1.60, 4.40, 1.05, 2.15),
        (0.00, 0.00, 9.40, 12.60, 1.10, 2.10),
        (larg, larg, 1.70, 4.60, 1.05, 2.15),
        (larg, larg, 9.60, 12.40, 1.10, 2.10),
        (1.40, 4.60, fundo, fundo, 1.10, 2.10),
        (10.00, 12.80, fundo, fundo, 1.00, 2.20),
        (16.10, 17.90, fundo, fundo, 1.45, 2.20),
        (19.60, 21.40, fundo, fundo, 1.10, 2.10),
    ]

    luzes = [
        (2.10, 2.55, 3.20, 0.95), (6.60, 2.55, 2.00, 1.00),
        (9.80, 2.55, 2.00, 1.00), (8.10, 2.55, 5.00, 0.90),
        (14.70, 2.55, 2.50, 1.00), (15.20, 2.55, 5.20, 0.85),
        (19.70, 2.55, 2.20, 0.95), (19.70, 2.55, 5.00, 0.85),
        (3.60, 2.55, 7.40, 0.80), (11.00, 2.55, 7.40, 0.80),
        (18.40, 2.55, 7.40, 0.80),
        (3.00, 2.55, 10.60, 0.95), (3.00, 2.55, 13.40, 0.90),
        (7.50, 2.55, 11.60, 0.85),
        (11.20, 2.55, 10.40, 0.95), (13.60, 2.55, 13.00, 0.88),
        (17.00, 2.55, 11.60, 0.90),
        (20.20, 2.55, 11.60, 0.92),
        (7.00, 1.35, 1.95, 0.55), (15.10, 1.30, 2.50, 0.55),
        (12.30, 1.05, 13.20, 0.50),
    ]

    pontos = _pontos_por_cobertura(zonas, caixas, larg, fundo,
                                   raio=RAIO_DE_COBERTURA)

    return dict(nome="Mansão com 330 m²", pasta="mansao",
                larg=larg, fundo=fundo, zonas=zonas, caixas=caixas,
                janelas=janelas, luzes=luzes, pontos=pontos,
                descricao="Hall, sala de estar, sala de jantar, escritório, "
                          "cozinha, área de serviço, suíte master, banheiro e "
                          "quarto, ligados por uma circulação de 22 metros. "
                          "Trinta e três pontos de captura.")


# ----------------------------------------------------- 5. casa pavilhao

def pavilhao():
    """
    Uma casa aberta: um unico volume, tres paredes de vidro, quase sem movel.

    Por que ela existe, e por que e diferente da mansao: a mansao tem dez
    ambientes e vinte e dois metros de corredor, e serve para mostrar o custo
    de capturar espaco compartimentado. Esta e o oposto — 150 m2 de estar,
    jantar e cozinha SEM uma parede entre eles, com vao livre de ponta a ponta.

    E o melhor caso possivel para a caminhada, e nao por acaso: o borrao do
    passeio nasce do que a foto nao viu atras dos moveis e das paredes. Onde
    nao ha parede nem movel alto, quase nao ha o que esconder — e quase nao ha
    o que o programa precise inventar.

    Os vidros sao a razao de ser dela. Ate agora janela era um retangulo bege
    chapado; com o ceu por direcao, uma parede de doze metros de vidro passa a
    valer alguma coisa.
    """
    larg, fundo = 20.0, 11.0
    wx = 13.60                    # unica parede que divide a casa
    wz = 6.20                     # e a que separa suite do banho

    zonas = [
        ("Living integrado", 0.00, wx,   0.00, fundo, "parede",    "piso"),
        ("Suíte",            wx,   larg, 0.00, wz,    "parede_q1", "piso"),
        ("Banho",            wx,   larg, wz,   fundo, "banheiro",  "porcelanato"),
    ]

    caixas = []
    # duas paredes internas na casa inteira, e so
    caixas += _px(wx, [(0.00, 3.10), (4.20, fundo)])
    caixas += _pz(wz, [(wx, 16.40), (17.50, larg)])

    caixas += [
        # --- estar: um sofa baixo e uma mesa de centro, longe do meio
        (1.60, 0.00, 1.10, 4.60, 0.38, 2.00, "estofado"),
        (1.60, 0.38, 1.10, 4.60, 0.76, 1.38, "estofado_b"),
        (2.20, 0.00, 2.60, 3.90, 0.012, 3.60, "tapete"),
        (2.50, 0.012, 2.90, 3.60, 0.36, 3.30, "madeira"),

        # --- jantar: mesa comprida, cadeiras baixas
        (6.60, 0.00, 4.30, 10.20, 0.73, 5.60, "madeira"),
        (6.60, 0.73, 4.30, 10.20, 0.78, 5.60, "vidro"),

        # --- cozinha: uma ilha e uma bancada rente ao fundo
        (6.80, 0.00, 8.40, 10.60, 0.90, 9.40, "cozinha"),
        (6.80, 0.90, 8.40, 10.60, 0.96, 9.40, "pedra"),
        (0.30, 0.00, 9.90, 5.40, 0.88, 10.60, "cozinha"),
        (0.30, 0.88, 9.90, 5.40, 0.94, 10.60, "pedra"),
        (11.80, 0.00, 9.60, 13.20, 2.20, 10.60, "madeira_esc"),

        # --- suite: cama e um armario rente a parede
        (15.40, 0.00, 1.60, 17.60, 0.50, 3.80, "madeira_esc"),
        (15.40, 0.50, 1.60, 17.60, 0.72, 3.80, "roupa_cama"),
        (15.55, 0.72, 3.20, 16.30, 0.84, 3.65, "roupa_cama"),
        (16.70, 0.72, 3.20, 17.45, 0.84, 3.65, "roupa_cama"),
        (19.10, 0.00, 0.70, 19.75, 2.30, 4.60, "madeira_esc"),

        # --- banho: banheira junto ao vidro e uma bancada
        (17.80, 0.00, 9.30, 19.70, 0.60, 10.60, "louca"),
        (13.90, 0.00, 6.60, 16.60, 0.86, 7.30, "madeira_esc"),
        (13.90, 0.86, 6.60, 16.60, 0.92, 7.30, "pedra"),
        (14.20, 0.92, 6.75, 15.10, 1.06, 7.15, "louca"),
    ]

    # Tres paredes de vidro no living, do chao quase ao teto. E o ponto da casa.
    janelas = [
        (0.50, 13.10, 0.00, 0.00, 0.35, 2.45),
        (0.50, 13.10, fundo, fundo, 0.35, 2.45),
        (0.00, 0.00, 0.60, 10.40, 0.35, 2.45),
        (larg, larg, 0.80, 5.40, 0.60, 2.30),
        (larg, larg, 6.90, 10.20, 0.90, 2.30),
    ]

    luzes = [
        (3.20, 2.55, 2.40, 0.95), (3.20, 2.55, 8.20, 0.90),
        (8.40, 2.55, 2.40, 0.95), (8.40, 2.55, 5.00, 1.00),
        (8.70, 2.55, 8.90, 0.95), (11.80, 2.55, 5.50, 0.88),
        (16.80, 2.55, 3.00, 0.92), (16.80, 2.55, 8.60, 0.90),
        (2.80, 1.10, 3.10, 0.45),
    ]

    pontos = _pontos_por_cobertura(zonas, caixas, larg, fundo,
                                   raio=RAIO_DE_COBERTURA)

    return dict(nome="Casa pavilhão, 220 m²", pasta="pavilhao",
                larg=larg, fundo=fundo, zonas=zonas, caixas=caixas,
                janelas=janelas, luzes=luzes, pontos=pontos,
                descricao="Estar, jantar e cozinha num vão único de 150 m², "
                          "sem parede entre eles, com três fachadas de vidro. "
                          "Suíte e banho no outro volume.")


# ------------------------------------------- 6. o quarto (imovel real)

def quarto():
    """
    Um quarto de verdade, reconstruido a partir de fotos e de um escaneamento.

    AS CINCO PLANTAS ANTERIORES SAO INVENTADAS. Esta nao: a disposicao foi lida
    das 48 fotos e do panorama costurado delas, e as medidas partiram da caixa
    de um escaneamento de celular.

    Por que ela existe: o dono tentou varias vezes capturar o proprio quarto em
    360 e o resultado sempre saiu com borrao. A medicao explicou por que — as
    48 fotos se partem em grupos de duas a cinco, porque ele mudava de lugar
    entre os cliques, e nao existe encaixe correto para fotos tiradas de pontos
    diferentes. O que ele queria era andar sem deformacao, e isso a foto nao
    entrega de um ponto so: entrega a GEOMETRIA.

    O QUE ELA NAO E: uma foto do quarto. E um modelo dele, como as outras cinco
    — cores chapadas, movel aproximado. Ganha em andar sem deformar e medir com
    a trena; perde em parecer a coisa real.

    DUAS COISAS QUE EU CHUTEI, e que so o dono corrige:

    1. O tamanho. A caixa do escaneamento deu 2,65 x 3,02 m, mas nela nao
       caberia a camera em lugar nenhum com estes moveis dentro — o
       escaneamento pegou so parte do comodo. O numero abaixo e o menor que
       acomoda o que aparece nas fotos.

    2. O guarda-roupa. No panorama ele aparece como duas colunas brancas
       ladeando a cabeceira, com a cama encaixada entre elas — o modelo de
       ponte, comum em quarto pequeno. Se for armario corrido numa parede, a
       planta muda e o chao livre tambem.
    """
    larg, fundo = 3.20, 3.45

    zonas = [
        ("Quarto", 0.00, larg, 0.00, fundo, "parede_q1", "piso"),
    ]

    caixas = [
        # --- guarda-roupa em ponte: duas colunas e a travessa sobre a cama
        (0.00, 0.00, 0.00, 0.52, PE_DIREITO, 0.62, "laminado"),
        (2.68, 0.00, 0.00, larg, PE_DIREITO, 0.62, "laminado"),
        (0.00, 1.95, 0.00, larg, PE_DIREITO, 0.62, "laminado"),
        (0.50, 0.00, 0.10, 0.54, 1.75, 0.52, "metal"),          # puxadores
        (2.66, 0.00, 0.10, 2.70, 1.75, 0.52, "metal"),

        # --- cama de casal encaixada entre as colunas
        (0.91, 0.00, 0.08, 2.29, 0.40, 1.96, "madeira_esc"),
        (0.91, 0.40, 0.08, 2.29, 0.64, 1.96, "roupa_cama"),
        (1.02, 0.64, 0.18, 1.56, 0.78, 0.56, "roupa_cama"),     # travesseiros
        (1.64, 0.64, 0.18, 2.18, 0.78, 0.56, "roupa_cama"),

        # --- prateleira da cabeceira, com os enfeites do panorama
        (0.91, 1.22, 0.62, 2.29, 1.28, 0.86, "madeira_esc"),
        (1.10, 1.28, 0.66, 1.24, 1.46, 0.82, "louca"),
        (1.48, 1.28, 0.66, 1.66, 1.50, 0.82, "livro_a"),
        (1.92, 1.28, 0.66, 2.08, 1.48, 0.82, "louca"),

        # --- escrivaninha na parede do fundo, com a cadeira
        (0.30, 0.00, 3.00, 2.20, 0.74, fundo, "madeira_esc"),
        (0.55, 0.74, 3.08, 1.35, 0.78, 3.40, "vidro"),          # notebook aberto
        (1.55, 0.74, 3.06, 2.05, 1.12, 3.38, "vidro"),          # monitor
        (0.95, 0.00, 2.40, 1.55, 0.46, 2.88, "estofado"),
        (0.95, 0.46, 2.40, 1.55, 1.02, 2.54, "estofado_b"),     # encosto

        # --- ar-condicionado alto, sobre a janela
        (3.00, 1.98, 1.20, larg, 2.30, 2.10, "metal"),
    ]

    # A janela de madeira com veneziana, na parede da direita. E a unica
    # abertura do quarto, e com o ceu por direcao ela vira vista de verdade.
    janelas = [
        (larg, larg, 1.25, 2.20, 1.05, 2.05),
    ]

    luzes = [
        (1.50, 2.55, 1.90, 1.00),          # a do teto
        (2.85, 1.55, 1.70, 0.55),          # a que entra pela janela
        (1.50, 1.24, 0.90, 0.35),          # a da cabeceira
    ]

    # folga de 0,42 e nao 0,45: a regra padrao exige 90 cm de corredor
    # livre, e o vao ao lado de uma cama num quarto real tem 60. O limite
    # do conferir e 0,40, entao ainda sobra margem.
    pontos = _pontos_por_cobertura(zonas, caixas, larg, fundo,
                                   raio=RAIO_DE_COBERTURA, folga=0.42)

    return dict(nome="Quarto — reconstruído do real", pasta="quarto",
                larg=larg, fundo=fundo, zonas=zonas, caixas=caixas,
                janelas=janelas, luzes=luzes, pontos=pontos,
                descricao="Quarto reconstruído a partir de fotos e de um "
                          "escaneamento de celular. Medidas aproximadas: vêm "
                          "de foto e de escaneamento, não de trena.")


TODAS = [apartamento, compacto, cobertura, mansao, pavilhao, quarto]
