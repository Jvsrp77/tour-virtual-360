# -*- coding: utf-8 -*-
"""
Uma cena repintada, a casa inteira coerente.

O PROBLEMA. Cada panorama era repintado pela IA por conta propria. O modelo
nao sabe que a parede da sala vista do ponto 3 e a MESMA parede vista do
ponto 7: ele inventa uma tabua boa para cada foto, e sao tabuas diferentes.
Enquanto cada cena era mostrada sozinha, isso passava. Depois que a maquete
passou a MISTURAR as fotos vizinhas num mesmo pedaco de parede, as duas
versoes aparecem juntas — e o que se ve e um fantasma na faixa onde elas se
encontram.

A SAIDA NAO E PEDIR COERENCIA AO MODELO. E nao perguntar duas vezes.

Repinta-se UMA cena — a mestra — e as outras recebem a aparencia dela por
geometria: para cada pixel da cena B descobre-se o ponto do mundo que ele
enxerga, e vai-se buscar a cor daquele mesmo ponto na cena A. Isso e o
reprojetar.levar(), que ja existia aqui sem ninguem chamar.

De quebra sai mais barato: uma CENA repintada em vez de 49. Uma cena custa
SEIS chamadas — o anel tem seis vistas —, entao cerca de US$ 0,18 a US$ 0,03
por imagem. Repintar o sobrado inteiro seriam US$ 8,82.

O QUE SOBRA SAO OS BURACOS: o que B enxerga e A nao enxergava — atras de um
movel, dentro de um comodo que A nao via, e as calotas de zenite e nadir que
A nao teve repintadas. Eles sao preenchidos nesta ordem:

  1. por OUTRA cena ja pronta, se alguma delas enxergava aquele ponto. Esta e
     a unica fonte que preserva a coerencia, e por isso as cenas sao feitas
     em ordem de distancia da mestra: quando chega a vez de uma cena, todas
     as mais proximas da mestra ja estao prontas e disponiveis;
  2. so o que NENHUMA cena pronta viu e inventado, e ai por preenchimento
     classico, que estende textura da borda. Inventar com IA aqui traria de
     volta exatamente a incoerencia que este arquivo existe para evitar.

Uso:

    python coerencia.py sobrado --mestre 0 "sala de estar moderna"
    python coerencia.py sobrado --mestre 0 --reaproveitar   (sem gastar API)
"""
import argparse
import os

import cv2
import numpy as np

import reprojetar

AQUI = os.path.dirname(os.path.abspath(__file__))

# Abaixo disto o buraco e pequeno demais para valer uma busca em outra cena:
# sao pixels soltos de borda, e o preenchimento classico resolve melhor e mais
# rapido do que costurar um retalho de dois pixels vindo de longe.
BURACO_MINIMO = 12

# Ate onde uma cena pronta pode socorrer outra. Alem disso a reprojecao estica
# demais: o pixel vem de tao longe que chega borrado, e borrado coerente ainda
# e borrado.
ALCANCE_DO_SOCORRO = 6.0


def ler_imagem(caminho):
    """cv2.imread nao abre caminho com acento no Windows."""
    dados = np.fromfile(caminho, dtype=np.uint8)
    return cv2.imdecode(dados, cv2.IMREAD_COLOR) if dados.size else None


def gravar_imagem(caminho, img, qualidade=92):
    ok, buf = cv2.imencode(".jpg", img,
                           [int(cv2.IMWRITE_JPEG_QUALITY), qualidade])
    if not ok:
        raise IOError("nao consegui codificar %s" % caminho)
    buf.tofile(caminho)


def ordem_de_propagacao(origens, mestres):
    """
    As cenas, da mais proxima de alguma mestra para a mais distante.

    A ORDEM E O QUE FAZ O SOCORRO FUNCIONAR. Indo das mestras para fora,
    quando chega a vez de uma cena as mais proximas dela ja estao prontas — e
    sao justamente elas as que mais tem chance de ter enxergado o que falta.
    Em ordem arbitraria, metade dos buracos seria inventada por falta de
    vizinha pronta, e a casa voltaria a ser incoerente: em manchas, em vez de
    inteira.
    """
    if isinstance(mestres, int):
        mestres = [mestres]
    o = np.asarray(origens, np.float32)
    d = np.min(np.linalg.norm(o[:, None, :] - o[list(mestres)][None, :, :],
                              axis=-1), axis=1)
    return [int(i) for i in np.argsort(d) if int(i) not in set(mestres)]


def escolher_mestres(origens, quantas):
    """
    Quais cenas a IA repinta: espalhadas, nunca amontoadas.

    MEDIDO no sobrado de 445 m2 com UMA mestra: os pontos vizinhos sairam com
    erro de 4 a 15 (contra 29 a 43 sem propagacao nenhuma), mas os pontos de
    outros comodos sairam com 98% de BURACO — a mestra nao enxerga o que
    esta atras de duas paredes, e nenhuma geometria conserta isso. Uma cena
    nao cobre uma casa.

    Entao as mestras sao escolhidas espalhando: comeca pela mais central, e
    cada seguinte e a mais LONGE de todas as ja escolhidas. E a mesma conta
    que a maquete usa para distribuir textura, pelo mesmo motivo — o que
    falta nao e detalhe num canto, e cobertura em todo lugar.

    QUANTAS PAGAR. Medido em 12 cenas do sobrado, comparando o resultado com
    a foto real de cada ponto (erro medio por canal, 0 a 255):

        mestras   custo   erro   inventado
           1      $0,18   38,6     33,5%
           2      $0,36   39,4     34,5%
           3      $0,54   29,1     28,6%
           4      $0,72   15,0      9,6%
           6      $1,08    5,0      7,7%
        sem propagacao nenhuma: 51,2

    Duas notas que o numero da e a intuicao nao daria:

    DUAS MESTRAS E PIOR QUE UMA. Espalhando, as duas vao para extremos
    opostos, e cada cena do meio fica longe das duas. So a partir de tres a
    cobertura comeca a valer.

    E A ECONOMIA NAO E O PONTO. Na proporcao que presta — perto de uma
    mestra para cada duas cenas — o sobrado de 49 pontos custaria uns
    US$ 4,32 contra US$ 8,82 repintando tudo. Metade do preco e bem-vinda,
    mas quem paga o trabalho e a COERENCIA: repintando cada cena por conta
    propria, o preco e o mesmo de sempre e a parede continua mudando de
    tabua de um ponto para o outro.
    """
    o = np.asarray(origens, np.float32)
    meio = o.mean(axis=0)
    escolhidas = [int(np.argmin(np.linalg.norm(o - meio[None, :], axis=1)))]
    while len(escolhidas) < min(quantas, len(o)):
        d = np.min(np.linalg.norm(o[:, None, :] - o[escolhidas][None, :, :],
                                  axis=-1), axis=1)
        escolhidas.append(int(np.argmax(d)))
    return sorted(escolhidas)


def socorrer(alvo, furo, disp_alvo, origem_alvo, prontas):
    """
    Tapa o que der com cena JA PRONTA, e devolve (imagem, furo que sobrou).

    `prontas` e uma lista de (pano, disp, origem), da mais util para a menos.
    """
    sobrou = furo.copy()
    for pano, disp, origem in prontas:
        if not sobrou.any():
            break
        if np.linalg.norm(np.asarray(origem, np.float32)
                          - np.asarray(origem_alvo, np.float32)) > ALCANCE_DO_SOCORRO:
            continue
        levado, furo_dela = reprojetar.levar(pano, disp, origem,
                                             disp_alvo, origem_alvo)
        # so onde ELA enxergava e EU nao tinha
        serve = sobrou & ~furo_dela
        if not serve.any():
            continue
        alvo = np.where(serve[:, :, None], levado, alvo)
        sobrou = sobrou & ~serve
    return alvo, sobrou


def inventar(img, furo):
    """
    O que ninguem viu. Estende a textura da borda, sem perguntar a IA.

    Perguntar a IA aqui traria de volta a incoerencia que este arquivo existe
    para evitar: o modelo inventaria uma tabua diferente para cada buraco, e
    os buracos ficam justamente nas emendas, que e onde a diferenca aparece.
    """
    if not furo.any():
        return img
    mascara = (furo.astype(np.uint8)) * 255
    # dilatar um pouco: a borda do buraco costuma trazer meio pixel da cor
    # errada, e o preenchimento que parte dela espalha o erro para dentro
    mascara = cv2.dilate(mascara, np.ones((3, 3), np.uint8), iterations=1)
    return cv2.inpaint(img, mascara, 4, cv2.INPAINT_TELEA)


def propagar(panos, disps, origens, mestres, relatar=print):
    """
    Leva a aparencia das cenas mestras para todas as outras.

    Devolve a lista de panoramas, com as mestras intactas e o resto refeito.
    """
    if isinstance(mestres, int):
        mestres = [mestres]
    mestres = list(mestres)
    saida = list(panos)
    prontas = [(saida[m], disps[m], origens[m]) for m in mestres]
    for i in ordem_de_propagacao(origens, mestres):
        # a mestra MAIS PROXIMA e a fonte: puxar de uma mestra do outro lado
        # da casa seria pedir para a geometria tapar o que ela nao pode
        mestre = min(mestres, key=lambda m: float(np.linalg.norm(
            np.asarray(origens[m], np.float32)
            - np.asarray(origens[i], np.float32))))
        levado, furo = reprojetar.levar(saida[mestre], disps[mestre],
                                        origens[mestre], disps[i], origens[i])
        antes = int(furo.sum())
        # as prontas mais proximas desta cena socorrem primeiro
        perto = sorted(prontas, key=lambda q: np.linalg.norm(
            np.asarray(q[2], np.float32) - np.asarray(origens[i], np.float32)))
        levado, sobrou = socorrer(levado, furo, disps[i], origens[i], perto)
        depois = int(sobrou.sum())
        if depois < BURACO_MINIMO:
            sobrou[:] = False
        saida[i] = inventar(levado, sobrou)
        total = furo.size
        relatar("  ponto %-3d  furo %5.2f%% -> socorrido %5.2f%% -> "
                "inventado %5.2f%%"
                % (i, 100.0 * antes / total,
                   100.0 * (antes - depois) / total,
                   100.0 * depois / total))
        prontas.append((saida[i], disps[i], origens[i]))
    return saida


def main():
    p = argparse.ArgumentParser(description=__doc__.split("Uso:")[0])
    p.add_argument("pasta", help="sufixo de fotos_<pasta>")
    p.add_argument("--mestres", type=int, default=1,
                   help="quantas cenas a IA repinta. Uma so nao cobre casa "
                        "grande: medido no sobrado, os cômodos que a mestra "
                        "nao enxerga saem com 98%% de buraco. Cada mestra "
                        "custa seis chamadas, cerca de US$ 0,18.")
    p.add_argument("descricao", nargs="?", default="")
    p.add_argument("--largura", type=int, default=4096)
    p.add_argument("--reaproveitar", action="store_true",
                   help="usa a mestra ja repintada em repintura/, sem gastar "
                        "chamada de API")
    p.add_argument("--ate", type=int, default=0,
                   help="limita a quantos pontos propagar (0 = todos); serve "
                        "para conferir o resultado antes de rodar a casa toda")
    a = p.parse_args()

    base = os.path.join(AQUI, "fotos_" + a.pasta)
    nomes = sorted(q for q in os.listdir(base) if q.startswith("ponto_"))
    indices = sorted(int(q[len("ponto_"):-len(".jpg")]) for q in nomes)
    if a.ate:
        indices = indices[:a.ate]
    if a.mestre not in indices:
        raise SystemExit("o ponto mestre %d nao esta na lista" % a.mestre)

    import cena_apartamento
    import plantas
    # a planta se acha pelo campo "pasta", como no repintar_cena — o nome da
    # funcao nem sempre e o nome da pasta
    planta = next((f() for f in plantas.TODAS if f()["pasta"] == a.pasta), None)
    if planta is None:
        raise SystemExit("nao achei a planta da pasta %r" % a.pasta)
    pts = planta["pontos"]

    panos, disps, origens = [], [], []
    alvo = (a.largura, a.largura // 2)
    for i in indices:
        img = ler_imagem(os.path.join(base, "ponto_%d.jpg" % i))
        d = np.load(os.path.join(base, "dist_%d.npy" % i))
        panos.append(cv2.resize(img, alvo, interpolation=cv2.INTER_AREA))
        disps.append(cv2.resize(d, alvo, interpolation=cv2.INTER_NEAREST))
        q = pts[i]
        origens.append((float(q[1]) - planta["larg"] / 2.0,
                        cena_apartamento.base_do_ponto(q) + cena_apartamento.OLHO,
                        float(q[2]) - planta["fundo"] / 2.0))

    onde = indices.index(a.mestre)
    print("%d cenas, mestra = ponto %d" % (len(indices), a.mestre))

    guardada = os.path.join(AQUI, "repintura",
                            "%s_%d_mestra.jpg" % (a.pasta, a.mestre))
    if a.reaproveitar:
        nova = ler_imagem(guardada)
        if nova is None:
            raise SystemExit("falta %s — rode sem --reaproveitar antes"
                             % guardada)
        panos[onde] = cv2.resize(nova, alvo, interpolation=cv2.INTER_CUBIC)
        print("mestra reaproveitada (sem gastar API)")
    else:
        import repintar
        import repintar_cena
        import repintor_ia
        pintor = repintor_ia.de_replicate()

        # O MODELO RECEBE O GUIA CINZA, nao a disparidade crua: o repintar()
        # entrega a profundidade da vista como ela esta guardada, e quem
        # converte e o adaptador — igual ao repintar_cena.
        def adaptado(vista, prof, texto):
            return pintor(vista, repintar_cena.guia_de_profundidade(prof),
                          texto)

        # O comodo se apresenta, como no repintar_cena: sem isso o modelo
        # escolhe sozinho o que e cada volume, e ja transformou painel de TV
        # em armario.
        comodo = (pts[a.mestre][0].split(" - ")[0] or "").lower()
        texto = (a.descricao or "interior fotografico").strip()
        if comodo:
            texto = "%s. %s" % (comodo, texto)

        print("repintando a mestra na Replicate (UMA chamada de cena)")
        # o anel, e nao a esfera: zenite e nadir saem do preenchimento
        nova, _sem_cobertura = repintar.repintar(
            panos[onde], disps[onde], texto, adaptado,
            direcoes=repintar.direcoes_do_anel())
        panos[onde] = nova
        os.makedirs(os.path.dirname(guardada), exist_ok=True)
        gravar_imagem(guardada, panos[onde])
        print("mestra guardada em %s" % guardada)

    feitos = propagar(panos, disps, origens, onde)

    saida = os.path.join(AQUI, "coerente_" + a.pasta)
    os.makedirs(saida, exist_ok=True)
    for k, i in enumerate(indices):
        gravar_imagem(os.path.join(saida, "ponto_%d.jpg" % i), feitos[k])
    print("%d cenas gravadas em %s" % (len(indices), saida))


if __name__ == "__main__":
    main()
