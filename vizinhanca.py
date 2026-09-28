# -*- coding: utf-8 -*-
"""
O que existe em volta do imovel.

Por que existe: o anuncio parava na porta. O tour mostra o interior muito bem
— panorama, maquete, caminhada, medidas, sol — e nao dizia uma palavra sobre o
bairro, que e metade da decisao de quem compra. Quem se interessava tinha de
abrir o Maps por fora, e nessa hora saia do nosso link.

O que este modulo NAO e: nao ha imagem de rua nem passeio pelo bairro. Isso
exige dados de nivel de rua da cidade inteira, que e um negocio de dados e nao
de codigo. Aqui o que se entrega e mais modesto e verdadeiro: a que distancia
estao o mercado, a farmacia, a escola e o ponto de onibus mais proximos.

Duas decisoes que moldam o resto:

1. A rede e chamada UMA vez, quando o corretor grava o endereco, e o resultado
   fica guardado no imovel. A pagina de quem visita nunca fala com servico de
   terceiro — foi a licao do three.js que vinha do cdnjs: a hora em que um
   servico de fora cai e sempre a pior hora possivel.

2. A distancia e em LINHA RETA, e a interface diz isso com todas as letras.
   Distancia de caminhada exigiria um servico de rotas; anunciar "300 m" que na
   verdade sao 700 m de volta no quarteirao seria a mentira que o cliente
   descobre a pe, no dia da visita.

Os dados sao do OpenStreetMap (ODbL). A cobertura e boa em capital e irregular
em cidade pequena — por isso "nao achei nada" e uma resposta prevista, e nao um
erro.
"""
import json
import math
import time
import urllib.parse
import urllib.request

# Um raio que se caminha: 900 m da uns 11 minutos a pe. Alem disso "perto" vira
# conversa de corretor, e a lista encheria de coisa que nao ajuda a decidir.
RAIO = 900

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"

# O User-Agent nao e enfeite: sem ele o Nominatim e o Overpass recusam a
# chamada, e o Overpass responde 406 sem explicar por que.
AGENTE = "TourVirtual/1.0 (maquete e tour 360 de imoveis)"

ESPERA = 30

# A ordem importa: e a ordem em que aparece no anuncio. Mercado e farmacia
# primeiro porque sao o que se usa toda semana; banco por ultimo porque quase
# ninguem escolhe imovel por causa de banco.
CATEGORIAS = [
    ("mercado", "Mercado", {"shop": ("supermarket", "convenience", "greengrocer")}),
    ("padaria", "Padaria", {"shop": ("bakery",)}),
    ("farmacia", "Farmácia", {"amenity": ("pharmacy",)}),
    ("escola", "Escola", {"amenity": ("school",)}),
    ("creche", "Creche", {"amenity": ("kindergarten",)}),
    ("saude", "Posto de saúde", {"amenity": ("hospital", "clinic", "doctors")}),
    ("onibus", "Ponto de ônibus", {"highway": ("bus_stop",)}),
    ("trilhos", "Estação", {"railway": ("station", "subway_entrance", "tram_stop")}),
    ("praca", "Praça", {"leisure": ("park", "playground", "garden")}),
    ("academia", "Academia", {"leisure": ("fitness_centre",)}),
    ("banco", "Banco", {"amenity": ("bank",)}),
]


class ErroVizinhanca(Exception):
    pass


def _haversine(lat1, lon1, lat2, lon2):
    """Distancia em metros entre dois pontos, sobre a esfera."""
    raio_terra = 6371000.0
    f1, f2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(f1) * math.cos(f2) * math.sin(dlon / 2) ** 2)
    return 2 * raio_terra * math.asin(min(1.0, math.sqrt(a)))


def categoria(tags):
    """
    Em que categoria cai um ponto do OpenStreetMap, se cair em alguma.

    Devolve (chave, rotulo) ou None. A primeira categoria que casa ganha: um
    lugar marcado ao mesmo tempo como mercado e padaria e mercado, porque e
    assim que quem mora no bairro o chama.
    """
    for chave, rotulo, regras in CATEGORIAS:
        for campo, valores in regras.items():
            if tags.get(campo) in valores:
                return chave, rotulo
    return None


def consulta(lat, lon, raio=RAIO):
    """
    Monta a pergunta ao Overpass.

    `nwr` e nao `node`: mercado e escola quase sempre estao mapeados como area,
    nao como ponto, e perguntar so por node deixaria de fora justamente os
    lugares grandes. `out center` devolve o centro da area.
    """
    partes = []
    for _chave, _rotulo, regras in CATEGORIAS:
        for campo, valores in regras.items():
            partes.append('nwr(around:%d,%.6f,%.6f)["%s"~"^(%s)$"];'
                          % (raio, lat, lon, campo, "|".join(valores)))
    return "[out:json][timeout:25];(%s);out center tags;" % "".join(partes)


def _ponto(elemento):
    """A coordenada de um elemento, seja ele ponto ou area."""
    if "lat" in elemento and "lon" in elemento:
        return elemento["lat"], elemento["lon"]
    centro = elemento.get("center") or {}
    if "lat" in centro and "lon" in centro:
        return centro["lat"], centro["lon"]
    return None


def escolher(elementos, lat, lon, raio=RAIO):
    """
    O mais proximo de cada categoria, em ordem de distancia.

    Um por categoria de proposito: a lista serve para decidir, e saber que ha
    catorze padarias no raio nao ajuda ninguem a decidir nada. O que ajuda e
    saber que a mais perto esta a 120 m.
    """
    melhores = {}
    for elemento in elementos or []:
        achado = categoria(elemento.get("tags") or {})
        if not achado:
            continue
        coord = _ponto(elemento)
        if not coord:
            continue
        metros = _haversine(lat, lon, coord[0], coord[1])
        if metros > raio:
            continue
        chave, rotulo = achado
        atual = melhores.get(chave)
        if atual is None or metros < atual["metros"]:
            melhores[chave] = {
                "chave": chave,
                "tipo": rotulo,
                "nome": (elemento.get("tags") or {}).get("name", ""),
                "metros": int(round(metros)),
            }
    return sorted(melhores.values(), key=lambda p: p["metros"])


def _pedir(url, dados=None):
    pedido = urllib.request.Request(
        url, data=dados, headers={"User-Agent": AGENTE,
                                  "Accept": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=ESPERA) as resposta:
            return json.loads(resposta.read().decode("utf-8", "replace"))
    except Exception as erro:
        raise ErroVizinhanca(
            "Não consegui falar com o OpenStreetMap agora (%s). A vizinhança "
            "pode ser buscada depois; o resto do imóvel não depende dela."
            % type(erro).__name__)


def geocodificar(endereco):
    """Endereco escrito vira coordenada."""
    endereco = (endereco or "").strip()
    if not endereco:
        raise ErroVizinhanca(
            "Este imóvel ainda não tem endereço. Preencha o endereço em Dados "
            "do imóvel e busque de novo.")
    url = NOMINATIM + "?" + urllib.parse.urlencode(
        {"q": endereco, "format": "json", "limit": 1, "addressdetails": 0})
    achados = _pedir(url)
    if not achados:
        raise ErroVizinhanca(
            "O OpenStreetMap não encontrou este endereço. Costuma resolver "
            "escrever rua, número, bairro, cidade e estado — por exemplo "
            "\"Rua das Flores, 120, Centro, Campinas, SP\".")
    primeiro = achados[0]
    return {"lat": float(primeiro["lat"]), "lon": float(primeiro["lon"]),
            "achado_como": primeiro.get("display_name", "")}


def redor(lat, lon, raio=RAIO):
    """O que o OpenStreetMap conhece em volta do ponto."""
    dados = urllib.parse.urlencode({"data": consulta(lat, lon, raio)})
    resposta = _pedir(OVERPASS, dados.encode("utf-8"))
    return resposta.get("elements", [])


def buscar(endereco, raio=RAIO):
    """
    O registro inteiro, pronto para ser gravado no imovel.

    Guarda junto o endereco que foi geocodificado: e o que permite descobrir
    depois que o corretor trocou o endereco e a vizinhanca guardada e de outro
    lugar.
    """
    lugar = geocodificar(endereco)
    lugares = escolher(redor(lugar["lat"], lugar["lon"], raio),
                       lugar["lat"], lugar["lon"], raio)
    return {
        "endereco": (endereco or "").strip(),
        "lat": round(lugar["lat"], 6),
        "lon": round(lugar["lon"], 6),
        "achado_como": lugar["achado_como"],
        "raio": raio,
        "lugares": lugares,
        "buscado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "fonte": "OpenStreetMap (ODbL)",
    }


def esta_velha(tour):
    """
    A vizinhanca guardada e de outro endereco?

    O corretor corrige o endereco depois de ter buscado a vizinhanca, e o
    anuncio passaria a mostrar o mercado do endereco ANTIGO sem avisar ninguem.
    """
    guardada = tour.get("vizinhanca")
    if not guardada:
        return False
    return (guardada.get("endereco") or "").strip() != (
        tour.get("endereco") or "").strip()
