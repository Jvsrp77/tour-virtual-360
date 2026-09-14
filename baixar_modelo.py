# -*- coding: utf-8 -*-
"""
Baixa o modelo de estimativa de profundidade (Depth Anything V2 Small, ONNX).

Precisa rodar uma vez so. O arquivo tem 94 MB e fica em modelos/depth.onnx.
Sem ele o tour continua funcionando - so o modo "andar pelo ambiente" fica
indisponivel.
"""
import os
import sys
import urllib.request

PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelos")
DESTINO = os.path.join(PASTA, "depth.onnx")
URL = ("https://huggingface.co/onnx-community/depth-anything-v2-small"
       "/resolve/main/onnx/model.onnx")

# opcional: reconstroi o que esta atras dos moveis no modo de caminhada
DESTINO_FUNDO = os.path.join(PASTA, "lama.onnx")
URL_FUNDO = "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx"


def progresso(blocos, tamanho_bloco, total):
    if total <= 0:
        return
    pct = min(100, blocos * tamanho_bloco * 100 // total)
    sys.stdout.write("\r  baixando... %d%%" % pct)
    sys.stdout.flush()


def baixar(url, destino, rotulo, mb):
    if os.path.exists(destino) and os.path.getsize(destino) > 1_000_000:
        print("%s ja esta instalado em %s" % (rotulo, destino))
        return 0
    os.makedirs(PASTA, exist_ok=True)
    print("Baixando %s (%d MB)..." % (rotulo, mb))
    try:
        urllib.request.urlretrieve(url, destino + ".parcial", progresso)
    except Exception as e:
        print("\nFalhou: %s" % e)
        print("Baixe manualmente de:\n  %s\ne salve como:\n  %s" % (url, destino))
        return 1
    os.replace(destino + ".parcial", destino)
    print("\nPronto: %s (%.0f MB)" % (destino, os.path.getsize(destino) / 1e6))
    return 0


def main():
    if "--fundo" in sys.argv:
        return baixar(URL_FUNDO, DESTINO_FUNDO,
                      "o modelo de reconstrucao de fundo", 208)
    if os.path.exists(DESTINO) and os.path.getsize(DESTINO) > 1_000_000:
        print("Modelo ja esta instalado em %s" % DESTINO)
        return 0

    os.makedirs(PASTA, exist_ok=True)
    print("Baixando o modelo de profundidade (94 MB)...")
    try:
        urllib.request.urlretrieve(URL, DESTINO + ".parcial", progresso)
    except Exception as e:
        print("\nFalhou: %s" % e)
        print("Baixe manualmente de:\n  %s\ne salve como:\n  %s" % (URL, DESTINO))
        return 1

    os.replace(DESTINO + ".parcial", DESTINO)
    print("\nPronto: %s (%.0f MB)" % (DESTINO, os.path.getsize(DESTINO) / 1e6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
