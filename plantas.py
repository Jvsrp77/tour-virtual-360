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
PAREDE = 0.12


def _px(x, trechos):
    """Parede de x constante, partida em trechos. O vao entre eles e a porta."""
    return [(x, 0.0, a, x + PAREDE, PE_DIREITO, b, "parede") for a, b in trechos]


def _pz(z, trechos):
    return [(a, 0.0, z, b, PE_DIREITO, z + PAREDE, "parede") for a, b in trechos]


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


TODAS = [apartamento, compacto, cobertura]
