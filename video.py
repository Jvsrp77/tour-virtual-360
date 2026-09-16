# -*- coding: utf-8 -*-
"""
Escolhe, de um video, os quadros que viram panorama.

POR QUE VIDEO. Fotografar girando exige acertar o passo: girou demais, abre vao;
girou de menos, sao fotos a toa. Medido nas 19 fotos do quarto, tres pares
consecutivos ficaram sem sobreposicao util e a corrente arrebentou. Filmando, a
sobreposicao e continua por construcao — nao existe "girei demais".

O QUE SE PERDE. Nitidez. A foto do iPhone tem 3024 px de largura; 1080p entrega
1080. O costurador trabalha a 2400 px e sua escada mais baixa e 1400, entao 1080p
entrega menos do que ele sabe aproveitar. Por isso `conferir_largura` avisa, e
por isso a orientacao e filmar em 4K, de pe (retrato).

O QUE NAO SE RESOLVE. Andar sem distorcao. Video do mesmo ponto tem o mesmo
buraco da foto do mesmo ponto: ninguem viu atras do armario. Isso e numero de
pontos de captura, nao formato de arquivo.

COMO OS QUADROS SAO ESCOLHIDOS. Nao por tempo — quem filma gira em velocidade
irregular, e o espacamento por tempo sairia torto junto. O passo e ANGULAR: mede
o deslocamento entre quadros por correlacao de fase e acumula. A cada `PASSO`
de largura de quadro percorrido, escolhe-se um quadro; e entre os candidatos
daquela vizinhanca, o mais nitido. Assim a captura tremida no meio do giro e
descartada em favor da vizinha parada, que e o ganho que a foto na mao nao da.
"""
import os

os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "disabled")

import cv2
import numpy as np

LARGURA_ANALISE = 320      # resolucao da passada de medicao: barata e suficiente
PASSO = 0.35               # passo em fracao da largura: deixa ~65% de sobreposicao
MAXIMO_QUADROS = 24        # acima disto a costura fica cara sem ganhar cobertura
MINIMO_QUADROS = 6         # abaixo disto nao da panorama
LARGURA_POBRE = 1400       # ver stitcher._larguras_a_tentar: o degrau mais baixo
NITIDEZ_ACEITAVEL = 0.7    # ver _escolher: so foge do alvo por borrao de verdade
EXTENSOES = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm")


class ErroVideo(Exception):
    pass


def _abrir(caminho):
    captura = cv2.VideoCapture(caminho)
    # video de celular vem deitado com uma marca de rotacao; sem isto o quadro sai
    # girado e o panorama nasce de lado
    try:
        captura.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
    except Exception:
        pass
    if not captura.isOpened():
        raise ErroVideo(
            "Não consegui abrir o vídeo. Envie em MP4 ou MOV — é o que o celular "
            "grava por padrão.")
    return captura


def conferir_largura(largura):
    """Aviso de resolucao, ou None. Ver o cabecalho: 1080p fica abaixo do util."""
    if largura >= 2000:
        return None
    if largura < LARGURA_POBRE:
        return ("O vídeo tem só %d pixels de largura. O costurador trabalha com "
                "2400 e não desce de %d, então boa parte do detalhe se perde antes "
                "de começar. Grave em 4K e com o celular de pé para aproveitar a "
                "resolução que a câmera tem." % (largura, LARGURA_POBRE))
    return ("O vídeo tem %d pixels de largura, contra os 2400 que o costurador "
            "sabe usar. Dá panorama, mas com menos detalhe que fotos soltas. Em 4K "
            "a diferença desaparece." % largura)


def _medir(captura, relatar):
    """
    Primeira passada: nitidez de cada quadro e quanto a camera girou ate ele.

    Correlacao de fase mede o deslocamento entre dois quadros inteiros, sem
    depender de achar pontos — o que importa aqui, porque parede lisa, que derruba
    o detector de pontos, ainda desloca bem.
    """
    total = int(captura.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    nitidez, andado, larguras = [], [], []
    anterior = None
    percorrido = 0.0
    i = 0
    while True:
        ok, quadro = captura.read()
        if not ok:
            break
        larguras.append(quadro.shape[1])
        escala = LARGURA_ANALISE / float(quadro.shape[1])
        pequeno = cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY)
        pequeno = cv2.resize(pequeno, (0, 0), fx=escala, fy=escala,
                             interpolation=cv2.INTER_AREA)
        nitidez.append(float(cv2.Laplacian(pequeno, cv2.CV_64F).var()))

        atual = pequeno.astype(np.float32)
        if anterior is not None:
            try:
                (dx, dy), _ = cv2.phaseCorrelate(anterior, atual)
                percorrido += float(np.hypot(dx, dy))
            except cv2.error:
                pass                       # quadro corrompido nao interrompe a medicao
        anterior = atual
        andado.append(percorrido)

        i += 1
        if relatar and total and i % 15 == 0:
            relatar(5 + int(10.0 * i / total), "lendo o vídeo")
    return nitidez, andado, larguras


def _escolher(nitidez, andado, passo):
    """
    Um quadro a cada `passo` percorrido; desvia do alvo so para fugir de borrao.

    O criterio e "o mais PROXIMO do alvo entre os aceitavelmente nitidos", e nao
    "o mais nitido da vizinhanca". A diferenca nao e sutil: medido num giro de
    velocidade constante, escolher o mais nitido da janela dava espacamento de
    4,8 a 36 graus onde o uniforme era 18 — porque num video sem borrao todos os
    candidatos tem nitidez praticamente igual, e o maximo cai em qualquer ponto
    da janela por ruido. Com 36 graus de vao e 50 de campo, a sobreposicao cai
    para 28% e o alinhamento se desmancha; o panorama saiu recusado por
    deformacao enquanto os MESMOS angulos, entregues direto, costuravam limpo.

    Com o filtro de nitidez relativo, video limpo escolhe sempre o quadro do alvo
    — espacamento uniforme — e so o trecho realmente borrado empurra a escolha
    para o vizinho.
    """
    if not andado:
        return []
    total = andado[-1]
    if total < passo:
        return [int(np.argmax(nitidez))] if nitidez else []

    quantos = int(total // passo) + 1
    quantos = max(MINIMO_QUADROS, min(MAXIMO_QUADROS, quantos))
    alvos = np.linspace(0.0, total, quantos)

    andado = np.asarray(andado)
    # a janela acompanha o espacamento real, que e maior que `passo` quando o
    # teto de quadros corta a conta
    espaco = float(alvos[1] - alvos[0]) if len(alvos) > 1 else passo
    janela = espaco * 0.5

    escolhidos = []
    for alvo in alvos:
        perto = np.where(np.abs(andado - alvo) <= janela)[0]
        if not len(perto):
            perto = np.array([int(np.argmin(np.abs(andado - alvo)))])
        melhor_nitidez = max(nitidez[k] for k in perto)
        aceitaveis = [k for k in perto
                      if nitidez[k] >= NITIDEZ_ACEITAVEL * melhor_nitidez]
        escolhido = min(aceitaveis, key=lambda k: abs(andado[k] - alvo))
        if escolhido not in escolhidos:
            escolhidos.append(int(escolhido))
    return sorted(escolhidos)


def extrair_quadros(caminho_video, pasta_saida, relatar=None):
    """
    Devolve (caminhos_dos_quadros, avisos).

    Os quadros saem como JPEG de qualidade alta, prontos para `stitcher.costurar`,
    que em seguida roda a conferencia de captura sobre eles — inclusive o teste de
    paralaxe, que denuncia quem filmou andando em vez de girando no lugar.
    """
    aviso = relatar or (lambda p, e: None)
    if not os.path.exists(caminho_video):
        raise ErroVideo("Não encontrei o arquivo de vídeo.")

    captura = _abrir(caminho_video)
    try:
        aviso(5, "lendo o vídeo")
        nitidez, andado, larguras = _medir(captura, aviso)
    finally:
        captura.release()

    if len(nitidez) < MINIMO_QUADROS:
        raise ErroVideo(
            "O vídeo tem só %d quadro(s) legível(is). Grave uns 20 segundos girando "
            "devagar no mesmo ponto." % len(nitidez))

    largura_real = int(np.median(larguras))
    passo = PASSO * LARGURA_ANALISE
    escolhidos = _escolher(nitidez, andado, passo)

    if len(escolhidos) < MINIMO_QUADROS:
        raise ErroVideo(
            "A câmera quase não girou durante o vídeo — não dá para montar um "
            "panorama com isso. Fique parado num ponto e gire devagar, dando a "
            "volta completa em uns 20 a 30 segundos.")

    aviso(18, "separando os %d melhores quadros" % len(escolhidos))

    # segunda passada, sequencial de proposito: procurar quadro por indice depende
    # do codec e erra em alguns MP4 de celular; reler do inicio sempre acerta
    querido = set(escolhidos)
    ordem = {q: n for n, q in enumerate(escolhidos)}
    captura = _abrir(caminho_video)
    salvos = []
    try:
        i = 0
        while querido:
            ok, quadro = captura.read()
            if not ok:
                break
            if i in querido:
                querido.discard(i)
                nome = os.path.join(pasta_saida, "quadro_%02d.jpg" % ordem[i])
                ok2, buf = cv2.imencode(".jpg", quadro, [cv2.IMWRITE_JPEG_QUALITY, 95])
                if ok2:
                    buf.tofile(nome)
                    salvos.append(nome)
            i += 1
    finally:
        captura.release()

    if len(salvos) < MINIMO_QUADROS:
        raise ErroVideo("Não consegui extrair quadros suficientes do vídeo.")

    avisos = ["Do vídeo saíram %d quadros, escolhidos pelo giro da câmera e pela "
              "nitidez — os trechos tremidos foram descartados." % len(salvos)]
    recado = conferir_largura(largura_real)
    if recado:
        avisos.append(recado)
    return sorted(salvos), avisos
