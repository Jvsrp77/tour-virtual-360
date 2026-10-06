# -*- coding: utf-8 -*-
"""
Monta um imovel no servidor a partir de uma planta JA RENDERIZADA.

  python publicar.py casa_grande
  python publicar.py casa_grande --titulo "Casa de 520 m2" --preco "R$ 6.900.000"

POR QUE EXISTE. As plantas sinteticas viram tour por este caminho, e nao pela
tela de upload: a tela recebe foto e nao sabe de onde ela foi tirada, enquanto
aqui a POSICAO de cada ponto e a PROFUNDIDADE exata vem da propria planta. E a
profundidade exata e o que permite caminhar sem borrao — o modelo de IA deduz a
profundidade da imagem e erra no contorno dos moveis, que e a origem do
escorrido.

Existiu um script assim antes, de uma vez so, e se perdeu. Por isso agora e
codigo do produto, com teste: refazer a mansao dependia dele.

O QUE ELE NAO FAZ: nao mexe em imovel que ja existe. Cada chamada cria um
imovel novo, com id novo. Republicar e criar outro e apagar o antigo pela tela
— de proposito, porque sobrescrever um tour publicado apagaria os leads e as
visitas que ele ja acumulou.
"""
import argparse
import datetime
import io
import json
import os
import sys
import uuid

import cv2
import numpy as np

import cena_apartamento
import ladrilhos
import plantas
import profundidade

AQUI = os.path.dirname(os.path.abspath(__file__))
PASTA_DADOS = os.path.join(AQUI, "data", "imoveis")
LARGURA_CENA = 4096             # o dobro basta na tela; 8k so pesa no 4G
LARGURA_MINI = 480
QUALIDADE = 90


def _hex_rgb(bgr):
    """
    A cor do material, em #rrggbb.

    MATERIAIS guarda BGR, que e a ordem do OpenCV. O conversor anterior gravava
    a tupla crua como se fosse RGB, e a maquete 3D de todos os imoveis
    sinteticos ficou com os canais trocados: o piso de madeira, que e o marrom
    #867060, saiu como #607086 — azul. Aqui inverte.
    """
    b, g, r = bgr
    return "#%02x%02x%02x" % (r, g, b)


def _gravar_jpg(img, caminho, q=QUALIDADE):
    # imwrite falha calado em caminho com acento, e a Area de Trabalho tem um
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        raise RuntimeError("falha ao codificar %s" % caminho)
    buf.tofile(caminho)


def _ler(caminho):
    img = cv2.imdecode(np.fromfile(caminho, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("nao consegui ler %s" % caminho)
    return img


def maquete_da_planta(planta):
    """A geometria em metros, do jeito que o visor 3D consome."""
    cor = cena_apartamento.MATERIAIS
    zonas = []
    for nome, x0, x1, z0, z1, parede, piso in planta["zonas"]:
        zonas.append({
            "nome": nome, "x0": x0, "x1": x1, "z0": z0, "z1": z1,
            "m2": round((x1 - x0) * (z1 - z0), 1),
            "piso": _hex_rgb(cor[piso]), "parede": _hex_rgb(cor[parede]),
            # o NOME do material, e nao so a cor: e com ele que a maquete 3D
            # busca o ladrilho e veste a mesma textura que o panorama tem
            "piso_m": piso, "parede_m": parede,
        })
    caixas = [{"p": [c[0], c[1], c[2], c[3], c[4], c[5]],
               "m": c[6], "cor": _hex_rgb(cor[c[6]])}
              for c in planta["caixas"]]
    return {
        "nome": planta["nome"],
        "descricao": planta.get("descricao", ""),
        "larg": planta["larg"], "fundo": planta["fundo"],
        "pe": plantas.PE_DIREITO,
        "zonas": zonas, "caixas": caixas,
        "janelas": [list(j) for j in planta["janelas"]],
        "pontos": [{"nome": n, "x": x, "z": z} for n, x, z in planta["pontos"]],
    }


def preparar_cena(origem_jpg, origem_npy, destino, base, cena_id, aviso):
    """
    Grava os cinco arquivos de uma cena e devolve o que vai no tour.

    A profundidade NAO passa pelo modelo de IA: ela ja e exata, veio do
    tracador. E essa a vantagem do imovel sintetico sobre a foto.
    """
    cheio = _ler(origem_jpg)

    # Os ladrilhos saem do ORIGINAL, antes de reduzir: e justamente o detalhe
    # que a reducao jogava fora que eles existem para entregar. O tracador
    # grava 8192 e o visor recebia 4096 — ja ampliado 1,7x numa tela de 1920.
    #
    # So para panorama completo. Em cena parcial as faces do cubo que caem no
    # que a foto nao cobre sairiam pretas, e preto num tour parece defeito de
    # carregamento, nao limite de captura.
    multires = None
    if cheio.shape[1] >= 2 * ladrilhos.LADO_DO_LADRILHO:
        pasta_lad = "ladrilhos_%s" % cena_id
        try:
            multires = ladrilhos.gerar(cheio, os.path.join(destino, pasta_lad))
            multires["basePath"] = pasta_lad
        except Exception as erro:      # ladrilho e melhoria, nao requisito
            aviso("ladrilhos de %s nao gerados: %s" % (base, erro))
            multires = None

    panorama = cheio
    alvo = (LARGURA_CENA, LARGURA_CENA // 2)
    if panorama.shape[1] != LARGURA_CENA:
        panorama = cv2.resize(panorama, alvo, interpolation=cv2.INTER_AREA)
    arquivo = "%s.jpg" % base
    # o equirretangular CONTINUA: a caminhada projeta a foto numa malha e
    # precisa dela inteira, e ele ainda e a reserva de quem nao tem WebGL
    _gravar_jpg(panorama, os.path.join(destino, arquivo))

    mini = cv2.resize(panorama, (LARGURA_MINI, LARGURA_MINI // 2),
                      interpolation=cv2.INTER_AREA)
    nome_mini = "mini_%s.jpg" % base
    _gravar_jpg(mini, os.path.join(destino, nome_mini), 78)

    disp = np.load(origem_npy).astype(np.float32)
    nome_prof = "prof_%s.png" % cena_id
    profundidade.salvar(disp, os.path.join(destino, nome_prof))

    previa = cv2.applyColorMap((np.clip(disp, 0, 1) * 255).astype(np.uint8),
                               cv2.COLORMAP_INFERNO)
    nome_prev = "prev_%s.jpg" % cena_id
    _gravar_jpg(previa, os.path.join(destino, nome_prev), 85)

    cena = {
        "id": cena_id, "nome": None, "arquivo": arquivo,
        "largura": panorama.shape[1], "altura": panorama.shape[0],
        "origem": "sintetica", "panorama_completo": True,
        "haov": 360.0, "vaov": 180.0,
        "vista_inicial": {"yaw": 0, "pitch": 0, "hfov": 100},
        "hotspots": [], "miniatura": nome_mini,
        "profundidade": nome_prof, "previa_profundidade": nome_prev,
    }
    if multires:
        cena["multires"] = multires
    try:
        medida = profundidade.medir_escorrido(panorama, disp)
        if medida:
            cena["escorrido"] = medida
    except Exception as erro:          # medida e informacao, nao pode derrubar
        aviso("escorrido de %s nao medido: %s" % (base, erro))
    return cena


def pontos_faltando(fotos, quantos):
    """
    Quais pontos ainda nao estao no disco, com foto E profundidade.

    Exige os DOIS arquivos, pelo mesmo motivo que o render exige ao retomar: um
    ponto que gravou a foto e morreu antes do mapa esta pela metade, e metade e
    pior do que nada — parece pronto.

    Publicar pela metade e pior ainda: o tour abre, parece inteiro, e falta
    comodo. O render de 520 m2 leva horas e ja foi interrompido tres vezes.
    """
    return [i for i in range(quantos)
            if not (os.path.exists(os.path.join(fotos, "ponto_%d.jpg" % i))
                    and os.path.exists(os.path.join(fotos, "dist_%d.npy" % i)))]


def _esbocos(imovel, cenas, saida):
    """
    O poster da vista inicial de cada cena: 30 KB que chegam em 0,2 s, no lugar
    de 1,3 MB de panorama que levam quase 7 s em 4G fraco.

    O `app` e importado AQUI DENTRO, e nao no topo: quem so quer gerar os
    arquivos do imovel nao deveria precisar do Flask instalado. Faltando, o
    proprio servidor completa os esbocos na proxima vez que subir.
    """
    try:
        import app
    except Exception as erro:
        saida("  sem esbocos (%s) — o servidor gera ao subir" % erro)
        return
    feitos = 0
    for cena in cenas:
        nome = app.gerar_esboco(imovel, cena)
        if nome:
            cena["esboco"] = nome
            feitos += 1
    saida("  %d esboço(s) de abertura" % feitos)


def publicar(pasta, titulo=None, descricao=None, endereco="", preco="",
             conta=None, cor="#e07b39", frente=0, saida=print):
    planta = next((f() for f in plantas.TODAS if f()["pasta"] == pasta), None)
    if planta is None:
        raise SystemExit("  nao conheco a planta %r" % pasta)

    fotos = os.path.join(AQUI, "fotos_" + pasta)
    faltam = pontos_faltando(fotos, len(planta["pontos"]))
    if faltam:
        raise SystemExit("  faltam %d pontos renderizados em %s (o primeiro e o %d)"
                         % (len(faltam), fotos, faltam[0]))

    imovel = uuid.uuid4().hex[:10]
    destino = os.path.join(PASTA_DADOS, imovel, "scenes")
    os.makedirs(destino, exist_ok=True)
    saida("  imovel %s  <-  %s (%d pontos)" % (imovel, pasta, len(planta["pontos"])))

    cenas = []
    for i, (nome, x, z) in enumerate(planta["pontos"]):
        cena_id = uuid.uuid4().hex[:10]
        cena = preparar_cena(os.path.join(fotos, "ponto_%d.jpg" % i),
                             os.path.join(fotos, "dist_%d.npy" % i),
                             destino, "cena_%s_%02d" % (pasta, i), cena_id,
                             saida)
        cena["nome"] = nome
        cena["posicao"] = {"x": round(float(x), 3), "y": round(float(z), 3)}
        cenas.append(cena)
        if (i + 1) % 20 == 0 or i + 1 == len(planta["pontos"]):
            saida("    %3d de %d" % (i + 1, len(planta["pontos"])))

    _esbocos(imovel, cenas, saida)

    tour = {
        "titulo": titulo or planta["nome"],
        "descricao": descricao or planta.get("descricao", ""),
        "endereco": endereco, "preco": preco, "logo": "", "cor": cor,
        "cena_inicial": cenas[0]["id"], "cenas": cenas,
        "lead": {"ativo": True, "titulo": "Gostou do imóvel?",
                 "texto": "Deixe seu contato que um corretor fala com você.",
                 "segundos": 45},
        "leads_capturados": [], "visitas": [],
        "conta": conta,
        "criado_em": datetime.datetime.now().replace(microsecond=0).isoformat(),
        "frente": frente,
    }
    base = os.path.join(PASTA_DADOS, imovel)
    io.open(os.path.join(base, "tour.json"), "w", encoding="utf-8").write(
        json.dumps(tour, ensure_ascii=False, indent=1))
    io.open(os.path.join(base, "maquete.json"), "w", encoding="utf-8").write(
        json.dumps(maquete_da_planta(planta), ensure_ascii=False))
    saida("  pronto: /tour/%s   (caminhada em /andar/%s)" % (imovel, imovel))
    return imovel


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pasta")
    p.add_argument("--titulo")
    p.add_argument("--descricao")
    p.add_argument("--endereco", default="")
    p.add_argument("--preco", default="")
    p.add_argument("--conta")
    p.add_argument("--cor", default="#e07b39")
    p.add_argument("--frente", type=int, default=0)
    a = p.parse_args()
    publicar(a.pasta, a.titulo, a.descricao, a.endereco, a.preco,
             a.conta, a.cor, a.frente)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
