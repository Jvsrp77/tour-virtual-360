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

# ------------------------------------------------- moveis que se repetem
#
# POR QUE ISTO EXISTE. A casa grande tem 22 comodos. Escrita caixa por caixa
# daria umas quinhentas linhas de tuplas de sete numeros, e um numero trocado
# no meio nao apareceria em revisao nenhuma — apareceria no render, horas
# depois, com a cama atravessando o guarda-roupa.
#
# Cada funcao aqui devolve a lista de caixas de um movel JA MONTADO, nas
# proporcoes certas. Quem escreve a planta diz onde o movel fica, e nao de que
# ele e feito por dentro.
#
# Convencao de orientacao: `frente` diz para que lado o movel encara, em
# "x+", "x-", "z+" ou "z-". Um sofa que encara z+ tem o encosto em z0.


def _cama(x0, z0, larg, comp, madeira="madeira_esc", roupa="roupa_cama"):
    """
    Cama com estrado, colchao, cabeceira e dois travesseiros.

    A cabeceira fica sempre em z0: a cama encosta pela cabeca, e deixar isso
    implicito evita o erro de pendurar o quadro atras dos pes.
    """
    x1, z1 = x0 + larg, z0 + comp
    meio = (x0 + x1) / 2.0
    return [
        (x0, 0.08, z0, x1, 0.42, z1, madeira),
        (x0, 0.42, z0, x1, 0.66, z1, roupa),
        (x0, 0.0, z0 - 0.07, x1, 1.05, z0, madeira),            # cabeceira
        (x0 + 0.12, 0.66, z0 + 0.10, meio - 0.05, 0.80, z0 + 0.54, roupa),
        (meio + 0.05, 0.66, z0 + 0.10, x1 - 0.12, 0.80, z0 + 0.54, roupa),
    ]


def _mesa(x0, z0, x1, z1, alt=0.76, tampo="madeira_esc", pe="madeira_esc"):
    """Mesa com tampo e quatro pes. Pe de 7 cm: mais fino some no render."""
    e, r = 0.07, 0.09
    return [
        (x0, alt - 0.05, z0, x1, alt, z1, tampo),
        (x0 + r, 0.0, z0 + r, x0 + r + e, alt - 0.05, z0 + r + e, pe),
        (x1 - r - e, 0.0, z0 + r, x1 - r, alt - 0.05, z0 + r + e, pe),
        (x0 + r, 0.0, z1 - r - e, x0 + r + e, alt - 0.05, z1 - r, pe),
        (x1 - r - e, 0.0, z1 - r - e, x1 - r, alt - 0.05, z1 - r, pe),
    ]


def _cadeira(x, z, frente="z+", assento="estofado", encosto="estofado_b"):
    """Cadeira de 46 cm. O encosto fica do lado OPOSTO ao que ela encara."""
    a, h, e = 0.46, 0.45, 0.07
    caixas = [(x, 0.0, z, x + a, h, z + a, assento)]
    if frente == "z+":
        caixas.append((x, h, z, x + a, h + 0.50, z + e, encosto))
    elif frente == "z-":
        caixas.append((x, h, z + a - e, x + a, h + 0.50, z + a, encosto))
    elif frente == "x+":
        caixas.append((x, h, z, x + e, h + 0.50, z + a, encosto))
    else:
        caixas.append((x + a - e, h, z, x + a, h + 0.50, z + a, encosto))
    return caixas


def _sofa(x0, z0, x1, z1, frente, couro="couro"):
    """Sofa com base, assento, encosto e dois bracos."""
    b = 0.24
    caixas = [(x0, 0.0, z0, x1, 0.42, z1, couro),
              (x0, 0.42, z0, x1, 0.64, z1, couro)]
    if frente in ("z+", "z-"):
        ze = (z0, z0 + b) if frente == "z+" else (z1 - b, z1)
        caixas += [(x0, 0.64, ze[0], x1, 1.04, ze[1], couro),
                   (x0, 0.42, z0, x0 + b, 0.80, z1, couro),
                   (x1 - b, 0.42, z0, x1, 0.80, z1, couro)]
    else:
        xe = (x0, x0 + b) if frente == "x+" else (x1 - b, x1)
        caixas += [(xe[0], 0.64, z0, xe[1], 1.04, z1, couro),
                   (x0, 0.42, z0, x1, 0.80, z0 + b, couro),
                   (x0, 0.42, z1 - b, x1, 0.80, z1, couro)]
    return caixas


def _armario(x0, z0, x1, z1, frente, alt=PE_DIREITO, corpo="laminado"):
    """Armario do chao ao teto, com dois puxadores na face da frente."""
    caixas = [(x0, 0.0, z0, x1, alt, z1, corpo)]
    a, b = 0.95, 1.45                    # alturas dos puxadores
    if frente in ("z+", "z-"):
        z = (z0 - 0.025, z0) if frente == "z-" else (z1, z1 + 0.025)
        t = (x1 - x0) / 3.0
        caixas += [(x0 + t * 0.7, a, z[0], x0 + t * 1.0, b, z[1], "metal"),
                   (x0 + t * 2.0, a, z[0], x0 + t * 2.3, b, z[1], "metal")]
    else:
        x = (x0 - 0.025, x0) if frente == "x-" else (x1, x1 + 0.025)
        t = (z1 - z0) / 3.0
        caixas += [(x[0], a, z0 + t * 0.7, x[1], b, z0 + t * 1.0, "metal"),
                   (x[0], a, z0 + t * 2.0, x[1], b, z0 + t * 2.3, "metal")]
    return caixas


def _quadro(parede, valor, lado, a, b, y0, y1):
    """
    Um quadro pendurado: moldura rente a parede, tela SALIENTE a frente dela.

    A tela precisa sair da moldura. Rente, o tracador decide no fio da navalha
    qual das duas o raio encontrou, e a tela aparece e some conforme o angulo.

    `parede` e "x" ou "z"; `lado` vale +1 quando a parede olha para o lado
    positivo do eixo (parede no comeco do comodo) e -1 quando olha para tras.
    """
    fundo, sai = 0.055, 0.095
    if parede == "z":
        m = (valor, valor + fundo) if lado > 0 else (valor - fundo, valor)
        t = ((valor + fundo, valor + sai) if lado > 0
             else (valor - sai, valor - fundo))
        return [(a, y0, m[0], b, y1, m[1], "madeira_esc"),
                (a + 0.10, y0 + 0.10, t[0], b - 0.10, y1 - 0.10, t[1], "quadro")]
    m = (valor, valor + fundo) if lado > 0 else (valor - fundo, valor)
    t = ((valor + fundo, valor + sai) if lado > 0
         else (valor - sai, valor - fundo))
    return [(m[0], y0, a, m[1], y1, b, "madeira_esc"),
            (t[0], y0 + 0.10, a + 0.10, t[1], y1 - 0.10, b - 0.10, "quadro")]


def _televisao(parede, valor, lado, a, b, chao=True):
    """Painel na parede, tela saliente e, opcionalmente, o rack embaixo."""
    p, s = 0.09, 0.14
    y0, y1 = 0.95, 1.80
    if parede == "z":
        pm = (valor, valor + p) if lado > 0 else (valor - p, valor)
        tm = ((valor + p, valor + s) if lado > 0 else (valor - s, valor - p))
        caixas = [(a, 0.32, pm[0], b, 2.15, pm[1], "madeira_esc"),
                  (a + 0.22, y0, tm[0], b - 0.22, y1, tm[1], "tela")]
        if chao:
            rm = (valor, valor + 0.42) if lado > 0 else (valor - 0.42, valor)
            caixas.append((a, 0.0, rm[0], b, 0.32, rm[1], "madeira_esc"))
        return caixas
    pm = (valor, valor + p) if lado > 0 else (valor - p, valor)
    tm = ((valor + p, valor + s) if lado > 0 else (valor - s, valor - p))
    caixas = [(pm[0], 0.32, a, pm[1], 2.15, b, "madeira_esc"),
              (tm[0], y0, a + 0.22, tm[1], y1, b - 0.22, "tela")]
    if chao:
        rm = (valor, valor + 0.42) if lado > 0 else (valor - 0.42, valor)
        caixas.append((rm[0], 0.0, a, rm[1], 0.32, b, "madeira_esc"))
    return caixas


def _bancada(x0, z0, x1, z1, alt=0.92, tampo="marmore", corpo="laminado"):
    """Bancada de cozinha: corpo com rodape recuado e tampo de pedra."""
    return [
        (x0, 0.10, z0, x1, alt - 0.04, z1, corpo),
        (x0 + 0.05, 0.0, z0 + 0.05, x1 - 0.05, 0.10, z1 - 0.05, "metal"),
        (x0 - 0.015, alt - 0.04, z0 - 0.015, x1 + 0.015, alt, z1 + 0.015, tampo),
    ]


def _vaso(x, z, raio=0.24, alt=1.35, pote="pedra", folha="planta"):
    """Vaso com planta. Duas caixas, porque so o verde parece brinquedo."""
    return [
        (x - raio, 0.0, z - raio, x + raio, 0.42, z + raio, pote),
        (x - raio * 1.25, 0.42, z - raio * 1.25,
         x + raio * 1.25, alt, z + raio * 1.25, folha),
    ]


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
    caixas += _px(wx1, [(0.0, 1.75), (2.95, 6.00), (6.90, fundo)])
    caixas += _px(wx2, [(0.0, 1.45), (2.65, 7.20), (8.10, fundo)])
    caixas += _px(wx3, [(wz1, 5.40), (6.30, fundo)])
    caixas += _pz(wz1, [(0.0, 1.30), (2.20, 5.10), (6.00, 9.45), (10.65, larg)])
    caixas += [
        (0.25, 0.00, 1.10, 1.15, 0.38, 3.40, "estofado"),
        (0.25, 0.38, 1.10, 0.52, 0.98, 3.40, "estofado_b"),
        (0.25, 0.38, 1.10, 1.15, 0.72, 1.42, "estofado_b"),
        (0.25, 0.38, 3.08, 1.15, 0.72, 3.40, "estofado_b"),
        (1.45, 0.00, 1.70, 3.05, 0.012, 3.05, "tapete"),
        (1.75, 0.012, 2.00, 2.60, 0.42, 2.70, "madeira"),
        (3.40, 0.00, 0.40, 4.32, 2.05, 2.00, "madeira_esc"),
        (3.37, 0.00, 0.48, 4.37, 0.30, 1.92, "livro_a"),
        (3.37, 0.62, 0.48, 4.37, 0.92, 1.92, "livro_a"),
        (3.37, 1.24, 0.48, 4.37, 1.54, 1.92, "livro_a"),
        (1.90, 0.00, 0.14, 3.20, 0.52, 0.50, "madeira"),
        (2.10, 0.52, 0.20, 3.00, 1.10, 0.26, "pedra"),
        (0.28, 0.00, 3.90, 0.74, 0.90, 4.36, "planta"),

        (4.62, 0.00, 0.20, 5.28, 0.88, 1.65, "madeira"),
        (4.62, 0.88, 0.20, 5.32, 0.94, 1.65, "pedra"),
        (4.62, 0.00, 3.05, 5.28, 0.88, 3.60, "madeira"),
        (4.62, 0.88, 3.05, 5.32, 0.94, 3.60, "pedra"),
        (4.62, 1.55, 0.20, 5.12, 2.25, 1.65, "madeira"),
        (4.64, 0.90, 1.95, 5.30, 0.99, 2.75, "metal"),
        (7.35, 0.00, 0.25, 8.08, 1.85, 0.98, "metal"),
        (6.05, 0.00, 1.85, 7.35, 0.74, 2.85, "madeira"),
        (6.05, 0.74, 1.85, 7.35, 0.81, 2.85, "louca"),
        (6.20, 0.00, 1.82, 6.58, 0.45, 2.88, "madeira_esc"),
        (6.20, 0.45, 2.00, 6.58, 0.95, 2.07, "madeira_esc"),
        (6.85, 0.00, 1.82, 7.23, 0.45, 2.88, "madeira_esc"),
        (6.85, 0.45, 2.00, 7.23, 0.95, 2.07, "madeira_esc"),

        (9.30, 0.00, 1.55, 11.10, 0.72, 3.05, "madeira"),
        (9.30, 0.72, 1.55, 11.10, 0.79, 3.05, "louca"),
        (9.45, 0.00, 1.20, 9.85, 0.45, 1.55, "madeira_esc"),
        (10.35, 0.00, 1.20, 10.75, 0.45, 1.55, "madeira_esc"),
        (9.45, 0.00, 3.05, 9.85, 0.45, 3.40, "madeira_esc"),
        (10.35, 0.00, 3.05, 10.75, 0.45, 3.40, "madeira_esc"),
        (8.45, 0.00, 0.25, 9.05, 0.85, 1.20, "madeira_esc"),
        (11.30, 0.00, 3.60, 11.80, 1.35, 4.20, "planta"),

        (0.30, 0.00, 6.55, 2.35, 0.52, 8.70, "estofado"),
        (0.30, 0.52, 6.55, 2.35, 0.62, 8.70, "roupa_cama"),
        (0.30, 0.52, 8.35, 2.35, 0.80, 8.70, "estofado_b"),
        (2.55, 0.00, 8.20, 3.05, 0.55, 8.70, "madeira"),
        (3.35, 0.00, 6.95, 4.28, 2.15, 8.05, "madeira_esc"),
        # terminava em x 1,55 e avancava 25 cm sobre a porta de 0,90 m
        # (x 1,30..2,20) que serve banheiro, quarto 1 e area de servico.
        # Encurtado para parar antes da soleira.
        (0.30, 0.00, 4.80, 1.25, 0.75, 5.40, "madeira"),
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
    caixas += _px(wx1, [(0.0, 0.85), (2.05, 3.70), (4.50, 6.00), (6.90, fundo)])
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
        (3.70, 0.00, 0.45, 4.62, 2.05, 0.60, "madeira_esc"),
        (3.67, 0.00, 0.52, 4.65, 0.30, 2.13, "livro_a"),
        (3.67, 0.64, 0.52, 4.65, 0.94, 2.13, "livro_a"),
        (1.60, 0.00, 4.90, 3.40, 0.72, 6.10, "madeira"),
        (1.60, 0.72, 4.90, 3.40, 0.79, 6.10, "louca"),
        (1.75, 0.00, 4.50, 2.15, 0.45, 4.90, "madeira_esc"),
        (2.85, 0.00, 4.50, 3.25, 0.45, 4.90, "madeira_esc"),
        (1.75, 0.00, 6.10, 2.15, 0.45, 6.50, "madeira_esc"),
        (2.85, 0.00, 6.10, 3.25, 0.45, 6.50, "madeira_esc"),
        (0.30, 0.00, 6.90, 0.78, 1.05, 7.38, "planta"),
        # cozinha
        (4.92, 0.00, 0.20, 5.70, 0.88, 0.75, "madeira"),
        (4.92, 0.88, 0.20, 5.74, 0.94, 0.75, "pedra"),
        (4.92, 0.00, 2.20, 5.70, 0.88, 2.80, "madeira"),
        (4.92, 0.88, 2.20, 5.74, 0.94, 2.80, "pedra"),
        (4.92, 1.55, 0.20, 5.42, 2.25, 0.75, "madeira"),
        (4.94, 0.90, 2.25, 5.68, 0.99, 2.75, "metal"),
        (8.15, 0.00, 0.25, 8.88, 1.82, 0.98, "metal"),
        (6.60, 0.00, 1.40, 7.90, 0.74, 2.40, "madeira"),
        (6.60, 0.74, 1.40, 7.90, 0.81, 2.40, "louca"),
        (6.75, 0.00, 1.37, 7.15, 0.45, 2.43, "madeira_esc"),
        (7.35, 0.00, 1.37, 7.75, 0.45, 2.43, "madeira_esc"),
        # banheiro
        # a bancada comecava em z 3,30 e avancava sobre a porta do banheiro
        # (z 3,70..4,50), deixando 0,64 m de vao. Recuou 16 cm, para caber
        # entre a parede e a soleira.
        (4.92, 0.00, 3.14, 6.00, 0.82, 3.69, "louca"),
        (4.92, 0.82, 3.14, 6.04, 0.88, 3.69, "pedra"),
        (4.94, 0.88, 3.29, 5.50, 1.02, 3.56, "louca"),
        (4.92, 1.35, 3.16, 6.02, 2.05, 3.22, "vidro"),
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
    caixas += _px(wx1, [(0.0, 1.40), (2.75, 6.10), (7.20, fundo)])
    caixas += _px(wx2, [(0.0, 1.55), (2.95, 6.30), (7.40, fundo)])
    caixas += _pz(wz1, [(0.0, 1.60), (2.70, 6.15), (7.55, 10.75), (12.15, larg)])
    caixas += [
        # living
        (0.25, 0.00, 1.30, 1.20, 0.38, 4.10, "estofado"),
        (0.25, 0.38, 1.30, 0.52, 0.98, 4.10, "estofado_b"),
        (1.55, 0.00, 1.90, 3.60, 0.012, 3.70, "tapete"),
        (1.90, 0.012, 2.30, 2.95, 0.42, 3.10, "madeira"),
        (2.05, 0.00, 0.14, 3.60, 0.52, 0.50, "madeira"),
        (2.30, 0.52, 0.20, 3.35, 1.16, 0.26, "pedra"),
        (4.15, 0.00, 0.45, 5.08, 2.05, 1.25, "madeira_esc"),
        (4.12, 0.00, 0.52, 5.11, 0.30, 2.23, "livro_a"),
        (4.12, 0.64, 0.52, 5.11, 0.94, 2.23, "livro_a"),
        (4.12, 1.28, 0.52, 5.11, 1.58, 2.23, "livro_a"),
        (0.30, 0.00, 4.35, 0.78, 1.15, 4.83, "planta"),
        # varanda gourmet
        (5.40, 0.00, 0.22, 6.10, 0.92, 1.30, "pedra"),
        (5.40, 0.00, 2.90, 6.10, 0.92, 3.10, "pedra"),
        (5.40, 0.92, 0.22, 6.14, 0.98, 3.10, "pedra"),
        (5.42, 0.94, 1.10, 6.08, 1.03, 2.10, "metal"),        # churrasqueira
        # a mesa da varanda chegava a x 8,90 e deixava 0,70 m ate a parede da
        # cozinha, bem em frente a porta de 1,40 m (z 1,55..2,95). Recuou e
        # encurtou: 1,05 m de passagem de um lado, 0,81 m da churrasqueira.
        (6.95, 0.00, 1.60, 8.55, 0.74, 3.00, "madeira"),      # mesa
        (6.95, 0.74, 1.60, 8.55, 0.81, 3.00, "louca"),
        (7.10, 0.00, 1.25, 7.50, 0.45, 1.60, "madeira_esc"),
        (8.00, 0.00, 1.25, 8.40, 0.45, 1.60, "madeira_esc"),
        (7.10, 0.00, 3.00, 7.50, 0.45, 3.35, "madeira_esc"),
        (8.00, 0.00, 3.00, 8.40, 0.45, 3.35, "madeira_esc"),
        # cozinha
        (9.75, 0.00, 0.22, 10.45, 0.88, 1.35, "madeira"),
        (9.75, 0.88, 0.22, 10.49, 0.94, 1.35, "pedra"),
        (9.75, 0.00, 3.10, 10.45, 0.88, 3.40, "madeira"),
        (9.75, 1.55, 0.22, 10.25, 2.25, 2.10, "madeira"),
        (13.15, 0.00, 0.30, 13.90, 1.85, 1.05, "metal"),
        (11.30, 0.00, 1.80, 12.80, 0.90, 2.90, "pedra"),      # ilha
        # home office
        (0.25, 0.00, 5.30, 0.95, 0.74, 7.90, "madeira"),      # bancada em L
        # a mesa ficava encostada na soleira e tapava INTEIRA a porta de
        # 1,10 m (x 1,60..2,70) que liga o living ao home office. Recuou
        # 1,70 m para o fundo do comodo.
        (0.95, 0.00, 7.00, 2.85, 0.74, 7.65, "madeira"),
        (1.55, 0.00, 6.10, 1.95, 0.46, 6.50, "madeira_esc"),
        (3.30, 0.00, 5.60, 4.25, 2.10, 6.75, "madeira_esc"),  # armario
        (3.30, 0.00, 7.40, 4.95, 0.42, 9.40, "estofado"),     # sofa cama
        (3.30, 0.42, 7.40, 4.95, 0.52, 9.40, "roupa_cama"),
        # suite master
        (5.60, 0.00, 6.60, 7.70, 0.52, 9.10, "estofado"),
        (5.60, 0.52, 6.60, 7.70, 0.62, 9.10, "roupa_cama"),
        (5.60, 0.52, 8.70, 7.70, 0.82, 9.10, "estofado_b"),
        (7.95, 0.00, 8.55, 8.45, 0.55, 9.10, "madeira"),
        (5.35, 0.00, 8.55, 5.85, 0.55, 9.10, "madeira"),
        (8.60, 0.00, 5.20, 9.48, 2.15, 6.20, "madeira_esc"),
        (5.35, 0.00, 5.25, 6.55, 0.78, 6.05, "estofado"),     # poltrona
        # banheiro
        # a bancada nascia em z 6,30, que e a propria soleira do banheiro:
        # da porta de 1,10 m sobravam 0,45 m. Correu para o fundo, entre a
        # banheira e o box.
        (9.75, 0.00, 7.45, 11.25, 0.82, 8.10, "louca"),
        (9.75, 0.82, 7.45, 11.30, 0.88, 8.10, "pedra"),
        (9.75, 1.35, 5.28, 11.28, 2.05, 5.34, "vidro"),
        (11.70, 0.00, 6.30, 12.10, 0.78, 7.00, "louca"),
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
        # a bancada recuou para z 7,00..7,65 ao liberar a porta; o ponto
        # seguiu, senao a camera olhava para onde o movel nao esta mais
        ("Home office - bancada", 2.35, 6.45),
        ("Home office - sofá-cama", 2.30, 8.80),
        ("Suíte master - entrada", 7.05, 5.95),
        ("Suíte master - junto à janela", 8.40, 7.90),
        # idem: a bancada do banheiro foi para z 7,45..8,10, e o ponto
        # antigo ficou DENTRO dela
        ("Banheiro - bancada", 10.60, 6.90),
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
        (17.95, 0.00, 4.87, 21.45, 0.32, 5.53, "livro_a"),
        (17.95, 0.66, 4.87, 21.45, 0.98, 5.53, "livro_a"),
        (17.95, 1.32, 4.87, 21.45, 1.64, 5.53, "livro_a"),

        # --- circulacao: aparador comprido e plantas, rente as paredes
        (2.90, 0.00, 6.75, 5.40, 0.82, 7.05, "madeira_esc"),
        # o aparador comecava em x 11,90 e comia 40 cm da porta de 1,00 m
        # da suite master (x 11,30..12,30), deixando 0,58 m. Correu para
        # leste, onde encosta em parede cheia.
        (12.40, 0.00, 7.80, 14.20, 0.82, 8.10, "madeira_esc"),
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
        (15.70, 0.00, 8.75, 18.30, 0.86, 9.45, "madeira_esc"),
        (15.70, 0.86, 8.75, 18.30, 0.92, 9.45, "pedra"),
        (16.00, 0.92, 8.90, 17.10, 1.06, 9.30, "louca"),
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


# ------------------------------------------- 7. a casa grande (520 m2)

def casa_grande():
    """
    Uma casa inteira: 26 x 20 m, 520 m2, 23 comodos, com vista para o mar.

    O QUE ELA TEM QUE AS OUTRAS NAO TINHAM. As plantas anteriores mostravam um
    pedaco de imovel — um apartamento, um pavilhao aberto, um quarto. Esta tem
    a casa COMPLETA, com as tres coisas que faltavam para parecer uma casa de
    verdade e nao uma maquete de sala:

    1. Circulacao. Um corredor de 19 m ligando a ala social a intima, e um
       corredor menor servindo os quartos do fundo. Andar por corredor e
       metade da experiencia de visitar uma casa, e era exatamente o que
       nenhuma planta anterior oferecia.
    2. Servico. Despensa, lavanderia, deposito, rouparia. Comodo feio tambem
       conta: quem compra casa de 520 m2 pergunta onde fica a lavanderia.
    3. Materiais de verdade em cada ambiente. Tijolo aparente na adega,
       concreto na academia e na varanda, azulejo nos banhos, marmore nas
       bancadas, couro nos sofas, palha na varanda.

    OS COMODOS, em tres faixas:

      z 0,0 a 8,4   social   varanda gourmet, sala de estar, hall, sala de
                             jantar, copa, cozinha, despensa, lavabo,
                             lavanderia, deposito
      z 8,4 a 10,2  corredor a espinha da casa, de x 7,2 ate a parede do fundo
      z 10,2 a 20   intima   suite master com closet e banho, quarto 2, quarto
                             3, banho social, rouparia, sala de estudos,
                             adega, academia, sala intima

    O QUE ELA NAO E: um imovel que existe. E inventada, como as cinco
    primeiras — e ao contrario do quarto, que saiu de fotos de um quarto real.
    Serve para demonstrar navegacao, medicao e caminhada numa casa do tamanho
    que o corretor de alto padrao vende, nao para julgar arquitetura.
    """
    larg, fundo = 26.00, 20.00

    zonas = [
        # social
        ("Varanda gourmet",   0.00,  5.40,  0.00,  8.40, "concreto", "porcelanato"),
        ("Sala de estar",     5.40, 12.60,  0.00,  8.40, "parede", "piso"),
        ("Hall de entrada",  12.60, 16.20,  0.00,  4.20, "parede", "porcelanato"),
        ("Sala de jantar",   16.20, 21.00,  0.00,  4.20, "jantar", "piso"),
        ("Despensa",         21.00, 23.40,  0.00,  2.20, "servico", "porcelanato"),
        ("Lavabo",           21.00, 23.40,  2.20,  4.20, "azulejo", "porcelanato"),
        ("Depósito",         23.40, 26.00,  0.00,  4.20, "servico", "porcelanato"),
        ("Copa",             12.60, 18.00,  4.20,  8.40, "cozinha", "porcelanato"),
        ("Cozinha",          18.00, 23.40,  4.20,  8.40, "cozinha", "porcelanato"),
        ("Lavanderia",       23.40, 26.00,  4.20,  8.40, "servico", "porcelanato"),
        # circulacao
        ("Corredor",          7.20, 26.00,  8.40, 10.20, "parede", "piso"),
        # intima
        ("Suíte master",      0.00,  7.20,  8.40, 16.40, "parede_q1", "piso"),
        ("Closet",            0.00,  3.60, 16.40, 20.00, "parede_q1", "piso"),
        ("Banho da suíte",    3.60,  7.20, 16.40, 20.00, "azulejo", "porcelanato"),
        ("Rouparia",          7.20,  9.80, 10.20, 13.20, "servico", "porcelanato"),
        ("Banho social",      9.80, 12.60, 10.20, 13.20, "azulejo", "porcelanato"),
        ("Quarto 2",          7.20, 12.60, 13.20, 20.00, "parede_q2", "piso"),
        ("Corredor íntimo",  12.60, 14.40, 10.20, 20.00, "parede", "piso"),
        ("Sala de estudos",  14.40, 18.20, 10.20, 13.60, "parede", "piso"),
        ("Adega",            18.20, 21.40, 10.20, 13.60, "tijolo", "pedra"),
        ("Academia",         21.40, 26.00, 10.20, 13.60, "concreto", "porcelanato"),
        ("Quarto 3",         14.40, 19.00, 13.60, 20.00, "parede_q1", "piso"),
        ("Sala íntima",      19.00, 26.00, 13.60, 20.00, "parede", "piso"),
    ]

    # As paredes. O vao entre dois trechos e a porta — e cada porta aqui foi
    # conferida contra o comodo que ela serve: comodo sem porta e comodo que
    # o visitante ve pela planta e nunca alcanca andando.
    paredes = (
        _px(5.40,  [(0.00, 2.20), (6.20, 8.40)]) +
        _px(12.60, [(0.00, 1.40), (2.40, 5.40), (6.40, 8.40)]) +
        _px(16.20, [(0.00, 1.00), (3.20, 4.20)]) +
        _px(18.00, [(4.20, 5.00), (7.00, 8.40)]) +
        _px(21.00, [(0.00, 0.80), (1.60, 2.70), (3.70, 4.20)]) +
        _px(23.40, [(0.00, 5.30), (6.30, 8.40)]) +
        _px(7.20,  [(8.40, 9.10), (10.00, 20.00)]) +
        _px(3.60,  [(16.40, 20.00)]) +
        _px(9.80,  [(10.20, 13.20)]) +
        _px(12.60, [(10.20, 11.20), (12.00, 14.20), (15.10, 20.00)]) +
        _px(14.40, [(10.20, 15.20), (16.10, 20.00)]) +
        _px(18.20, [(10.20, 11.60), (12.40, 13.60)]) +
        _px(21.40, [(10.20, 11.60), (12.40, 13.60)]) +
        _px(19.00, [(13.60, 20.00)]) +
        _pz(2.20,  [(21.00, 23.40)]) +
        _pz(4.20,  [(12.60, 13.60), (15.00, 16.60), (17.60, 19.40),
                    (20.40, 24.10), (25.30, 26.00)]) +
        _pz(8.40,  [(0.00, 11.00), (12.20, 14.40), (15.60, 26.00)]) +
        _pz(10.20, [(7.20, 8.00), (8.80, 12.60), (14.40, 15.60),
                    (16.50, 19.40), (20.30, 23.00), (23.90, 26.00)]) +
        _pz(13.20, [(7.20, 12.60)]) +
        _pz(13.60, [(14.40, 23.60), (24.60, 26.00)]) +
        _pz(16.40, [(0.00, 1.20), (2.10, 5.00), (5.90, 7.20)])
    )

    moveis = (
        # ---------------------------------------------- varanda gourmet
        _bancada(0.20, 0.40, 1.10, 3.60) +
        [(0.20, 0.92, 1.30, 1.10, 2.15, 2.50, "tijolo"),       # churrasqueira
         (0.20, 2.15, 1.40, 1.15, 2.52, 2.40, "inox"),         # coifa
         (4.70, 0.00, 0.30, 5.25, 0.50, 2.80, "pedra"),        # jardineira
         (4.70, 0.50, 0.35, 5.25, 1.25, 2.75, "planta")] +
        _mesa(1.90, 4.20, 4.70, 6.60, tampo="madeira_clara") +
        _cadeira(2.10, 3.60, "z+", "palha", "palha") +
        _cadeira(2.90, 3.60, "z+", "palha", "palha") +
        _cadeira(3.70, 3.60, "z+", "palha", "palha") +
        _cadeira(2.10, 6.70, "z-", "palha", "palha") +
        _cadeira(2.90, 6.70, "z-", "palha", "palha") +
        _cadeira(3.70, 6.70, "z-", "palha", "palha") +
        _vaso(4.90, 7.60) +

        # ---------------------------------------------- sala de estar
        _sofa(6.40, 3.80, 7.30, 6.80, "x+") +
        _sofa(8.60, 2.40, 9.60, 3.30, "z+") +
        _sofa(10.40, 2.40, 11.40, 3.30, "z+") +
        _televisao("x", 12.60, -1, 4.20, 7.00) +
        _quadro("x", 5.40 + PAREDE, 1, 6.50, 7.90, 1.15, 2.05) +
        [(7.60, 0.00, 3.60, 11.80, 0.012, 7.20, "tapete"),
         (8.80, 0.38, 4.60, 10.60, 0.44, 6.00, "vidro"),       # mesa de centro
         (9.20, 0.00, 4.90, 10.20, 0.38, 5.70, "madeira_esc"),
         (5.55, 0.00, 0.70, 6.15, 2.30, 2.90, "madeira_esc"),  # estante
         (5.52, 0.30, 0.78, 6.18, 2.15, 2.82, "livro_a"),
         (11.90, 0.00, 7.40, 12.10, 1.55, 7.60, "metal"),      # luminaria
         (11.76, 1.55, 7.26, 12.24, 1.85, 7.74, "roupa_cama")] +
        _vaso(12.10, 1.00) +

        # ---------------------------------------------- hall de entrada
        [(12.80, 0.30, 0.20, 13.20, 0.86, 1.30, "madeira_esc"),
         (13.40, 0.00, 0.60, 15.60, 0.012, 2.40, "tapete")] +
        _quadro("x", 12.60 + PAREDE, 1, 2.60, 3.90, 1.20, 2.10) +
        _vaso(15.60, 3.70) +

        # ---------------------------------------------- sala de jantar
        _mesa(17.10, 1.30, 20.10, 2.90) +
        _cadeira(17.40, 0.70, "z+") + _cadeira(18.30, 0.70, "z+") +
        _cadeira(19.20, 0.70, "z+") + _cadeira(17.40, 3.00, "z-") +
        _cadeira(18.30, 3.00, "z-") + _cadeira(19.20, 3.00, "z-") +
        # SEM cabeceira, de proposito. A mesa de 3,0 m fica numa sala de
        # 4,8 m: sobram 0,90 m de cada lado, e uma cadeira de 0,46 m em
        # qualquer das pontas reduz a passagem a 0,44 m. Do lado x- isso
        # trancava a ala de servico INTEIRA — despensa, lavabo,
        # deposito, cozinha e lavanderia, que so se alcanca por aqui.
        # Seis lugares numa mesa de 3,0 m ja e o arranjo normal.
        _quadro("z", 4.20, -1, 17.80, 19.30, 1.25, 2.15) +
        [(16.32, 0.00, 3.55, 18.40, 0.88, 4.05, "madeira_esc"),   # buffet
         (18.10, 2.35, 1.90, 19.10, 2.60, 2.40, "vidro")] +       # lustre

        # ---------------------------------------------- copa
        _mesa(13.40, 5.40, 15.60, 7.00, alt=0.75, tampo="marmore") +
        _cadeira(13.70, 4.80, "z+") + _cadeira(14.60, 4.80, "z+") +
        _cadeira(13.70, 7.10, "z-") + _cadeira(14.60, 7.10, "z-") +
        _armario(16.60, 7.60, 17.90, 8.25, "z-", alt=2.20) +
        _vaso(17.40, 4.90) +

        # ---------------------------------------------- cozinha
        _bancada(18.20, 7.70, 23.20, 8.25) +
        # a bancada da parede oeste corria de z 4,35 a 7,20 — ou seja, por
        # cima inteira da porta de 2,00 m que liga a copa a cozinha. Porta
        # emparedada por movel: aparece na planta, nao existe para quem anda.
        # A cozinha fica com a bancada do sul (5 m) e a ilha, que ja bastam.
        _bancada(20.20, 5.40, 22.60, 6.60) +                       # ilha
        [(18.20, 1.60, 7.95, 23.20, 2.45, 8.25, "laminado"),       # aereos
         # a geladeira ficava em x 22,40..23,20: a esquina onde o corredor
         # norte da cozinha encontra o corredor leste que vai a lavanderia.
         # Sozinha ela estreitava os dois para 0,20 m, e trancava deposito
         # e lavanderia. Foi para a ponta oeste da mesma parede.
         (18.20, 0.00, 4.35, 19.00, 1.95, 5.10, "inox"),           # geladeira
         (20.60, 0.88, 7.72, 21.80, 0.94, 8.20, "inox"),           # cooktop
         (20.50, 1.95, 7.80, 21.90, 2.30, 8.25, "inox"),           # coifa
         (20.60, 0.00, 6.70, 20.95, 0.72, 7.05, "metal"),
         (20.52, 0.72, 6.62, 21.03, 0.80, 7.13, "couro"),
         (21.60, 0.00, 6.70, 21.95, 0.72, 7.05, "metal"),
         (21.52, 0.72, 6.62, 22.03, 0.80, 7.13, "couro")] +

        # ---------------------------------------------- despensa / lavabo
        # Prateleira de um lado so. Com as duas sobrava um corredor de 80
        # cm, e a amostragem nao achava UM ponto onde a camera coubesse: a
        # despensa aparecia na planta e o visitante nunca chegava nela.
        [(22.97, 0.30, 0.20, 23.40, 2.30, 2.05, "laminado"),
         (22.75, 0.78, 2.55, 23.40, 0.88, 3.15, "marmore"),        # cuba
         (23.33, 1.05, 2.60, 23.40, 1.95, 3.10, "vidro"),          # espelho
         # o vaso nascia a 15 cm da porta do lavabo e comia 25 cm do vao de
         # 1,00 m. Foi para o fundo do comodo, longe da soleira.
         (22.60, 0.00, 3.45, 23.10, 0.78, 4.15, "louca")] +

        # ---------------------------------------------- deposito / lavanderia
        [(23.50, 0.20, 0.10, 24.00, 2.40, 4.10, "laminado"),
         (25.00, 0.00, 1.00, 25.90, 1.20, 2.40, "madeira_esc"),
         (23.60, 0.00, 6.40, 24.25, 0.88, 7.05, "inox"),           # maquina
         (24.35, 0.00, 6.40, 25.00, 0.88, 7.05, "inox")] +         # secadora
        _bancada(23.50, 7.70, 25.90, 8.25, tampo="inox") +
        _armario(25.20, 4.35, 25.90, 6.60, "x-", alt=2.20) +

        # ---------------------------------------------- corredor
        _quadro("z", 8.40 + PAREDE, 1, 17.00, 18.60, 1.20, 2.00) +
        _quadro("z", 8.40 + PAREDE, 1, 20.00, 21.40, 1.20, 2.00) +
        [(8.20, 0.30, 8.55, 10.40, 0.85, 8.95, "madeira_esc")] +
        _vaso(25.30, 9.30) +

        # ---------------------------------------------- suite master
        _cama(2.40, 8.59, 1.90, 2.10) +
        _televisao("z", 16.40, -1, 2.20, 4.60, chao=False) +
        _sofa(5.40, 13.60, 6.60, 14.80, "x-") +
        [(1.90, 0.00, 8.60, 2.35, 0.55, 9.05, "madeira_esc"),
         (4.35, 0.00, 8.60, 4.80, 0.55, 9.05, "madeira_esc"),
         (1.80, 0.00, 10.80, 5.00, 0.012, 13.20, "tapete"),
         (0.06, 0.00, 9.40, 0.22, 2.50, 15.40, "cortina")] +
        _vaso(6.60, 12.40) +

        # ---------------------------------------------- closet / banho suite
        _armario(0.15, 16.60, 0.80, 19.80, "x+") +
        _armario(2.80, 16.60, 3.45, 19.80, "x-") +
        [(1.20, 0.00, 17.80, 2.40, 0.90, 18.90, "madeira_esc"),
         (1.40, 0.00, 19.20, 2.20, 0.45, 19.60, "estofado")] +
        _bancada(3.80, 16.60, 4.90, 17.20) +
        [(3.80, 1.10, 16.53, 4.90, 2.10, 16.60, "vidro"),          # espelho
         (6.10, 0.00, 18.40, 7.05, 0.58, 19.80, "louca"),          # banheira
         (3.75, 0.00, 18.80, 5.30, 2.10, 19.85, "vidro"),          # box
         (5.60, 0.00, 17.40, 6.10, 0.78, 18.10, "louca")] +

        # ---------------------------------------------- rouparia / banho social
        _armario(7.40, 11.55, 9.60, 12.20, "z+", alt=2.30) +
        [(7.40, 0.30, 12.60, 9.60, 2.30, 13.05, "laminado")] +
        _bancada(10.00, 10.40, 11.80, 11.00) +
        [(10.00, 1.10, 10.33, 11.80, 2.05, 10.40, "vidro"),
         (12.00, 0.00, 10.50, 12.50, 0.78, 11.20, "louca"),
         (9.95, 0.00, 12.00, 11.40, 2.10, 13.05, "vidro")] +

        # ---------------------------------------------- quarto 2
        _cama(9.00, 13.39, 1.60, 2.00) +
        _armario(7.35, 17.60, 8.00, 19.80, "x+") +
        _mesa(10.80, 18.60, 12.45, 19.60, alt=0.74) +
        _cadeira(11.40, 17.90, "z-") +
        _televisao("x", 12.60, -1, 15.30, 17.10, chao=False) +
        [(8.55, 0.00, 13.40, 8.95, 0.52, 13.85, "madeira_esc"),
         (10.65, 0.00, 13.40, 11.05, 0.52, 13.85, "madeira_esc"),
         (8.60, 0.00, 15.60, 11.60, 0.012, 18.00, "tapete")] +

        # ---------------------------------------------- corredor intimo
        _quadro("x", 14.40, -1, 17.40, 18.80, 1.20, 2.00) +
        [(12.75, 0.30, 18.90, 13.15, 0.85, 19.70, "madeira_esc")] +

        # ---------------------------------------------- sala de estudos
        _mesa(15.00, 11.40, 17.60, 12.60, alt=0.74) +
        _cadeira(16.00, 12.62, "z-") +
        [(14.55, 0.00, 12.40, 15.00, 2.30, 13.45, "madeira_esc"),
         (14.52, 0.30, 12.48, 15.03, 2.15, 13.38, "livro_a"),
         (15.40, 0.00, 13.10, 17.80, 2.30, 13.52, "madeira_esc"),
         (15.48, 0.30, 13.07, 17.72, 2.15, 13.55, "livro_a")] +

        # ---------------------------------------------- adega
        _mesa(19.30, 11.60, 20.40, 12.70, alt=1.05) +
        [(18.35, 0.20, 10.40, 18.85, 2.30, 13.40, "madeira_esc"),
         (20.85, 0.20, 10.40, 21.35, 2.30, 13.40, "madeira_esc"),
         (19.50, 0.00, 12.90, 19.85, 0.72, 13.25, "metal"),
         (19.42, 0.72, 12.82, 19.93, 0.80, 13.33, "couro"),
         (20.05, 0.00, 12.90, 20.40, 0.72, 13.25, "metal"),
         (19.97, 0.72, 12.82, 20.48, 0.80, 13.33, "couro")] +

        # ---------------------------------------------- academia
        # espelho em DOIS panos: o do meio virou a porta da sala intima.
        # Antes ele atravessava a parede inteira e lacrava o comodo.
        [(21.60, 0.60, 13.46, 23.50, 2.40, 13.52, "vidro"),        # espelho
         (24.70, 0.60, 13.46, 25.80, 2.40, 13.52, "vidro"),
         (22.00, 0.00, 10.60, 22.90, 0.25, 12.00, "metal"),        # esteira
         (22.00, 0.25, 10.60, 22.90, 1.35, 10.90, "tela"),
         (23.60, 0.00, 11.20, 24.10, 0.48, 12.40, "estofado"),
         (25.20, 0.00, 10.50, 25.80, 0.70, 12.60, "metal")] +

        # ---------------------------------------------- quarto 3
        _cama(15.90, 13.79, 1.50, 2.00) +
        _armario(18.20, 17.40, 18.85, 19.70, "x-") +
        _mesa(14.60, 18.40, 16.30, 19.40, alt=0.74) +
        _cadeira(15.20, 17.70, "z-") +
        [(15.45, 0.00, 13.80, 15.85, 0.52, 14.25, "madeira_esc"),
         (17.45, 0.00, 13.80, 17.85, 0.52, 14.25, "madeira_esc"),
         (15.40, 0.00, 16.00, 18.00, 0.012, 18.40, "tapete")] +

        # ---------------------------------------------- sala intima
        _sofa(20.20, 15.00, 23.80, 16.00, "z-") +
        _sofa(24.60, 14.40, 25.70, 15.50, "x-") +
        _televisao("z", 13.60 + PAREDE, 1, 20.80, 23.40) +
        [(20.00, 0.00, 13.90, 24.20, 0.012, 15.00, "tapete"),
         (21.60, 0.38, 14.20, 22.80, 0.44, 14.80, "vidro"),
         (21.90, 0.00, 14.32, 22.50, 0.38, 14.68, "madeira_esc"),
         (19.15, 0.00, 17.00, 19.70, 2.30, 19.60, "madeira_esc"),
         (19.12, 0.30, 17.08, 19.73, 2.15, 19.52, "livro_a"),
         (20.20, 0.00, 19.80, 25.40, 2.50, 19.96, "cortina")] +
        _vaso(25.40, 18.60)
    )

    caixas = paredes + moveis

    janelas = [
        # fachada da frente
        (0.60, 4.80, 0.00, 0.00, 0.30, 2.40),        # varanda, vao aberto
        (6.40, 11.60, 0.00, 0.00, 0.50, 2.40),       # sala de estar
        (13.60, 15.20, 0.00, 0.00, 0.00, 2.20),      # porta de entrada
        (17.40, 20.40, 0.00, 0.00, 0.80, 2.30),      # sala de jantar
        (24.20, 25.40, 0.00, 0.00, 1.40, 2.20),      # deposito
        # lateral esquerda
        (0.00, 0.00, 1.20, 7.20, 0.30, 2.40),        # varanda
        (0.00, 0.00, 9.60, 15.20, 0.60, 2.30),       # suite master
        (0.00, 0.00, 17.60, 19.20, 1.50, 2.30),      # closet
        # fundos
        (4.60, 6.40, 20.00, 20.00, 1.30, 2.30),      # banho da suite
        (8.40, 11.60, 20.00, 20.00, 0.80, 2.30),     # quarto 2
        (13.00, 14.00, 20.00, 20.00, 1.60, 2.40),    # corredor intimo
        (15.40, 18.20, 20.00, 20.00, 0.80, 2.30),    # quarto 3
        (20.40, 25.20, 20.00, 20.00, 0.50, 2.40),    # sala intima
        # lateral direita
        (26.00, 26.00, 5.40, 7.40, 1.30, 2.20),      # lavanderia
        (26.00, 26.00, 8.80, 9.80, 1.50, 2.40),      # corredor
        (26.00, 26.00, 10.80, 13.00, 0.80, 2.30),    # academia
        (26.00, 26.00, 15.00, 19.00, 0.70, 2.30),    # sala intima
    ]

    luzes = [
        (2.70, 2.55, 4.20, 0.85),      (9.00, 2.55, 4.20, 1.00),
        (14.40, 2.55, 2.10, 0.80),     (18.90, 2.55, 2.10, 0.95),
        (22.20, 2.55, 1.10, 0.50),     (22.20, 2.55, 3.20, 0.55),
        (24.70, 2.55, 2.10, 0.50),     (15.30, 2.55, 6.30, 0.90),
        (20.70, 2.55, 6.30, 0.95),     (24.70, 2.55, 6.30, 0.60),
        (11.00, 2.55, 9.30, 0.70),     (19.00, 2.55, 9.30, 0.70),
        (3.60, 2.55, 12.40, 1.00),     (1.80, 2.55, 18.20, 0.65),
        (5.40, 2.55, 18.20, 0.70),     (8.50, 2.55, 11.70, 0.50),
        (11.20, 2.55, 11.70, 0.70),    (9.90, 2.55, 16.60, 0.95),
        (13.50, 2.55, 15.00, 0.60),    (16.30, 2.55, 11.90, 0.80),
        (19.80, 2.55, 11.90, 0.50),    (23.70, 2.55, 11.90, 0.85),
        (16.70, 2.55, 16.80, 0.95),    (22.50, 2.55, 16.80, 1.00),
        # o que entra pelas aberturas grandes
        (0.40, 1.70, 12.40, 0.45),     (9.00, 1.70, 0.40, 0.45),
        (22.80, 1.70, 19.60, 0.45),
    ]

    pontos = _pontos_por_cobertura(zonas, caixas, larg, fundo,
                                   raio=RAIO_DE_COBERTURA)

    return dict(nome="Casa de 520 m², com vista para o mar", pasta="casa_grande",
                larg=larg, fundo=fundo, zonas=zonas, caixas=caixas,
                janelas=janelas, luzes=luzes, pontos=pontos, vista="mar",
                descricao="Casa completa de 520 m² em 23 cômodos: varanda "
                          "gourmet, sala de estar, hall, jantar, copa, "
                          "cozinha, despensa, lavabo, lavanderia, depósito, "
                          "corredor, suíte master com closet e banho, dois "
                          "quartos, banho social, rouparia, sala de estudos, "
                          "adega, academia e sala íntima.")


TODAS = [apartamento, compacto, cobertura, mansao, pavilhao, quarto,
         casa_grande]
