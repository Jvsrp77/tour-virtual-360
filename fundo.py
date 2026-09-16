# -*- coding: utf-8 -*-
"""
Camada de fundo: o comodo como seria sem os moveis da frente.

Caminhando pelo ambiente, o visitante sai do ponto onde a foto foi tirada e passa
a enxergar atras das coisas — atras da mesa, ao lado do armario. Ali nao existe
foto: a camera nunca viu. A malha preenchia esticando a textura da borda, o que
virava borrao.

Aqui o vao ganha conteudo proprio: uma segunda camada, com textura e profundidade
do que provavelmente esta atras, desenhada atras da camada real. O que a foto viu
continua sendo o que a foto viu; so o vao e reconstruido.

E CONTEUDO GERADO. Nao e o imovel: e a continuacao plausivel do que a foto mostra.
Por isso a cena marca `fundo_gerado` e o visualizador avisa na tela.

Por que LaMa e nao cv2.inpaint: medido no quarto de teste, o classico transforma
caneca em borrao e desfigura o violao na parede — ele foi feito para risco fino,
nao para remover objeto. O LaMa preserva quina de mesa, canto de parede e o
desenho do piso. (O mesmo LaMa havia perdido para a tecnica simples no TETO, que
e caso degenerado: polo, superficie lisa, sem estrutura para preservar.)
"""
import os

os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "disabled")

import cv2
import numpy as np

LADO = 512                 # o modelo so aceita 512x512
PASSO = 384                # sobreposicao entre ladrilhos, para nao marcar emenda
LARGURA_FUNDO = 2048       # o fundo aparece so por frestas: nao precisa da resolucao cheia
# Quanto um vizinho precisa estar mais longe para contar como degrau.
#
# TEM DE ACOMPANHAR `SALTO_MAX` do static/andar.html, e sempre por BAIXO. La o
# triangulo vira duvidoso com degrau acima de 18% (SALTO_MAX = 0.18) e SOME da
# camada real; aqui se decide o que a IA reconstroi para aparecer no lugar. Com
# este valor em 1.20, o degrau entre 18% e 20% sumia sem ter nada atras — e o
# visitante via um rasgo preto, exatamente o defeito que a camada existe para
# eliminar. Medido na cena do quarto: rasgos pretos ao caminhar 1,4 m, mesmo com
# a camada gerada.
#
# 1.15 deixa margem: tudo que o visualizador apaga tem conteudo por tras. O preco
# e reconstruir um pouco mais da imagem, e isso e conteudo GERADO — por isso a
# porcentagem sobe e o visualizador continua avisando na tela.
SALTO = 1.15
SESSAO = None


class ErroFundo(Exception):
    pass


def caminho_modelo():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "modelos", "lama.onnx")


def modelo_disponivel():
    return os.path.exists(caminho_modelo())


def _sessao():
    global SESSAO
    if SESSAO is None:
        if not modelo_disponivel():
            raise ErroFundo(
                "O modelo de reconstrução não está instalado. Rode "
                "'python baixar_modelo.py --fundo' uma vez (208 MB).")
        import onnxruntime as ort
        provedores = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider")
                      if p in ort.get_available_providers()]
        SESSAO = ort.InferenceSession(caminho_modelo(), providers=provedores)
    return SESSAO


def _mascara_da_frente(raio, largura):
    """
    Marca o que esta na FRENTE de um degrau de profundidade.

    E esse pedaco que some na camada de fundo: ele e que esconde o resto. A margem
    define quanto paralaxe a camada aguenta antes de acabar o conteudo gerado.
    """
    janela = max(3, (largura // 160) | 1)
    longe = cv2.dilate(raio, np.ones((janela, janela), np.float32))
    frente = (longe > raio * SALTO).astype(np.uint8)
    return cv2.dilate(frente, np.ones((janela, janela), np.uint8), iterations=2)


def _inpaint(img, masc, relatar=None):
    """Percorre a imagem em ladrilhos de 512 e mistura as bordas com janela suave."""
    ses = _sessao()
    H, W = img.shape[:2]
    acumulado = np.zeros((H, W, 3), np.float32)
    peso = np.zeros((H, W, 1), np.float32)
    janela = np.hanning(LADO)[:, None] * np.hanning(LADO)[None, :]
    janela = np.maximum(janela, 0.02)[..., None].astype(np.float32)

    ys = list(range(0, max(1, H - 1), PASSO))
    xs = list(range(0, max(1, W - 1), PASSO))
    total = len(ys) * len(xs)
    feitos = 0

    for y0 in ys:
        for x0 in xs:
            y = min(y0, max(0, H - LADO))
            x = min(x0, max(0, W - LADO))
            bloco = img[y:y + LADO, x:x + LADO]
            m = masc[y:y + LADO, x:x + LADO]
            if bloco.shape[0] < LADO or bloco.shape[1] < LADO:
                bloco = cv2.copyMakeBorder(bloco, 0, LADO - bloco.shape[0],
                                           0, LADO - bloco.shape[1], cv2.BORDER_REFLECT)
                m = cv2.copyMakeBorder(m, 0, LADO - m.shape[0], 0, LADO - m.shape[1],
                                       cv2.BORDER_CONSTANT, value=0)

            if m.max() == 0:
                saida = bloco.astype(np.float32)      # nada a reconstruir aqui
            else:
                entrada = cv2.cvtColor(bloco, cv2.COLOR_BGR2RGB)
                entrada = entrada.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
                mascara = (m > 0).astype(np.float32)[None, None]
                bruto = ses.run(None, {"image": entrada, "mask": mascara})[0][0]
                bruto = bruto.transpose(1, 2, 0)
                if bruto.max() <= 1.01:               # algumas exportacoes saem em 0..1
                    bruto = bruto * 255.0
                saida = cv2.cvtColor(np.clip(bruto, 0, 255).astype(np.uint8),
                                     cv2.COLOR_RGB2BGR).astype(np.float32)

            alt = min(LADO, H - y)
            lar = min(LADO, W - x)
            acumulado[y:y + alt, x:x + lar] += saida[:alt, :lar] * janela[:alt, :lar]
            peso[y:y + alt, x:x + lar] += janela[:alt, :lar]

            feitos += 1
            if relatar and feitos % 4 == 0:
                relatar(int(feitos * 100.0 / total), "reconstruindo o que está atrás")

    return np.clip(acumulado / np.maximum(peso, 1e-6), 0, 255).astype(np.uint8)


def gerar(caminho_panorama, caminho_profundidade, relatar=None):
    """
    Devolve (textura_de_fundo, disparidade_de_fundo, informacao).

    A profundidade do fundo recebe o valor do que esta ATRAS do degrau: sem isso a
    camada nova nasceria na mesma distancia do movel que ela deveria substituir.
    """
    dados = np.fromfile(caminho_panorama, dtype=np.uint8)
    pano = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if pano is None:
        raise ErroFundo("Não consegui abrir o panorama.")

    png = cv2.imdecode(np.fromfile(caminho_profundidade, dtype=np.uint8), cv2.IMREAD_COLOR)
    if png is None:
        raise ErroFundo("Não consegui abrir o mapa de profundidade.")
    disp = (((png[:, :, 2].astype(np.uint32) << 8) |
             png[:, :, 1]).astype(np.float32) / 65535.0)

    largura = min(LARGURA_FUNDO, pano.shape[1])
    altura = largura // 2
    pano = cv2.resize(pano, (largura, altura), interpolation=cv2.INTER_AREA)
    disp = cv2.resize(disp, (largura, altura), interpolation=cv2.INTER_CUBIC)

    raio = 1.0 / (1.542 * disp + 0.125)
    frente = _mascara_da_frente(raio, largura)
    fracao = float(frente.mean())
    if fracao < 0.002:
        raise ErroFundo(
            "Esta cena quase não tem objeto na frente de parede — não há vão a "
            "reconstruir. A camada de fundo não traria diferença.")

    textura = _inpaint(pano, frente, relatar)

    # profundidade do fundo: onde havia movel, vale o que esta atras dele
    janela = max(3, (largura // 160) | 1)
    atras = cv2.dilate(raio, np.ones((janela * 3, janela * 3), np.float32))
    raio_fundo = np.where(frente > 0, atras, raio)
    raio_fundo = cv2.GaussianBlur(raio_fundo, (0, 0), sigmaX=janela * 0.5)
    # Invariante: o fundo nunca esta mais perto do que o que a foto viu. Sem isso
    # o desfoque puxa valores para perto e a camada gerada nasce NA FRENTE da
    # real, cobrindo movel que existe — medido na tela, tapava a mesa inteira.
    raio_fundo = np.maximum(raio_fundo, raio)
    disp_fundo = np.clip((1.0 / np.maximum(raio_fundo, 0.05) - 0.125) / 1.542, 0.0, 1.0)

    # o fundo e liso e so aparece por frestas: metade da resolucao poupa ~1,8 MB
    disp_fundo = cv2.resize(disp_fundo, (largura // 2, altura // 2),
                            interpolation=cv2.INTER_AREA)

    return textura, disp_fundo.astype(np.float32), {
        "reconstruido": round(fracao * 100, 2),
        "largura": largura,
        "altura": altura,
    }
