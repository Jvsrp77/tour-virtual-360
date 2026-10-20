# -*- coding: utf-8 -*-
"""
Repinta UMA cena, de ponta a ponta, e grava o antes e o depois.

  python repintar_cena.py sobrado 10 "sala de estar ampla, luz da tarde"

Uma cena de proposito. Antes de gastar as 49, o que precisa ser respondido e
se o resultado vale: se os moveis viram moveis, se a planta e respeitada, e se
as oito vistas concordam nas bordas. Isso se ve numa cena — e se nao valer,
custou uma.

Sem chave de modelo, roda assim mesmo com o repintor IDENTIDADE: nao repinta
nada, mas exercita o caminho inteiro e mede a costura. E o que deixa o dia da
chave ser so trocar uma linha.
"""
import argparse
import os
import sys

import cv2
import numpy as np

import repintar

AQUI = os.path.dirname(os.path.abspath(__file__))


# O OpenCV do Windows nao abre caminho com acento, e este projeto mora em
# "Área de Trabalho". imread devolve None sem dizer por que, e parece arquivo
# faltando. Ler os bytes em Python e decodificar na memoria resolve, e vale
# para qualquer maquina.
def ler_imagem(caminho):
    if not os.path.exists(caminho):
        return None
    with open(caminho, "rb") as f:
        dados = np.frombuffer(f.read(), np.uint8)
    return cv2.imdecode(dados, cv2.IMREAD_COLOR)


def gravar_imagem(caminho, img, qualidade=92):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, qualidade])
    if not ok:
        raise RuntimeError("falha ao codificar %s" % caminho)
    with open(caminho, "wb") as f:
        f.write(buf.tobytes())


def metros(disp):
    """O .npy guarda disparidade: r = 1 / (1,542 d + 0,125)."""
    return (1.0 / np.maximum(disp, 1e-6) - 0.125) / 1.542


def guia_de_profundidade(disp):
    """Perto claro, longe escuro, normalizado por percentil."""
    baixo, alto = np.percentile(disp, 2), np.percentile(disp, 98)
    v = np.clip((disp - baixo) / max(alto - baixo, 1e-6), 0, 1)
    return (255 * v).astype(np.uint8)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pasta")
    p.add_argument("ponto", type=int)
    p.add_argument("descricao", nargs="?", default="")
    p.add_argument("--largura", type=int, default=4096,
                   help="largura do equirretangular de saida")
    p.add_argument("--lado", type=int, default=1024,
                   help="lado de cada vista entregue ao modelo")
    p.add_argument("--vistas", type=int, default=0,
                   help="quantas das 8 direcoes repintar (0 = todas). Comece "
                        "com 1: uma imagem basta para ver se o visual presta, "
                        "e a costura so importa depois que ele prestar")
    a = p.parse_args()

    base = os.path.join(AQUI, "fotos_" + a.pasta)
    equi = ler_imagem(os.path.join(base, "ponto_%d.jpg" % a.ponto))
    if equi is None:
        raise SystemExit("nao achei o panorama do ponto %d" % a.ponto)
    disp = np.load(os.path.join(base, "dist_%d.npy" % a.ponto))

    alvo = (a.largura, a.largura // 2)
    equi = cv2.resize(equi, alvo, interpolation=cv2.INTER_AREA)
    disp = cv2.resize(disp, alvo, interpolation=cv2.INTER_NEAREST)
    m = metros(disp)
    print("cena %s/%d  %dx%d  de %.1f a %.1f m"
          % (a.pasta, a.ponto, alvo[0], alvo[1],
             np.percentile(m, 2), np.percentile(m, 98)))

    try:
        import repintor_ia
        pintor = repintor_ia.de_replicate()
        print("repintor: Replicate (ControlNet de profundidade)")
    except Exception as erro:
        pintor = repintar.identidade
        print("repintor: IDENTIDADE — %s" % str(erro).splitlines()[0])
        print("  (o caminho roda inteiro; so nao ha repintura)")

    saida = os.path.join(AQUI, "repintura")
    os.makedirs(saida, exist_ok=True)

    # A profundidade entregue ao modelo e o guia cinza, nao a disparidade
    # crua. Cada vista e gravada antes e depois: e nela que se ve se o movel
    # virou movel, e e ela que vale olhar antes de pagar as outras sete.
    feitas = [0]

    def adaptado(vista, prof, descricao):
        guia = guia_de_profundidade(prof)
        n = feitas[0]
        feitas[0] += 1
        nova = pintor(vista, guia, descricao)
        for rotulo, img in (("vista", vista), ("guia", guia), ("nova", nova)):
            gravar_imagem(os.path.join(
                saida, "%s_%d_%s_%d.jpg" % (a.pasta, a.ponto, rotulo, n)), img)
        return nova

    direcoes = repintar.direcoes_padrao()
    if a.vistas:
        direcoes = direcoes[:a.vistas]
        print("repintando %d de %d direcoes — o resto fica como esta"
              % (len(direcoes), len(repintar.direcoes_padrao())))

    novo, vazio = repintar.repintar(equi, disp, a.descricao,
                                    repintor=adaptado, direcoes=direcoes,
                                    lado=a.lado)
    novo = np.clip(novo, 0, 255).astype(np.uint8)

    dif = np.abs(novo.astype(np.int16) - equi.astype(np.int16)).max(axis=2)
    porcol = dif.mean(axis=0)
    print("\nmudou %.1f niveis de 255 em media (0 = nao repintou)"
          % dif.mean())
    print("sem cobertura: %d pixels" % int(vazio.sum()))
    print("pior coluna / mediana: %.2fx  (emenda aparece aqui)"
          % (porcol.max() / max(np.median(porcol), 1e-6)))

    antes = os.path.join(saida, "%s_%d_antes.jpg" % (a.pasta, a.ponto))
    depois = os.path.join(saida, "%s_%d_depois.jpg" % (a.pasta, a.ponto))
    gravar_imagem(antes, equi)
    gravar_imagem(depois, novo)
    print("\ngravados:\n  %s\n  %s" % (antes, depois))
    print("  e, por vista: %s_%d_vista_N (antes), _guia_N, _nova_N (depois)"
          % (a.pasta, a.ponto))
    if a.vistas:
        print("\nAVISO: com %d de %d direcoes a ESFERA fica INCOMPLETA. O"
              " preto nela e o que" % (len(direcoes),
                                       len(repintar.direcoes_padrao())))
        print("nao foi coberto, nao defeito — e por isso que 'sem cobertura'"
              " acusa milhoes de")
        print("pixels. O que vale olhar agora e _vista_0 contra _nova_0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
