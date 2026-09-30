# -*- coding: utf-8 -*-
"""
Costura de fotos em panorama 360 (equirretangular).

Recebe varias fotos tiradas girando no proprio eixo e devolve uma unica
imagem panoramica em projecao esferica, pronta para o visualizador 360.
"""
import os

# A aceleracao por GPU (OpenCL) estoura a memoria de video ao projetar a esfera e o
# erro que ela levanta e irrecuperavel: chama o terminate handler e derruba o processo
# inteiro, sem excecao para capturar. Na CPU a costura e mais lenta, porem estavel.
#
# Precisa ser desligado por variavel de ambiente, ANTES de importar o cv2:
# cv2.ocl.setUseOpenCL(False) vale so para a thread que chamou, e o Flask atende
# cada requisicao numa thread nova, que voltaria a usar a GPU.
os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "disabled")
os.environ.setdefault("OPENCV_OPENCL_DEVICE", "disabled")

import uuid
import cv2
import struct
import numpy as np

import nivelamento

cv2.ocl.setUseOpenCL(False)   # reforco para a thread de importacao

LARGURA_MAX_SAIDA = 8000     # teto de seguranca da imagem final
MINIMO_RECOMENDADO = 6       # abaixo disso a chance de sucesso cai muito


SEMENTE = 12345           # ver _tentar_costurar: e o que torna a costura repetivel
LIMITE_GIRO_FECHADO = 55.0   # ver _geometria: fechamento sem depender da focal


def _larguras_a_tentar(quantidade):
    """
    Larguras de trabalho, da maior para a menor.

    Antes era uma largura so, escolhida pelo numero de fotos, e quanto mais fotos
    MENOR ela ficava — a captura caprichada em 3 fileiras saia menos nitida que a
    de uma fileira. Com 34 fotos de iPhone o software usava 1000 px de 3024: 11%
    dos pixels que a camera capturou.

    Agora comeca alto e cai se o alinhamento nao convergir. A queda nao e luxo: o
    comportamento do OpenCV NAO e monotonico na resolucao. Medido nas 34 fotos do
    quarto, com semente fixa: 1600 aprovou, 2000 foi recusado por deformacao, e
    2400 aprovou com o melhor preenchimento de todos (0,917). Sem a queda, um lote
    que calha de cair num vale desses falharia por inteiro.

    Lotes grandes comecam mais baixo por memoria: 34 fotos a 2400 px ja ocupam
    perto de 800 MB so nas imagens de entrada.
    """
    if quantidade >= 45:
        return (1600, 1200, 1000)
    if quantidade >= 20:
        return (2400, 1600, 1200)
    return (2400, 1600, 1400)


# ------------------------------------------------- a focal que a foto ja sabe
#
# O alinhamento deduz a distancia focal por ajuste de feixe, olhando so os
# pixels. Funciona, mas o proprio codigo abaixo ja documentava o caso em que
# o OpenCV devolve uma focal fora da realidade — e dela sai o campo de visao,
# que decide se a volta fechou.
#
# A foto costuma TRAZER esse numero. O celular grava no EXIF a focal
# equivalente a 35 mm, que e medida do aparelho e nao estimativa. Ler custa
# milissegundos e troca um palpite por um dado.
#
# Leitor proprio, sem biblioteca: e a mesma licao do three.js que vinha do
# cdnjs. Sao trinta linhas de formato bem definido, e uma dependencia a mais
# so para isto seria paga pelo servidor de quem instala.

TAG_EXIF_IFD = 0x8769          # ponteiro para o bloco onde vive a focal
TAG_FOCAL_35 = 0xA405          # FocalLengthIn35mmFilm, em milimetros
LADO_LONGO_MM = 36.0           # o quadro de 35 mm tem 36 x 24
LADO_CURTO_MM = 24.0


def _entradas_ifd(dados, base, pos, ordem):
    """Percorre um IFD e devolve {tag: valor} para os tipos que interessam."""
    achados = {}
    if pos + 2 > len(dados):
        return achados
    (quantas,) = struct.unpack(ordem + "H", dados[pos:pos + 2])
    pos += 2
    for _ in range(min(quantas, 512)):        # teto: EXIF corrompido nao trava
        if pos + 12 > len(dados):
            break
        tag, tipo, conta = struct.unpack(ordem + "HHI", dados[pos:pos + 8])
        bruto = dados[pos + 8:pos + 12]
        if tipo == 3 and conta == 1:                      # SHORT
            achados[tag] = struct.unpack(ordem + "H", bruto[:2])[0]
        elif tipo == 4 and conta == 1:                    # LONG
            achados[tag] = struct.unpack(ordem + "I", bruto)[0]
        pos += 12
    return achados


def focal_em_35mm(bruto):
    """
    A focal equivalente a 35 mm gravada pela camera, ou None.

    None em todo caso duvidoso: foto sem EXIF, EXIF truncado, arquivo que nem e
    JPEG. Chutar aqui seria pior do que nao ler, porque o numero entraria com
    cara de medida.
    """
    try:
        if not bruto[:2] == b"\xff\xd8":                 # nao e JPEG
            return None
        i = 2
        while i + 4 <= len(bruto):
            if bruto[i] != 0xFF:
                return None
            marcador = bruto[i + 1]
            if marcador in (0xD8, 0xD9) or 0xD0 <= marcador <= 0xD7:
                i += 2
                continue
            (tamanho,) = struct.unpack(">H", bruto[i + 2:i + 4])
            corpo = bruto[i + 4:i + 2 + tamanho]
            if marcador == 0xE1 and corpo[:6] == b"Exif\x00\x00":
                return _focal_do_tiff(corpo[6:])
            if marcador == 0xDA:                          # comecou a imagem
                return None
            i += 2 + tamanho
    except (struct.error, IndexError, ValueError):
        return None
    return None


def _focal_do_tiff(tiff):
    if tiff[:2] == b"II":
        ordem = "<"
    elif tiff[:2] == b"MM":
        ordem = ">"
    else:
        return None
    (magico,) = struct.unpack(ordem + "H", tiff[2:4])
    if magico != 42:
        return None
    (off0,) = struct.unpack(ordem + "I", tiff[4:8])
    ifd0 = _entradas_ifd(tiff, 0, off0, ordem)
    if TAG_FOCAL_35 in ifd0:
        valor = ifd0[TAG_FOCAL_35]
        return float(valor) if 4 <= valor <= 300 else None
    ponteiro = ifd0.get(TAG_EXIF_IFD)
    if not ponteiro:
        return None
    exif = _entradas_ifd(tiff, 0, ponteiro, ordem)
    valor = exif.get(TAG_FOCAL_35)
    if not valor:
        return None
    # fora desta faixa nao e lente de celular nem de camera comum: e lixo
    return float(valor) if 4 <= valor <= 300 else None


def focal_em_pixels(focal35, largura, altura):
    """
    Converte a focal de 35 mm para pixels da foto que vamos costurar.

    A orientacao importa: no quadro de 35 mm o lado longo tem 36 mm e o curto
    24. Foto em pe tem 24 mm no horizontal, e usar 36 ali daria um campo de
    visao 50% maior do que o real — pior do que nao ler o EXIF.
    """
    if not focal35 or largura <= 0 or altura <= 0:
        return None
    lado = LADO_LONGO_MM if largura >= altura else LADO_CURTO_MM
    return float(largura) * float(focal35) / lado


def focal_das_fotos(caminhos, largura, altura):
    """
    A focal em pixels que o lote declara, ou None se as fotos nao disserem.

    Mediana e nao media: uma foto com EXIF estranho no meio de vinte nao pode
    arrastar o resultado. E exige que a MAIORIA concorde — lote com duas
    cameras diferentes nao tem uma focal so, e fingir que tem seria inventar.
    """
    valores = []
    for caminho in caminhos:
        try:
            with open(caminho, "rb") as f:
                valores.append(focal_em_35mm(f.read(262144)))
        except OSError:
            valores.append(None)
    lidos = [v for v in valores if v]
    if len(lidos) < max(2, len(valores) // 2):
        return None
    mediana = float(np.median(lidos))
    if max(lidos) - min(lidos) > mediana * 0.25:
        return None                    # fotos de lentes diferentes: sem palpite
    return focal_em_pixels(mediana, largura, altura)


def _geometria(cameras, largura_foto, focal_exif=None):
    """
    Le a orientacao que o OpenCV calculou para cada foto e devolve a cobertura real
    da captura. E o unico jeito confiavel de saber se a volta fechou: a proporcao da
    imagem nao serve, porque fotografar em fileiras aumenta a altura e derruba a
    proporcao mesmo quando o giro horizontal foi completo.
    """
    yaws, pitches, focais = [], [], []
    for c in cameras:
        R = np.array(c.R, dtype=np.float64)
        yaws.append(np.degrees(np.arctan2(R[0, 2], R[2, 2])))
        pitches.append(np.degrees(np.arcsin(np.clip(-R[1, 2], -1.0, 1.0))))
        focais.append(float(c.focal))

    yaws = np.array(yaws)
    pitches = np.array(pitches)
    focal = float(np.median(focais)) or 1.0
    # A focal do EXIF e medida do aparelho; a do ajuste de feixe e estimativa
    # a partir dos pixels. Quando a foto diz, a foto manda.
    origem_focal = "ajuste"
    if focal_exif:
        origem_focal = "exif"
        focal = float(focal_exif)
    fov = float(np.degrees(2 * np.arctan(largura_foto / (2 * focal))))

    ordenados = np.sort(np.mod(yaws, 360.0))
    buracos = np.diff(np.concatenate([ordenados, [ordenados[0] + 360.0]]))
    maior_buraco = float(buracos.max())

    # a volta fechou se nenhum vao entre fotos vizinhas for maior que o campo de
    # visao de uma foto - abaixo disso as imagens ainda se tocam e cobrem a esfera
    fechada = maior_buraco < fov * 0.95

    # O mesmo julgamento SEM depender da focal. `maior_buraco` sai dos angulos de
    # giro, que vem das matrizes de rotacao e nao passam pela estimativa de foco;
    # so o `fov` da comparacao acima e que depende dela. Em resolucao alta o
    # ajuste de feixe do OpenCV as vezes devolve uma focal fora da realidade, e ai
    # a conta acima erra — mas os angulos continuam corretos.
    #
    # 55 graus e o piso do campo horizontal de celular (o codigo assume 50 a 80).
    # Usar o piso e deliberado: erra para o lado de dizer "nao fechou", que custa
    # um panorama parcial, em vez de esticar uma captura incompleta por 360 graus.
    fechada_por_giro = maior_buraco < LIMITE_GIRO_FECHADO

    span_pitch = float(pitches.max() - pitches.min())

    # Camera de celular fica entre 50 e 80 graus de campo horizontal. Muito fora
    # disso, a estimativa de foco nao fecha com a realidade — acontece quando as
    # fotos nao sao um giro no eixo, e o resultado seria um haov sem sentido.
    confiavel = 25.0 <= fov <= 120.0

    # cobertura vertical: o quanto as fotos inclinaram mais o campo de uma foto.
    # Celular em pe tem o sensor mais alto que largo, dai o 4/3.
    vaov_real = min(180.0, span_pitch + fov * 4.0 / 3.0)

    return {
        "haov": 360.0 if fechada else min(360.0, (360.0 - maior_buraco) + fov),
        "vaov_real": vaov_real,
        "fechada": fechada,
        "fechada_por_giro": fechada_por_giro,
        "maior_buraco": maior_buraco,
        "fov": fov,
        "focal_origem": origem_focal,
        "confiavel": confiavel,
        "fileiras": 1 if span_pitch < 15 else (2 if span_pitch < 50 else 3),
    }


class ErroCostura(Exception):
    """Falha de costura com mensagem explicativa para o usuario final."""


def _ler_imagem(caminho):
    dados = np.fromfile(caminho, dtype=np.uint8)   # suporta acento no caminho
    img = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if img is None:
        raise ErroCostura("Não consegui abrir o arquivo: %s" % os.path.basename(caminho))
    return img


def _salvar(img, caminho, qualidade=90):
    ext = os.path.splitext(caminho)[1]
    ok, buf = cv2.imencode(ext, img, [cv2.IMWRITE_JPEG_QUALITY, qualidade])
    if not ok:
        raise ErroCostura("Falha ao gravar a imagem final.")
    buf.tofile(caminho)


def _redimensionar(img, largura_alvo):
    h, w = img.shape[:2]
    if w <= largura_alvo:
        return img
    escala = largura_alvo / float(w)
    return cv2.resize(img, (int(w * escala), int(h * escala)), interpolation=cv2.INTER_AREA)


def _tapar_buracos_internos(img, limite=0.12):
    """
    Preenche buracos pretos CERCADOS de imagem, que a extensao de borda nao cobre.

    `_preencher_bordas_irregulares` estende cada coluna do ultimo pixel valido para
    fora, entao resolve o recorte ondulado das pontas — mas nao um vazio no meio,
    que fica com conteudo valido dos dois lados. Esses vazios aparecem quando a
    costura nao junta uma regiao, tipicamente perto do polo inferior.

    Medido nas 34 fotos do quarto: a 1000 px o buraco interior era 0,43% da imagem;
    a 2400 px subiu para 2,11%, e vira uma mancha preta visivel ao olhar para baixo.

    Aqui o cv2.inpaint serve: sao buracos pequenos cercados de textura, que e para
    o que ele foi feito. (O mesmo cv2.inpaint foi REJEITADO para tirar movel da
    frente da parede, onde a area e grande e ele transforma caneca em borrao.)
    O limite evita o caso patologico: se o vazio for enorme, nao e buraco, e
    costura falhada — e ai inventar textura seria pior do que deixar claro.
    """
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    vazio = (cinza <= 6).astype(np.uint8)
    if not vazio.any():
        return img, 0.0

    altura, largura = vazio.shape
    interno = np.zeros_like(vazio)
    for x in range(largura):
        validos = np.where(vazio[:, x] == 0)[0]
        if validos.size < 2:
            continue
        # so o que esta ENTRE o primeiro e o ultimo pixel valido da coluna
        interno[validos[0]:validos[-1] + 1, x] = vazio[validos[0]:validos[-1] + 1, x]

    fracao = float(interno.mean())
    if fracao == 0 or fracao > limite:
        return img, fracao

    # dilata um pouco: a borda do buraco costuma ter pixels meio pretos da mistura
    mascara = cv2.dilate(interno, np.ones((5, 5), np.uint8), iterations=1)
    return cv2.inpaint(img, mascara, 6, cv2.INPAINT_TELEA), fracao


def _cortar_bordas_pretas(img):
    """Remove a moldura preta que a costura esferica deixa em volta."""
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, mascara = cv2.threshold(cinza, 1, 255, cv2.THRESH_BINARY)
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return img
    x, y, w, h = cv2.boundingRect(max(contornos, key=cv2.contourArea))
    recorte = img[y:y + h, x:x + w]

    # encolhe ate nao sobrar preto nas bordas
    for _ in range(60):
        r = recorte
        if r.shape[0] < 40 or r.shape[1] < 40:
            break
        topo = r[0, :, :].max() < 8
        base = r[-1, :, :].max() < 8
        esq = r[:, 0, :].max() < 8
        dir_ = r[:, -1, :].max() < 8
        if not (topo or base or esq or dir_):
            break
        recorte = r[1 if topo else 0: r.shape[0] - (1 if base else 0),
                    1 if esq else 0: r.shape[1] - (1 if dir_ else 0)]
    return recorte


def _maior_retangulo_cheio(mascara):
    """
    Maior retangulo sem nenhum pixel vazio, pelo metodo do histograma.
    Devolve (x0, y0, x1, y1) em coordenadas da mascara.
    """
    altura, largura = mascara.shape
    alturas = np.zeros(largura, dtype=np.int32)
    melhor = (0, 0, 0, 0, 0)

    for i in range(altura):
        alturas = np.where(mascara[i], alturas + 1, 0)
        pilha = []
        for j in range(largura + 1):
            atual = int(alturas[j]) if j < largura else 0
            inicio = j
            while pilha and pilha[-1][1] >= atual:
                inicio, alt = pilha.pop()
                area = alt * (j - inicio)
                if area > melhor[0]:
                    melhor = (area, inicio, i - alt + 1, j, i + 1)
            pilha.append((inicio, atual))

    _, x0, y0, x1, y1 = melhor
    return x0, y0, x1, y1


# Medido nas 16 fotos de um quarto real: o OpenCV ja compensa o ganho entre as
# fotos, entao o brilho medio do panorama sai uniforme. O que sobrava era perda
# de detalhe nas sombras — 11% dos pixels esmagados abaixo de 25.
#
# A correcao e local, nao global: achatar o brilho do panorama inteiro destruiria
# a iluminacao real, porque a parede da janela e mesmo mais clara que o canto.
# Com CLAHE no canal de luminancia, a sombra esmagada caiu para 7,2% sem mexer
# no estouro. Limite 4,0 foi testado e PIOROU (15%), por redistribuir demais.
LIMITE_CLAHE = 2.5
GRADE_CLAHE = (16, 8)


def ajustar_exposicao(img):
    """Recupera detalhe nas sombras sem estourar as partes claras."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=LIMITE_CLAHE, tileGridSize=GRADE_CLAHE).apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def medir_exposicao(img):
    """Numeros que o painel mostra para o corretor julgar a captura."""
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    validos = cinza[cinza > 6]
    if validos.size == 0:
        return {}
    return {
        "brilho": round(float(validos.mean()), 1),
        "sombra_esmagada": round(float((validos < 25).mean() * 100), 2),
        "estourado": round(float((validos > 250).mean() * 100), 2),
    }


def _preencher_bordas_irregulares(img):
    """
    Elimina o recorte preto ondulado de cima e de baixo estendendo, em cada coluna,
    a cor do ultimo pixel valido ate a borda — depois suaviza so o que foi preenchido.

    Recortar no retangulo cheio seria mais simples, mas custa caro: numa costura
    tipica de quarto o maior retangulo 100% preenchido guarda menos de 20% da area,
    o que jogaria fora quase todo o campo de visao vertical.
    """
    altura, largura = img.shape[:2]
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    valido = cinza > 6

    tem_conteudo = valido.any(axis=0)
    if not tem_conteudo.any():
        return img

    primeira = np.argmax(valido, axis=0)
    ultima = altura - 1 - np.argmax(valido[::-1], axis=0)

    saida = img.copy()
    preenchido = np.zeros((altura, largura), dtype=bool)

    # A cor de cada coluna e suavizada na horizontal ANTES de ser esticada. Sem isso,
    # um movel escuro encostado na borda vira uma listra vertical subindo pelo teto.
    cor_topo = np.array([img[int(primeira[x]), x] for x in range(largura)], dtype=np.float32)
    cor_base = np.array([img[int(ultima[x]), x] for x in range(largura)], dtype=np.float32)
    cor_topo = cv2.GaussianBlur(cor_topo.reshape(1, largura, 3), (0, 0), sigmaX=70)[0]
    cor_base = cv2.GaussianBlur(cor_base.reshape(1, largura, 3), (0, 0), sigmaX=70)[0]

    for x in range(largura):
        if not tem_conteudo[x]:
            continue
        p, u = int(primeira[x]), int(ultima[x])
        if p > 0:
            saida[:p, x] = cor_topo[x]
            preenchido[:p, x] = True
        if u < altura - 1:
            saida[u + 1:, x] = cor_base[x]
            preenchido[u + 1:, x] = True

    # colunas totalmente vazias herdam a vizinha mais proxima que tenha conteudo
    if not tem_conteudo.all():
        indices = np.where(tem_conteudo)[0]
        for x in np.where(~tem_conteudo)[0]:
            saida[:, x] = saida[:, indices[np.argmin(np.abs(indices - x))]]
            preenchido[:, x] = True

    # sem isso o preenchimento vira listras verticais visiveis
    suave = cv2.GaussianBlur(saida, (0, 0), sigmaX=25, sigmaY=9)
    peso = cv2.GaussianBlur(preenchido.astype(np.float32), (0, 0), sigmaX=9, sigmaY=9)
    peso = np.clip(peso, 0, 1)[:, :, None]
    return (saida * (1 - peso) + suave * peso).astype(np.uint8)


def _completar_esfera(img):
    """
    Encaixa a faixa panoramica numa tela 2:1 (equirretangular completa) e preenche
    teto e chao esticando as cores das bordas, com desfoque progressivo.

    Sem isso o visitante ve preto ao olhar para cima ou para baixo, porque a faixa
    cobre so a altura que a camera alcancou. O preenchimento nao inventa detalhe:
    e a propria cor do teto e do piso, borrada ate o polo.
    """
    h, w = img.shape[:2]
    altura_alvo = w // 2
    if h >= altura_alvo:
        return cv2.resize(img, (w, altura_alvo), interpolation=cv2.INTER_AREA)

    tela = np.zeros((altura_alvo, w, 3), dtype=np.uint8)
    topo = (altura_alvo - h) // 2
    tela[topo:topo + h] = img

    def preencher(faixa_origem, destino_ini, destino_fim, para_cima):
        if destino_fim <= destino_ini:
            return
        base = cv2.GaussianBlur(faixa_origem.mean(axis=0).astype(np.float32)
                                .reshape(1, w, 3), (61, 1), 0)[0]
        cor_polo = base.mean(axis=0)
        n = destino_fim - destino_ini
        for k in range(n):
            t = (k + 1) / float(n) if para_cima else (n - k) / float(n)
            t = t ** 0.7                     # aproxima do polo mais rapido
            linha = base * (1 - t) + cor_polo * t
            tela[destino_ini + k] = linha.astype(np.uint8)

    preencher(img[:12], 0, topo, para_cima=False)
    preencher(img[-12:], topo + h, altura_alvo, para_cima=True)
    return tela


def _contar_pares_com_sobreposicao(imagens):
    """
    Mede quantos pares consecutivos realmente compartilham conteudo.
    Serve para dar um diagnostico honesto quando a costura falha.
    """
    orb = cv2.ORB_create(1200)
    casador = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    descritores = []
    for img in imagens:
        cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, desc = orb.detectAndCompute(cinza, None)
        descritores.append(desc)

    pares_ok = 0
    for i in range(len(descritores) - 1):
        a, b = descritores[i], descritores[i + 1]
        if a is None or b is None or len(a) < 10 or len(b) < 10:
            continue
        casamentos = casador.match(a, b)
        bons = [m for m in casamentos if m.distance < 45]
        if len(bons) >= 25:
            pares_ok += 1
    return pares_ok


def _diagnostico(codigo, imagens):
    qtd = len(imagens)

    if qtd < MINIMO_RECOMENDADO:
        pares = _contar_pares_com_sobreposicao(imagens)
        if pares == 0:
            return ("Estas %d fotos não têm trecho em comum. Pelo que a análise mostra, "
                    "elas foram tiradas de pontos diferentes do cômodo — você andou entre "
                    "uma foto e outra. Para o 360 funcionar você precisa ficar parado no "
                    "mesmo lugar e girar o corpo, tirando de 8 a 12 fotos, cada uma "
                    "repetindo cerca de 30%% do que apareceu na anterior." % qtd)
        return ("Só %d fotos não fecham uma volta completa. Fique parado no centro do "
                "cômodo e tire de 8 a 12 fotos girando aos poucos, sem sair do lugar."
                % qtd)

    if codigo == cv2.STITCHER_ERR_NEED_MORE_IMGS:
        return ("As fotos não têm sobreposição suficiente. Cada foto precisa repetir cerca "
                "de 30%% do que aparece na anterior. Você enviou %d fotos — gire menos a "
                "cada clique e tire mais fotos no mesmo ponto." % qtd)
    if codigo == cv2.STITCHER_ERR_HOMOGRAPHY_EST_FAIL:
        return ("Não consegui alinhar as fotos. Isso costuma acontecer quando a câmera sai "
                "do lugar entre um clique e outro, ou quando a parede é lisa demais e não "
                "tem pontos de referência.")
    if codigo == cv2.STITCHER_ERR_CAMERA_PARAMS_ADJUST_FAIL:
        return ("As fotos foram tiradas de posições diferentes do cômodo. Para o 360 "
                "funcionar, você precisa girar no próprio eixo, sem andar.")
    return "A costura falhou (código %s)." % codigo


PREENCHIMENTO_MINIMO = 0.85   # costura boa fica ~100%; deformada cai para ~60%


def _preenchimento(panorama):
    """Fracao da imagem que tem conteudo real (o resto e vazio deixado pela projecao)."""
    cinza = cv2.cvtColor(panorama, cv2.COLOR_BGR2GRAY)
    return (cinza > 6).sum() / float(cinza.size)


def _resolucao_emenda(quantidade):
    """
    Resolucao em que o OpenCV procura onde cortar entre duas fotos vizinhas.
    E a etapa mais cara da composicao e cresce muito com o numero de fotos: em
    30 fotos, baixar de 0,1 para 0,015 levou o tempo de 122s para 16s sem
    diferenca visivel nas emendas.
    """
    if quantidade >= 20:
        return 0.015
    if quantidade >= 10:
        return 0.04
    return 0.08


def _resultado_aproveitavel(panorama, imagens, usadas=None):
    """
    O OpenCV as vezes devolve STITCHER_OK com um resultado inutil. Dois casos:

    1. Juntou so uma faixa minima e o panorama fica do tamanho de uma foto sozinha.
    2. Encaixou tudo, mas com a geometria errada — o comodo vira um arco torto e
       sobra vazio em volta. Acontece quando as fotos saem de pontos diferentes.

    Ambos sao piores que um erro claro, porque o usuario so descobre o problema
    depois de montar o tour inteiro. Devolve (aprovado, motivo).
    """
    if panorama is None:
        return False, "vazio"

    # Quantas fotos o OpenCV realmente aproveitou. Se descartou a maioria, sobrou
    # so um pedaco do comodo por mais que a imagem pareca aceitavel.
    if usadas is not None and len(usadas) < max(2, int(len(imagens) * 0.6)):
        return False, "descartadas"

    # Checagem minima de largura: pega fotos praticamente iguais, em que a costura
    # devolve algo do tamanho de uma foto so. Nao da para exigir muito mais que isso,
    # porque uma captura parcial legitima (meia volta) tambem produz panorama curto.
    if panorama.shape[1] < imagens[0].shape[1] * 1.3:
        return False, "estreito"

    if _preenchimento(panorama) < PREENCHIMENTO_MINIMO:
        return False, "deformado"

    return True, "ok"


def _tentar_costurar(imagens, focal_exif=None):
    """
    Tenta a costura em varias configuracoes, da mais exigente para a mais tolerante,
    e so aceita um resultado que realmente seja um panorama.
    Devolve (panorama, codigo_do_ultimo_erro, houve_resultado_fraco).
    """
    # Ordenadas por custo x chance de acerto: as tres primeiras sao rapidas.
    tentativas = [
        (cv2.Stitcher_PANORAMA, 1.0),   # padrao, camera girando no eixo
        (cv2.Stitcher_PANORAMA, 0.6),   # aceita pares com menos confianca
        (cv2.Stitcher_SCANS,    1.0),   # pouca rotacao / camera quase transladando
        (cv2.Stitcher_PANORAMA, 0.3),   # ultimo recurso esferico
        (cv2.Stitcher_SCANS,    0.6),   # lento: so vale a pena em lotes pequenos
    ]
    # cada tentativa refaz a costura inteira: com muitas fotos as duas ultimas
    # sozinhas passariam de um minuto, o que trava a tela do usuario.
    if len(imagens) >= 10:
        tentativas = tentativas[:3]

    ultimo_codigo = cv2.STITCHER_ERR_NEED_MORE_IMGS
    motivo_recusa = None

    # O alinhamento do OpenCV usa RANSAC, que sorteia. Sem semente fixa, o MESMO
    # lote de fotos dava resultados diferentes a cada tentativa: medido nas 34
    # fotos do quarto a 1600 px, 5 execucoes deram 4 resultados distintos —
    # 8269x4084, recusado, 6645x2904, recusado, 8123x3321. Com semente, 5 de 5
    # identicos. Custo zero.
    #
    # Rodar com uma thread so tambem daria determinismo, e foi testado: deu 5 de 5
    # RECUSADOS. Seria trocar "imprevisivelmente bom" por "previsivelmente ruim".
    cv2.setRNGSeed(SEMENTE)

    for modo, confianca in tentativas:
        st = cv2.Stitcher_create(modo)
        try:
            st.setPanoConfidenceThresh(confianca)
            st.setSeamEstimationResol(_resolucao_emenda(len(imagens)))
        except cv2.error:
            pass
        try:
            # em duas etapas para poder ler as cameras: o stitch() de uma tacada
            # so devolve a imagem e descarta a geometria da captura
            codigo = st.estimateTransform(imagens)
            if codigo != cv2.STITCHER_OK:
                ultimo_codigo = codigo
                continue
            geo = _geometria(st.cameras(), imagens[0].shape[1],
                             focal_exif)
            usadas = st.component()
            codigo, panorama = st.composePanorama(imagens)
        except cv2.error:
            ultimo_codigo = cv2.STITCHER_ERR_NEED_MORE_IMGS
            continue

        if codigo == cv2.STITCHER_OK and panorama is not None:
            # corta ANTES de medir: a moldura preta infla a largura e
            # faria um resultado ruim passar na validacao.
            panorama = _cortar_bordas_pretas(panorama)
            aprovado, motivo = _resultado_aproveitavel(panorama, imagens, usadas)
            if aprovado:
                return panorama, codigo, None, geo
            motivo_recusa = motivo          # resultado inutil: descarta e segue
            continue
        ultimo_codigo = codigo

    return None, ultimo_codigo, motivo_recusa, None


ABERTURA_TETO = 70.0        # graus a partir do polo considerados na analise
SUAVIDADE_TETO = 16.0


def limite_do_teto(equi, limiar=8.0):
    """
    Ate quantos graus do polo superior nao existe foto de verdade.

    Medido na propria imagem, varrendo de cima ate aparecer detalhe. A alternativa
    seria deduzir do campo da lente, mas essa estimativa vem do ajuste de foco do
    OpenCV e sai inflada: num caso real dava 115 graus de lente, o que apontaria
    um buraco de 7 graus quando o real era 44.
    """
    H = equi.shape[0]
    for y in range(0, H // 2, 6):
        faixa = cv2.cvtColor(equi[y:y + 14], cv2.COLOR_BGR2GRAY)
        if cv2.Laplacian(faixa, cv2.CV_32F).var() > limiar:
            return max(0.0, 90.0 - (y / float(H)) * 180.0)
    return 0.0


def preencher_teto(equi, graus_sem_dado):
    """
    Refaz o teto onde a captura nao alcancou.

    O preenchimento padrao estica a cor de cada coluna para cima, o que no polo
    vira um leque de cunhas — o defeito mais visivel ao olhar para cima. Aqui o
    teto observado e projetado numa vista azimutal (o polo vira o centro, sem a
    distorcao do equirretangular), ajusta-se uma superficie suave a ele e essa
    superficie e estendida para dentro do buraco.

    So entram no ajuste os pixels mais claros do anel: o anel tambem contem topo
    de armario e quina escura, e incluir isso puxava a cor para um disco cinza.

    Nao e invencao de conteudo: e a continuacao da superficie que a foto mostra.
    Medido no quarto de teste, a energia de cunha caiu de 50,8 para 3,7. O LaMa
    (198 MB) foi testado no mesmo caso e chegou a 37,3 — a tecnica simples ganhou.
    """
    H, W = equi.shape[:2]
    if abs(W / float(H) - 2.0) > 0.1 or graus_sem_dado < 4:
        return equi

    lado = 640
    eixo = (np.arange(lado, dtype=np.float32) - lado / 2.0) / (lado / 2.0)
    X, Y = np.meshgrid(eixo, eixo)
    raio = np.sqrt(X * X + Y * Y)
    theta = raio * np.radians(ABERTURA_TETO)

    # equirretangular -> vista azimutal do zenite
    phi = np.arctan2(X, -Y)
    lat = -(np.pi / 2 - theta)
    mx = ((phi / (2 * np.pi)) + 0.5) * W
    my = ((lat / np.pi) + 0.5) * H
    vista = cv2.remap(equi, mx.astype(np.float32), my.astype(np.float32),
                      cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)

    limite = np.radians(min(graus_sem_dado, ABERTURA_TETO - 8))
    buraco = (theta < limite) & (raio <= 1)
    anel = (theta >= limite) & (theta < limite + np.radians(18)) & (raio <= 1)
    if buraco.sum() < 400 or anel.sum() < 400:
        return equi

    cinza = cv2.cvtColor(vista, cv2.COLOR_BGR2GRAY)
    claros = anel & (cinza > np.percentile(cinza[anel], 55))
    if claros.sum() < 200:
        claros = anel

    def termos(x, y):
        return np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], 1)

    A = termos(X[claros], Y[claros])
    B = termos(X[buraco], Y[buraco])
    saida = vista.copy().astype(np.float32)
    for canal in range(3):
        coef, *_ = np.linalg.lstsq(A, vista[claros][:, canal].astype(np.float32),
                                   rcond=None)
        saida[buraco, canal] = np.clip(B @ coef, 0, 255)

    # ruido fraco com a mesma textura do teto observado: sem isso fica plastico
    desvio = float(cinza[claros].std()) * 0.10
    ruido = np.random.default_rng(7).normal(0, desvio, (lado, lado, 1)).astype(np.float32)
    saida[buraco] += ruido[buraco]

    peso = cv2.GaussianBlur((buraco * 255).astype(np.uint8), (0, 0),
                            SUAVIDADE_TETO).astype(np.float32)[..., None] / 255.0
    vista = (vista * (1 - peso) + np.clip(saida, 0, 255) * peso).astype(np.uint8)
    # mapa de "aqui eu mexi", em 8 bits para viajar pelo mesmo remap da imagem
    mexido = (peso[..., 0] * 255).astype(np.uint8)

    # de volta para o equirretangular, so na calota de cima
    lon = (np.arange(W, dtype=np.float32) / W - 0.5) * 2 * np.pi
    latE = (np.arange(H, dtype=np.float32) / H - 0.5) * np.pi
    lonG, latG = np.meshgrid(lon, latE)
    thetaE = np.pi / 2 + latG                      # 0 no polo de cima
    dentro = thetaE < np.radians(ABERTURA_TETO)
    rr = thetaE / np.radians(ABERTURA_TETO)
    ux = (0.5 + 0.5 * rr * np.sin(lonG)) * (lado - 1)
    uy = (0.5 - 0.5 * rr * np.cos(lonG)) * (lado - 1)
    volta_peso = cv2.remap(mexido, ux.astype(np.float32), uy.astype(np.float32),
                           cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    volta = cv2.remap(vista, ux.astype(np.float32), uy.astype(np.float32),
                      cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    # So o que foi PREENCHIDO volta do disco. Misturar a calota inteira trocava
    # pixel bom por pixel do disco de 640 px, que a 60 graus do polo tem 4,8 px
    # por grau contra 14 do equirretangular — subamostragem de 3x, que aparecia
    # como uma emenda serrilhada na junta do teto com a parede.
    mistura = (volta_peso.astype(np.float32) / 255.0)
    mistura *= np.clip((np.radians(ABERTURA_TETO) - thetaE) / np.radians(10), 0, 1)
    mistura = (mistura * dentro)[..., None]
    return (equi * (1 - mistura) + volta * mistura).astype(np.uint8)


def _nivelar(panorama):
    """Endireita o horizonte, engolindo a falha: cena sem quinas nao tem prumo."""
    try:
        img, info = nivelamento.nivelar(panorama)
        # o vetor de prumo e detalhe interno e nao sobrevive ao json.dump do tour
        info.pop("direcao", None)
        return img, info
    except nivelamento.ErroNivelamento as e:
        return panorama, {"aplicado": False, "motivo": str(e)}
    except Exception:
        return panorama, {"aplicado": False, "motivo": "falha ao nivelar"}


# --------------------------------------------------------- conferir a captura

LARGURA_CONFERENCIA = 1000   # resolucao de trabalho da conferencia
TEXTURA_MINIMA = 400         # pontos SIFT: abaixo disto a foto e superficie lisa
SOBREPOSICAO_MINIMA = 25     # pares casados: abaixo disto as fotos mal se tocam
PARALAXE_ALTA = 1.35         # inliers F/H: acima disto a camera saiu do lugar
PARALAXE_LEVE = 1.15


def _lista_de_numeros(numeros):
    """[7, 8, 9] -> "7, 8 e 9" """
    n = [str(x) for x in numeros]
    if len(n) == 1:
        return n[0]
    return ", ".join(n[:-1]) + " e " + n[-1]


def _com_conferencia(mensagem, achados):
    """Junta o diagnostico por foto ao motivo generico da recusa."""
    if not achados:
        return mensagem
    return mensagem + "\n\nO que eu vi nas suas fotos:\n" + "\n".join(
        "- " + a for a in achados)


def conferir_captura(imagens, relatar=None):
    """
    Diagnostica a captura ANTES de costurar, foto a foto e par a par.

    A costura ja reprova captura ruim, mas so depois de minutos e sem dizer QUAL
    foto atrapalhou: o usuario recebe "as fotos nao tem sobreposicao" e nao sabe
    onde errou. Aqui o defeito sai com numero de foto.

    Como se separa GIRO de PASSO sem conhecer a distancia de nada: camera que
    apenas gira e explicada inteira por uma homografia, perto e longe igual.
    Camera que anda produz paralaxe — o que esta perto se desloca mais que o
    fundo — e entao a matriz fundamental, que admite translacao, casa bem mais
    pontos que a homografia. A razao entre as duas denuncia o passo.

    Medido nas 19 fotos do quarto: os pares limpos deram razao 1,03 e 1,14; os
    pares em que a pessoa mudou de lugar deram de 1,31 a 1,95. As quatro fotos de
    porta de armario lisa deram 69 a 167 pontos, contra 4038 da melhor foto.

    So descreve; nao reprova nada. Um salto entre vizinhas nao condena a costura,
    porque o alinhador compara TODOS os pares, e nao apenas os consecutivos — a
    foto 3 pode fechar com a 9. Reprovar aqui criaria recusa falsa.
    """
    aviso = relatar or (lambda p, e: None)
    if len(imagens) < 2:
        return []

    sift = cv2.SIFT_create(nfeatures=2000)
    fotos = []
    for i, img in enumerate(imagens):
        cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        escala = LARGURA_CONFERENCIA / float(cinza.shape[1])
        if escala < 1.0:
            cinza = cv2.resize(cinza, (0, 0), fx=escala, fy=escala,
                               interpolation=cv2.INTER_AREA)
        kp, des = sift.detectAndCompute(cinza, None)
        fotos.append({"pontos": len(kp), "kp": kp, "des": des,
                      "nitidez": float(cv2.Laplacian(cinza, cv2.CV_64F).var())})
        aviso(12 + int(6.0 * (i + 1) / len(imagens)), "conferindo a captura")

    achados = []
    melhor = max(f["pontos"] for f in fotos)

    # 1. fotos sem textura: superficie lisa ocupando o quadro
    lisas = [i + 1 for i, f in enumerate(fotos) if f["pontos"] < TEXTURA_MINIMA]
    for i in lisas:
        fotos[i - 1]["lisa"] = True
    if lisas:
        achados.append(
            "Foto %s: quase sem textura (%s pontos de referência, contra %d da "
            "melhor foto do lote). Parede ou porta lisa ocupando a tela inteira não "
            "dá ao alinhamento onde se apoiar. Inclua uma quina, o rodapé ou a linha "
            "do teto no quadro — ou afaste-se, que é o que acontece sozinho quando "
            "você fotografa do meio do cômodo."
            % (_lista_de_numeros(lisas),
               _lista_de_numeros([fotos[i - 1]["pontos"] for i in lisas]),
               melhor))

    # 2. fotos tremidas: so entre as que TEM textura, senao a parede lisa, que e
    #    naturalmente pouco nitida, seria acusada de tremida tambem
    comTextura = [f for f in fotos if not f.get("lisa")]
    if len(comTextura) >= 3:
        mediana = float(np.median([f["nitidez"] for f in comTextura]))
        # 0,3 e nao 0,4: em 0,4 uma foto apenas um pouco menos nitida que as
        # vizinhas ja era acusada, e aviso que cai em foto boa ensina a ignorar
        # o aviso. Na medida do quarto a tremida de verdade ficou em 0,18 da
        # mediana, com folga larga para o limiar.
        tremidas = [i + 1 for i, f in enumerate(fotos)
                    if not f.get("lisa") and f["nitidez"] < 0.3 * mediana]
        if tremidas:
            achados.append(
                "Foto %s: saiu tremida ou fora de foco, bem menos nítida que as "
                "outras do lote. Cômodo com pouca luz faz o celular demorar no "
                "clique; encoste o cotovelo no corpo e fique parado no disparo."
                % _lista_de_numeros(tremidas))

    # 3. par a par: sobreposicao e giro-vs-passo
    bf = cv2.BFMatcher()
    saltos, andou, razoes = [], [], []
    for i in range(len(fotos) - 1):
        a, b = fotos[i], fotos[i + 1]
        aviso(18, "conferindo a captura")
        if a["des"] is None or b["des"] is None:
            continue
        brutos = bf.knnMatch(a["des"], b["des"], k=2)
        bons = [m for m, n in brutos if len(brutos[0]) == 2 and m.distance < 0.75 * n.distance]
        if len(bons) < SOBREPOSICAO_MINIMA:
            saltos.append((i + 1, i + 2, len(bons)))
            continue
        pa = np.float32([a["kp"][m.queryIdx].pt for m in bons])
        pb = np.float32([b["kp"][m.trainIdx].pt for m in bons])
        _, mascH = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
        _, mascF = cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC, 3.0, 0.99)
        iH = int(mascH.sum()) if mascH is not None else 0
        iF = int(mascF.sum()) if mascF is not None else 0
        if iH < 20:
            continue
        razao = iF / float(iH)
        razoes.append(razao)
        if razao > PARALAXE_ALTA:
            andou.append((i + 1, i + 2, razao))

    if saltos:
        achados.append(
            "Entre as fotos %s quase não há sobreposição. Cada foto precisa repetir "
            "uns 30%% do que aparece na anterior: a borda de uma tem que cair no meio "
            "da seguinte. Gire menos a cada clique."
            % _lista_de_numeros(["%d e %d" % (x, y) for x, y, _ in saltos]))

    if andou:
        piores = sorted(andou, key=lambda t: -t[2])[:4]
        achados.append(
            "Em %d de %d trechos a câmera saiu do lugar entre um clique e outro — os "
            "objetos próximos se deslocaram em relação ao fundo, coisa que girar no "
            "eixo não produz. Mais evidente entre as fotos %s. Não existe encaixe "
            "correto para fotos tiradas de pontos diferentes: o alinhamento resolve "
            "entortando. Marque um ponto no chão, mantenha os pés nele e gire em "
            "volta do aparelho, não do corpo."
            % (len(andou), len(fotos) - 1,
               _lista_de_numeros(["%d e %d" % (x, y) for x, y, _ in piores])))

    return achados


def costurar(caminhos, pasta_saida, relatar=None):
    """
    Costura N fotos numa panoramica esferica.
    relatar(progresso, etapa) e opcional e serve para a fila mostrar o andamento.
    """
    aviso = relatar or (lambda p, e: None)
    if len(caminhos) < 2:
        raise ErroCostura("Envie pelo menos 2 fotos para costurar um panorama.")

    # a flag e por thread e esta funcao roda na thread da requisicao, nao na de import
    cv2.ocl.setUseOpenCL(False)

    aviso(10, "lendo %d fotos" % len(caminhos))
    originais = [_ler_imagem(c) for c in caminhos]

    # Conferir ANTES: o que for dito aqui explica tanto a falha quanto o torto que
    # passa. Nunca reprova sozinho — ver conferir_captura.
    try:
        conferencia = conferir_captura(originais, aviso)
    except Exception:
        conferencia = []          # diagnostico e ajuda, nao pode derrubar a costura

    larguras = _larguras_a_tentar(len(caminhos))
    # A focal precisa estar na escala da imagem que VAI ser costurada, e cada
    # tentativa usa uma largura diferente — por isso e recalculada no laco.
    alt0, larg0 = originais[0].shape[0], originais[0].shape[1]
    focal35 = None
    try:
        focal35 = focal_das_fotos(caminhos, larg0, alt0)
    except Exception:
        focal35 = None            # leitura de metadado nao pode derrubar costura

    panorama = geo = None
    codigo, motivo = cv2.STITCHER_ERR_NEED_MORE_IMGS, None
    for i, largura in enumerate(larguras):
        aviso(25, "alinhando e costurando" + (" (%d px)" % largura if i else ""))
        imagens = [_redimensionar(img, largura) for img in originais]
        focal_lote = (focal35 * imagens[0].shape[1] / float(larg0)
                      if focal35 else None)
        panorama, codigo, motivo, geo = _tentar_costurar(imagens, focal_lote)
        if panorama is not None:
            break
    del originais
    if panorama is None:
        if motivo == "estreito":
            base = (
                "Consegui encaixar só uma faixa estreita das fotos — o resultado ficaria "
                "quase do tamanho de uma foto só, sem servir como 360. Isso indica que as "
                "fotos pegam pedaços diferentes do cômodo e mal se tocam. Fique parado no "
                "mesmo ponto e tire de 8 a 12 fotos girando aos poucos.")
        elif motivo == "descartadas":
            base = (
                "A maioria das fotos não encaixou com as vizinhas e ficou de fora, "
                "então sobraria só um pedaço do cômodo. Isso costuma acontecer quando "
                "a sequência tem saltos: você girou demais entre alguns cliques, ou "
                "misturou fotos de ambientes diferentes no mesmo envio.")
        elif motivo == "deformado":
            base = (
                "As fotos até se encaixaram, mas o cômodo saiu torto: as paredes viraram "
                "um arco e sobrou vazio em volta. Isso acontece quando as fotos são tiradas "
                "de pontos diferentes do cômodo — ao mudar de lugar, os móveis se deslocam "
                "uns em relação aos outros e não existe encaixe correto possível. "
                "Refaça ficando parado no mesmo ponto, girando só o corpo, com 8 a 12 fotos.")
        else:
            base = _diagnostico(codigo, imagens)
        raise ErroCostura(_com_conferencia(base, conferencia))

    # O corte das bordas e a validacao ja aconteceram dentro de _tentar_costurar.
    # O acabamento vem depois de propositio: preencher as bordas deixaria a imagem
    # 99% cheia e a checagem de panorama deformado nunca mais reprovaria nada.
    aviso(78, "corrigindo a exposição")
    antes = medir_exposicao(panorama)
    panorama = ajustar_exposicao(panorama)
    depois = medir_exposicao(panorama)

    aviso(85, "acabamento das bordas")
    panorama = _preencher_bordas_irregulares(panorama)
    panorama, _buracos = _tapar_buracos_internos(panorama)

    info = dict(geo)
    if not geo["confiavel"]:
        # Sem focal confiavel, julga pelos ANGULOS DE GIRO, que nao dependem dela.
        #
        # Antes aqui caia na proporcao da imagem, e isso quebrava exatamente a
        # captura caprichada: fileiras aumentam a ALTURA do panorama e derrubam a
        # proporcao mesmo com o giro horizontal completo — defeito que o proprio
        # _geometria ja documentava. Medido nas 34 fotos do quarto em 3 fileiras:
        # o panorama saiu 8000x3729 (proporcao 2,15), a proporcao dizia "nao
        # fechou", e a cena perdia esfera completa, teto refeito e caminhada.
        info["fechada"] = geo["fechada_por_giro"]
        info["haov"] = (360.0 if info["fechada"]
                        else min(360.0, 360.0 - geo["maior_buraco"] + LIMITE_GIRO_FECHADO))

    # A esfera 2:1 so faz sentido quando o giro fechou a volta. Se a captura foi
    # parcial, esticar para 360 graus deformaria o comodo inteiro; nesse caso o
    # panorama fica parcial e o haov real vai junto para o visualizador.
    if info["fechada"]:
        panorama = _completar_esfera(panorama)
        # Nivelar so depois da esfera fechada: a rotacao trata o panorama como
        # uma superficie completa, e numa faixa parcial o mapeamento seria outro.
        aviso(88, "nivelando o horizonte")
        panorama, info["nivelamento"] = _nivelar(panorama)

        aviso(94, "refazendo o teto")
        sem_dado = limite_do_teto(panorama)
        panorama = preencher_teto(panorama, sem_dado)

    aviso(92, "gravando o panorama")
    panorama = _redimensionar(panorama, LARGURA_MAX_SAIDA)

    nome = "cena_%s.jpg" % uuid.uuid4().hex[:12]
    _salvar(panorama, os.path.join(pasta_saida, nome))
    h, w = panorama.shape[:2]

    info["vaov"] = 180.0 if info["fechada"] else info["haov"] * (h / float(w))
    info["exposicao"] = {"antes": antes, "depois": depois}
    # captura que passou raspando tambem merece explicacao: o panorama sai, mas
    # com o entorte que a conferencia ja tinha visto
    info["conferencia"] = conferencia
    return nome, w, h, info


def importar_equirretangular(caminho_origem, pasta_saida):
    """
    Aceita uma foto 360 ja pronta (camera 360 ou app de celular).

    Passa pelo mesmo nivelamento e reconstrucao de teto da costura: o modo
    Panorama do celular sai torto com a mesma frequencia, e quem gira o aparelho
    na mao raramente alcanca o zenite. As duas correcoes se protegem sozinhas —
    o nivelamento ignora desvios abaixo de 0,8 grau e o teto so age quando falta
    mais de 4 graus de foto —, entao uma imagem ja boa sai intacta.

    Exposicao fica de fora de proposito: o CLAHE e incondicional e uma foto que
    ja veio tratada pela camera so teria a perder.
    """
    img = _ler_imagem(caminho_origem)
    img = _redimensionar(img, LARGURA_MAX_SAIDA)
    info = {"nivelamento": {"aplicado": False}, "teto": 0.0}
    if eh_equirretangular(img.shape[1], img.shape[0]):
        img, info["nivelamento"] = _nivelar(img)
        info["teto"] = limite_do_teto(img)
        img = preencher_teto(img, info["teto"])
    nome = "cena_%s.jpg" % uuid.uuid4().hex[:12]
    _salvar(img, os.path.join(pasta_saida, nome))
    h, w = img.shape[:2]
    return nome, w, h


def reprocessar(caminho_panorama):
    """
    Reaplica nivelamento e reconstrucao de teto num panorama ja gravado.

    Cenas montadas por versoes anteriores do pipeline ficaram com o horizonte
    torto e com o leque de cunhas no teto. Recostura-las exigiria as fotos
    originais, que o sistema apaga depois de montar a cena; estas duas correcoes
    trabalham sobre o equirretangular pronto, entao ainda dao para aplicar.

    Exposicao nao entra: o CLAHE ja foi aplicado uma vez e repetir escureceria
    o resultado a cada passagem.
    """
    img = _ler_imagem(caminho_panorama)
    if not eh_equirretangular(img.shape[1], img.shape[0]):
        raise ErroCostura("Só dá para corrigir panorama 360 completo (proporção 2:1).")

    img, nivel = _nivelar(img)
    graus = limite_do_teto(img)
    antes = img
    img = preencher_teto(img, graus)
    _salvar(img, caminho_panorama)
    return {
        "nivelamento": nivel,
        "teto_graus": round(float(graus), 1),
        "teto_aplicado": bool(graus >= 4 and img is not antes),
    }


def importar_varredura(caminho_origem, pasta_saida, haov_graus=360.0):
    """
    Converte um panorama de varredura de celular (modo Panorama do iPhone/Android)
    em equirretangular.

    A varredura sai em projecao CILINDRICA, nao esferica: a altura cresce com a
    tangente da latitude, nao com a latitude. Carregar do jeito que vem esticaria
    teto e chao. A conversao amostra, para cada linha do equirretangular, a altura
    correspondente no cilindro.

    O campo vertical nao precisa ser informado: com a cobertura horizontal conhecida,
    ele sai da propria proporcao da imagem, porque no cilindro
    largura/altura = haov / (2*tan(vfov/2)).
    """
    cil = _ler_imagem(caminho_origem)
    cil = _redimensionar(cil, LARGURA_MAX_SAIDA)
    Hc, Wc = cil.shape[:2]

    haov = np.radians(max(30.0, min(360.0, float(haov_graus))))
    vfov = 2.0 * np.arctan(haov * Hc / (2.0 * Wc))
    if not np.isfinite(vfov) or vfov <= 0:
        raise ErroCostura("Não consegui interpretar a geometria dessa varredura.")

    # tela equirretangular na mesma escala angular da entrada
    W = int(round(Wc * (2 * np.pi) / haov))
    W = max(1024, min(LARGURA_MAX_SAIDA, W - (W % 2)))
    H = W // 2

    lon = (np.arange(W, dtype=np.float32) / W - 0.5) * 2 * np.pi
    lat = (np.arange(H, dtype=np.float32) / H - 0.5) * np.pi
    lon, lat = np.meshgrid(lon, lat)

    # cilindro: x acompanha a longitude, y e a tangente da latitude
    mx = (lon / haov + 0.5) * Wc
    my = (np.tan(lat) / (2 * np.tan(vfov / 2)) + 0.5) * Hc

    dentro = (np.abs(lat) < vfov / 2 - 1e-4) & (np.abs(lon) <= haov / 2 + 1e-6)
    mx = np.where(dentro, mx, -1).astype(np.float32)
    my = np.where(dentro, my, -1).astype(np.float32)

    equi = cv2.remap(cil, mx, my, cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))

    equi = ajustar_exposicao(equi)
    equi = _preencher_bordas_irregulares(equi)
    equi, _ = _tapar_buracos_internos(equi)
    nivel = {"aplicado": False}
    if haov_graus >= 359.0:
        equi, nivel = _nivelar(equi)
        # a varredura sobe pouco: o topo fica tao esticado quanto na costura
        equi = preencher_teto(equi, limite_do_teto(equi))
    nome = "cena_%s.jpg" % uuid.uuid4().hex[:12]
    _salvar(equi, os.path.join(pasta_saida, nome))

    fechada = haov_graus >= 359.0
    return nome, equi.shape[1], equi.shape[0], {
        "nivelamento": nivel,
        "haov": 360.0 if fechada else float(haov_graus),
        "vaov": 180.0 if fechada else float(np.degrees(vfov)),
        "fechada": fechada,
        "maior_buraco": 0.0 if fechada else 360.0 - float(haov_graus),
        "fov": float(np.degrees(vfov)),
        "confiavel": True,
        "fileiras": 1,
    }


def eh_equirretangular(largura, altura):
    """Equirretangular completa tem proporcao 2:1 (tolerancia de 5%)."""
    if altura == 0:
        return False
    return abs((largura / float(altura)) - 2.0) < 0.1


VAOV_CELULAR = 65.0      # campo vertical tipico de camera de celular


def cobertura_parcial(largura, altura):
    """
    Cobertura estimada de uma foto que NAO esta em 2:1.

    Assumir 360 graus aqui era um erro caro: um panorama 3:1 do celular cobre uns
    195 graus na pratica, e espalha-lo pela volta inteira estica a cena 1,8 vez —
    parede entortada, comodo parecendo maior do que e. Sem metadado nao da para
    saber o angulo real, mas o campo vertical de camera de celular varia pouco,
    entao partir dele erra muito menos do que partir de 360.

    O painel tem o campo "Cobertura horizontal" para o corretor acertar na mao.
    """
    vaov = VAOV_CELULAR
    haov = min(360.0, vaov * (largura / float(altura)))
    return round(haov, 2), round(vaov, 2)


def cobertura_angular(largura, altura, haov=None):
    """
    Em projecao esferica os graus por pixel sao constantes.
    Logo vaov = haov * altura / largura.
    """
    if haov is None:
        haov = 360.0
    vaov = haov * (altura / float(largura))
    return round(haov, 2), round(min(vaov, 180.0), 2)
