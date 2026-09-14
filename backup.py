# -*- coding: utf-8 -*-
"""
Copia de seguranca dos dados.

Sao 42 MB numa pasta: tours, panoramas, mapas de profundidade, contas e os
contatos capturados. Um disco que falha leva tudo, e nao ha de onde refazer — as
fotos originais sao apagadas depois que a cena e montada, e profundidade e
camada de fundo custam minutos de CPU cada.

  python backup.py criar
  python backup.py listar
  python backup.py restaurar backups/tour-2026-09-14-1530.zip

CONSISTENCIA. O backup roda fora do processo do servidor, entao nao pega as
travas dele. Nao precisa: o `tour.json` e gravado com `os.replace`, que troca o
arquivo inteiro de uma vez — quem le pega a versao antiga ou a nova, nunca um
meio-termo. As imagens sao escritas uma vez e nunca alteradas. O caso que sobra
e uma cena criada NO MEIO da copia: o tour.json pode entrar sem ela, ou a imagem
entrar sem estar no tour.json. Nenhum dos dois corrompe nada — no pior caso a
cena nao aparece, e o proprio servidor limpa arquivos orfaos no arranque.

As imagens ja sao JPEG e PNG: comprimir de novo gasta CPU e nao ganha nada, so
o JSON e comprimido.
"""
import io
import os
import sys
import json
import shutil
import zipfile
from datetime import datetime

RAIZ = os.path.dirname(os.path.abspath(__file__))
# configuravel para o teste de restauracao rodar numa copia, longe dos dados reais
PASTA_DADOS = os.environ.get("TOUR_DADOS") or os.path.join(RAIZ, "data")
PASTA_BACKUPS = os.environ.get("TOUR_BACKUPS") or os.path.join(RAIZ, "backups")
GUARDAR = int(os.environ.get("TOUR_BACKUPS_GUARDAR", "7"))

# uploads sao temporarios: o servidor os apaga sozinho depois de montar a cena
IGNORAR = ("uploads",)
JA_COMPRIMIDO = (".jpg", ".jpeg", ".png", ".webp", ".zip", ".onnx")


def _arquivos():
    for raiz, pastas, arquivos in os.walk(PASTA_DADOS):
        pastas[:] = [p for p in pastas if p not in IGNORAR]
        for nome in arquivos:
            if nome.endswith(".tmp") or nome.endswith(".parcial"):
                continue                     # gravacao a meio caminho
            caminho = os.path.join(raiz, nome)
            yield caminho, os.path.relpath(caminho, PASTA_DADOS).replace("\\", "/")


def criar(silencioso=False):
    if not os.path.isdir(PASTA_DADOS):
        print("  não há nada em data/ para copiar.")
        return 1
    os.makedirs(PASTA_BACKUPS, exist_ok=True)
    marca = datetime.now().strftime("%Y-%m-%d-%H%M")
    destino = os.path.join(PASTA_BACKUPS, "tour-%s.zip" % marca)
    parcial = destino + ".parcial"

    total = bytes_ = 0
    with zipfile.ZipFile(parcial, "w") as z:
        for caminho, interno in _arquivos():
            ext = os.path.splitext(caminho)[1].lower()
            modo = (zipfile.ZIP_STORED if ext in JA_COMPRIMIDO
                    else zipfile.ZIP_DEFLATED)
            try:
                z.write(caminho, interno, compress_type=modo)
            except (OSError, ValueError):
                continue                     # arquivo sumiu no meio da copia
            total += 1
            bytes_ += os.path.getsize(caminho)
        z.writestr("_backup.json", json.dumps(
            {"criado_em": datetime.now().isoformat(timespec="seconds"),
             "arquivos": total, "bytes": bytes_}, ensure_ascii=False, indent=2))
    os.replace(parcial, destino)             # so vira backup quando esta inteiro

    if not silencioso:
        print("  %s  (%d arquivos, %.1f MB)" % (
            os.path.basename(destino), total, os.path.getsize(destino) / 1048576.))
    return _rodar_rotacao(silencioso)


def _rodar_rotacao(silencioso=False):
    copias = sorted(f for f in os.listdir(PASTA_BACKUPS)
                    if f.startswith("tour-") and f.endswith(".zip"))
    apagadas = 0
    for velha in copias[:-GUARDAR] if GUARDAR > 0 else []:
        os.remove(os.path.join(PASTA_BACKUPS, velha))
        apagadas += 1
    if apagadas and not silencioso:
        print("  %d cópia(s) antiga(s) apagada(s); guardando as %d mais novas"
              % (apagadas, GUARDAR))
    return 0


def listar():
    if not os.path.isdir(PASTA_BACKUPS):
        print("  nenhuma cópia ainda. Rode: python backup.py criar")
        return 0
    copias = sorted(f for f in os.listdir(PASTA_BACKUPS)
                    if f.startswith("tour-") and f.endswith(".zip"))
    if not copias:
        print("  nenhuma cópia ainda. Rode: python backup.py criar")
        return 0
    for nome in copias:
        caminho = os.path.join(PASTA_BACKUPS, nome)
        try:
            with zipfile.ZipFile(caminho) as z:
                meta = json.loads(z.read("_backup.json"))
            extra = "%d arquivos" % meta["arquivos"]
        except Exception:
            extra = "ilegível"
        print("  %-28s %7.1f MB   %s" % (nome, os.path.getsize(caminho) / 1048576., extra))
    return 0


def restaurar(argv):
    if not argv:
        print("  uso: python backup.py restaurar <arquivo.zip>")
        return 1
    origem = argv[0]
    if not os.path.exists(origem):
        origem = os.path.join(PASTA_BACKUPS, argv[0])
    if not os.path.exists(origem):
        print("  não encontrei %s" % argv[0])
        return 1

    print("  ATENÇÃO: isto substitui data/ pelo conteúdo da cópia.")
    print("  Pare o servidor antes, senão ele grava por cima do que for restaurado.")
    if input("  digite RESTAURAR para confirmar: ").strip() != "RESTAURAR":
        print("  cancelado.")
        return 1

    # o que existe hoje vira uma copia antes de ser substituido: restaurar a
    # copia errada nao pode ser um caminho sem volta
    if os.path.isdir(PASTA_DADOS):
        guardado = PASTA_DADOS + "-antes-de-restaurar-" + datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.move(PASTA_DADOS, guardado)
        print("  data/ atual guardado em %s" % os.path.basename(guardado))

    os.makedirs(PASTA_DADOS, exist_ok=True)
    with zipfile.ZipFile(origem) as z:
        for interno in z.namelist():
            if interno == "_backup.json":
                continue
            z.extract(interno, PASTA_DADOS)
    print("  restaurado de %s" % os.path.basename(origem))
    return 0


def main():
    comando = sys.argv[1] if len(sys.argv) > 1 else "listar"
    if comando == "criar":
        return criar()
    if comando == "listar":
        return listar()
    if comando == "restaurar":
        return restaurar(sys.argv[2:])
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
