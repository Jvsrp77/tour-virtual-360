# -*- coding: utf-8 -*-
"""
Diagnostico da captura: o que ja foi fotografado e o que ainda falta.

POR QUE EXISTE. Todo caminho deste projeto desembocou no mesmo lugar: quem
decide a qualidade do passeio e a CAPTURA, nao o codigo. Medimos isso quatro
vezes por caminhos diferentes — o escorrido, a mistura entre pontos, a viagem
de camera, a maquete. E, no entanto, o corretor capturava no escuro: so descobria
que ficou ruim quando o tour ja estava pronto, e ai ninguem volta ao imovel.

O guia que ja existia ensina a fotografar UM panorama — ficar parado e girar.
Este responde a outra pergunta, que ninguem respondia: quantos pontos, onde, e o
que ainda falta NESTE imovel.

O QUE ELE NAO FAZ. Nao sabe onde o corretor esta. Celular nao tem posicao dentro
de casa, e fingir que tem ("ande 2 metros para a direita") seria inventar. Tudo
que ele diz sai do que ja foi enviado e gravado — posicao no croqui, escorrido
medido, profundidade gerada.
"""

# O passeio de cada ponto tem raio maximo de 2,50 m (PASSEIO_CHEIO, no
# andar.html). Entao dois pontos vizinhos a mais de 2,50 m deixam, entre eles,
# um trecho que ponto nenhum alcanca: a caminhada simplesmente para ali.
VAO_MAXIMO = 2.50

# Abaixo disto a pessoa esta sempre a menos de 90 cm do ponto mais proximo, que
# e a faixa em que a imagem ainda se sustenta. Nao e regra de gosto: e o mesmo
# numero, dividido por dois, com folga.
VAO_IDEAL = 1.80

# Fracao de escorrido a partir da qual o proprio passeio ja foi encurtado pelo
# sistema (espelha ESCORRIDO_OTIMO do andar.html).
ESCORRIDO_OTIMO = 0.010


def comodo_da_cena(nome):
    """
    "Cozinha - junto à mesa" -> "Cozinha".

    O corretor ja nomeia assim por conta propria, porque e como se fala. Quem
    nao usar o traco fica com a cena inteira como nome do comodo, o que continua
    valendo: dois pontos com o mesmo nome sao o mesmo ambiente.
    """
    nome = (nome or "").strip()
    for separador in (" - ", " – ", " — "):
        if separador in nome:
            return nome.split(separador)[0].strip()
    return nome


def _posicao(cena):
    p = cena.get("posicao")
    if not isinstance(p, dict):
        return None
    try:
        return float(p["x"]), float(p["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _distancia(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def vaos(cenas):
    """
    Para cada cena posicionada, a distancia ate a cena posicionada mais proxima.

    Devolve lista de (cena, metros) ou (cena, None) quando nao ha com quem
    comparar. E o numero que decide a caminhada: o pior lugar do passeio e
    sempre o meio do caminho entre dois pontos.
    """
    postas = [(c, _posicao(c)) for c in cenas]
    postas = [(c, p) for c, p in postas if p]
    saida = []
    for cena, aqui in postas:
        outras = [_distancia(aqui, la) for outra, la in postas if outra is not cena]
        saida.append((cena, min(outras) if outras else None))
    return saida


def por_comodo(cenas):
    """Quantos pontos cada ambiente tem, na ordem em que aparecem."""
    grupos = {}
    ordem = []
    for cena in cenas:
        nome = comodo_da_cena(cena.get("nome", ""))
        if nome not in grupos:
            grupos[nome] = []
            ordem.append(nome)
        grupos[nome].append(cena)
    return [(nome, grupos[nome]) for nome in ordem]


def diagnosticar(tour):
    """
    Devolve (resumo, achados).

    Cada achado tem grau ("impede", "atrapalha", "ok"), o que houve e O QUE
    FAZER. Achado sem o que fazer e so um muro: o corretor esta no imovel, de
    celular na mao, e precisa saber se sai dali ou nao.
    """
    cenas = tour.get("cenas", []) or []
    achados = []

    sem_profundidade = [c for c in cenas if not c.get("profundidade")]
    sem_posicao = [c for c in cenas if _posicao(c) is None]
    medidos = vaos(cenas)
    distancias = [d for _c, d in medidos if d is not None]

    if not cenas:
        achados.append({
            "grau": "impede", "cena": None,
            "o_que": "Este imóvel ainda não tem nenhum ambiente.",
            "fazer": "Comece pela sala: fique parado no meio dela e gire, "
                     "seguindo o guia de fotografia."})

    for cena in sem_profundidade:
        achados.append({
            "grau": "impede", "cena": cena.get("nome", ""),
            "o_que": "Sem profundidade: dá para olhar em volta, não dá para andar.",
            "fazer": "No painel, gere a profundidade desta cena."})

    for cena in sem_posicao:
        achados.append({
            "grau": "impede", "cena": cena.get("nome", ""),
            "o_que": "Sem posição no croqui: o sistema não sabe onde este ponto fica.",
            "fazer": "Arraste este ponto para o lugar certo no croqui do painel."})

    for cena, metros in medidos:
        if metros is None:
            achados.append({
                "grau": "atrapalha", "cena": cena.get("nome", ""),
                "o_que": "É o único ponto posicionado do imóvel.",
                "fazer": "Capture ao menos mais um ponto, a uns 2 metros deste."})
        elif metros > VAO_MAXIMO:
            achados.append({
                "grau": "impede", "cena": cena.get("nome", ""),
                "o_que": "O ponto mais próximo está a %.1f m. O passeio alcança "
                         "no máximo %.1f m, então há um trecho no meio que ponto "
                         "nenhum cobre." % (metros, VAO_MAXIMO),
                "fazer": "Capture um ponto no meio do caminho."})
        elif metros > VAO_IDEAL:
            achados.append({
                "grau": "atrapalha", "cena": cena.get("nome", ""),
                "o_que": "O ponto mais próximo está a %.1f m: dá para andar, mas "
                         "a imagem estica no meio do caminho." % metros,
                "fazer": "Se der, capture um ponto entre os dois."})

    for nome, do_comodo in por_comodo(cenas):
        if len(do_comodo) == 1 and nome:
            achados.append({
                "grau": "atrapalha", "cena": do_comodo[0].get("nome", ""),
                "o_que": "%s tem um ponto só: de lá não dá para caminhar pelo "
                         "ambiente." % nome,
                "fazer": "Capture um segundo ponto em %s, do outro lado do "
                         "ambiente." % nome})

    escorridas = [c for c in cenas
                  if (c.get("escorrido") or {}).get("fracao", 0) > ESCORRIDO_OTIMO * 3]
    for cena in escorridas:
        achados.append({
            "grau": "atrapalha", "cena": cena.get("nome", ""),
            "o_que": "Muita coisa nesta cena ficou escondida atrás de móveis, "
                     "então o sistema já encurtou o passeio aqui.",
            "fazer": "Capture outro ponto neste ambiente, de um lugar que veja "
                     "o que este não viu."})

    resumo = {
        "ambientes": len([n for n, _ in por_comodo(cenas) if n]),
        "pontos": len(cenas),
        "posicionados": len(cenas) - len(sem_posicao),
        "vao_mediano": round(sorted(distancias)[len(distancias) // 2], 2)
                       if distancias else None,
        "vao_maior": round(max(distancias), 2) if distancias else None,
        "vao_ideal": VAO_IDEAL,
        "vao_maximo": VAO_MAXIMO,
        "impedem": len([a for a in achados if a["grau"] == "impede"]),
        "atrapalham": len([a for a in achados if a["grau"] == "atrapalha"]),
    }
    return resumo, achados


def proximo_passo(resumo, achados):
    """
    A UMA coisa a fazer agora.

    Lista de dez problemas no celular, em pe no corredor, nao vira acao nenhuma.
    O que vira e uma frase.
    """
    impede = [a for a in achados if a["grau"] == "impede"]
    if impede:
        return impede[0]["fazer"]
    atrapalha = [a for a in achados if a["grau"] == "atrapalha"]
    if atrapalha:
        return atrapalha[0]["fazer"]
    if not resumo["pontos"]:
        return "Comece pela sala."
    return "A captura deste imóvel está boa. Pode publicar."
