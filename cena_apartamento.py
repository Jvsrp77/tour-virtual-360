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
    global _PAREDE_DA_ZONA, _PISO_DA_ZONA, _LIMITES
    PLANTA = planta
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
    # BGR, porque o panorama inteiro sai em BGR para o OpenCV gravar
    zenite = np.array([196, 148, 104], np.float32)     # azul de dia limpo
    horizonte = np.array([232, 222, 208], np.float32)  # palido, com neblina
    terreno = np.array([104, 118, 100], np.float32)    # verde acinzentado

    acima = np.clip(dy, 0.0, 1.0)[:, None]
    abaixo = np.clip(-dy, 0.0, 1.0)[:, None]
    # a subida ao zenite e mais rapida que a descida ao chao: e assim que um
    # ceu real se comporta visto de dentro de casa, com o horizonte lavado
    ceu = horizonte * (1.0 - acima ** 0.55) + zenite * (acima ** 0.55)
    chao = horizonte * (1.0 - abaixo ** 0.8) + terreno * (abaixo ** 0.8)
    return np.where(dy[:, None] > 0.0, ceu, chao)


def _textura(material, p, face, cor, dirs=None):
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
        # Janelas de verdade. Antes havia uma "luz de janela" sem janela nenhuma
        # na parede: iluminava a sala e nao aparecia. Alem de estranho, tirava do
        # visitante a unica referencia que diz para que lado ele esta olhando.
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
    elif material == "teto":
        for lx, ly, lz, _ in [l for l in LUZES if l[1] > 2.3]:
            r = np.hypot(p[:, 0] - lx, p[:, 2] - lz)
            saida[r < 0.26] = np.array([252, 252, 248], np.float32)
            saida[(r >= 0.26) & (r < 0.33)] *= 0.74
    elif material in ("madeira", "madeira_esc"):
        saida *= (1.0 + 0.045 * np.sin(p[:, 1] * 61.0 + p[:, 0] * 7.0))[:, None]
    elif material in ("estofado", "estofado_b"):
        saida *= _ruido(p, 55.0, 0.035)[:, None]
    elif material == "roupa_cama":
        vinco = (0.045 * np.sin(p[:, 0] * 14.0) + 0.035 * np.sin(p[:, 2] * 19.0)
                 + 0.02 * np.sin(p[:, 0] * 53.0))
        saida *= (1.0 + vinco)[:, None]
    elif material == "livro_a":
        # lombadas: a faixa de cor muda a cada ~3,5 cm
        k = np.floor(p[:, 2] / 0.035).astype(np.int32)
        matiz = np.stack([(k * 53 % 140) + 60, (k * 97 % 120) + 70,
                          (k * 31 % 150) + 70], axis=1).astype(np.float32)
        saida = matiz
        saida[np.abs((p[:, 2] / 0.035) % 1.0 - 0.5) > 0.44] *= 0.6
    elif material == "planta":
        saida *= (1.0 + 0.16 * np.sin(p[:, 1] * 40.0) * np.sin(p[:, 0] * 37.0))[:, None]
    elif material == "vidro":
        # Sem transparencia de verdade (o tracado nao refrata), o que faz o
        # olho aceitar o vidro e o degrade vertical mais a moldura. Chapado ele
        # lia como parede clara e tapava o banheiro inteiro.
        saida *= (0.80 + 0.26 * np.clip(p[:, 1] / 2.0, 0, 1))[:, None]
        saida *= np.array([1.02, 1.00, 0.95], np.float32)[None, :]   # verde do vidro
        saida *= (1.0 + 0.05 * np.sin(p[:, 1] * 24.0))[:, None]
        borda = (p[:, 1] < 0.16) | (p[:, 1] > 1.88)
        saida[borda] *= 0.62
    return saida


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
    for y0 in range(0, altura, passo):
        y1 = min(altura, y0 + passo)
        d = _direcoes(y0, y1, largura, altura)
        inv = _inverso(d)
        t, face = _casca(o, d)
        dono = np.full(d.shape[0], -1, np.int32)
        for k, c in enumerate(CAIXAS):
            tk = _caixa(o, inv, c)
            perto = tk < t
            t = np.where(perto, tk, t)
            dono = np.where(perto, k, dono)

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
                                            d[idx])
            else:
                cor[sel] = _textura(nome, p[sel], i, MATERIAIS[nome],
                                    d[sel])

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
                        cor[base[s2]] = _textura(m2, p[base[s2]], lado,
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


def conferir(planta):
    """
    Recusa renderizar com ponto de captura ruim.

    Vale o custo: renderizar 14 panoramas de 8k leva meia hora, e ja aconteceu
    de descobrir so no fim que a camera estava DENTRO da cama — o colchao virava
    o chao inteiro. Aqui a checagem custa milissegundos e diz o nome do ponto.
    """
    problemas = []
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
