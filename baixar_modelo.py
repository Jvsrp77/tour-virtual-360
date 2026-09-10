# -*- coding: utf-8 -*-
"""
Baixa o modelo de estimativa de profundidade (Depth Anything V2 Small, ONNX).

Precisa rodar uma vez só. O arquivo tem 94 MB e fica em modelos/depth.onnx.
Sem ele o tour continua funcionando — só o modo "andar pelo ambiente" fica
indisponível.
"""
import os
import sys
import urllib.request

URL = ("https://huggingface.co/onnx-community/depth-anything-v2-small"
       "/resolve/main/onnx/model.onnx")
DESTINO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "modelos", "depth.onnx")


def progresso(blocos, tamanho_bloco, total):
    if total <= 0:
        return
    pct = min(100, blocos * tamanho_bloco * 100 // total)
    sys.stdout.write("\r  baixando... %d%%" % pct)
    sys.stdout.flush()


def main():
    if os.path.exists(DESTINO) and os.path.getsize(DESTINO) > 1_000_000:
        print("Modelo já está instalado em %s" % DESTINO)
        return 0

    os.makedirs(os.path.dirname(DESTINO), exist_ok=True)
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
