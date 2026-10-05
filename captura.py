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

# TODAS ESTAS ESPELHAM O andar.html, e ha teste que confere uma a uma. Se o
# visor mudar e o guia nao, o guia passa a mandar o corretor capturar errado —
# e com toda a autoridade de um numero na tela.
PASSEIO_CHEIO = 2.50
PASSEIO_MINIMO = 0.35
PASSEIO_SEM_FUNDO = 1.00
ESCORRIDO_OTIMO = 0.010
RECONSTRUIDO_OTIMO = 2.0

# Fracao do alcance somado dos dois pontos a partir da qual o meio do caminho
# comeca a esticar, mesmo sem buraco. Folga, nao regra de gosto.
FOLGA_BOA = 0.70

# Mantidos porque a tela os consome, mas agora sao CALCULADOS por imovel, a
# partir do alcance real das cenas dele — nao mais constantes. Vide resumo().
VAO_MAXIMO = PASSEIO_CHEIO * 2
VAO_IDEAL = VAO_MAXIMO * FOLGA_BOA


def passeio_da_cena(cena, preparada=False):
    """
    Quanto se pode andar a partir desta cena, em metros.

    ESPELHA tetoDePasseio() do andar.html, e o motivo de existir aqui e um
    defeito que durou um dia: o guia dizia que dois pontos a 2,50 m estavam
    bons, porque 2,50 era o alcance do passeio. Quando o alcance passou a
    depender da OCLUSAO — quanto da cena a IA teve de inventar — a media caiu
    para 0,90 m, e o guia continuou aprovando vaos que a caminhada nao cobre.

    Dois pontos a 2,50 m deixam o meio do caminho a 1,25 m de cada um. Com
    alcance de 0,90 m, ninguem chega la: a caminhada para no vazio.
    """
    teto = PASSEIO_CHEIO
    escorrido = (cena.get("escorrido") or {}).get("fracao")
    if escorrido and escorrido > ESCORRIDO_OTIMO:
        teto = PASSEIO_CHEIO * (ESCORRIDO_OTIMO / escorrido)

    reconstruido = (cena.get("fundo") or {}).get("reconstruido")
    if reconstruido and reconstruido > 0:
        if reconstruido > RECONSTRUIDO_OTIMO:
            teto = min(teto, PASSEIO_CHEIO * (RECONSTRUIDO_OTIMO / reconstruido))
    elif not preparada:
        # sem camada de fundo o vao nao tem conteudo nenhum: vira preto
        teto = min(teto, PASSEIO_SEM_FUNDO)
    return max(PASSEIO_MINIMO, teto)


def alcance_do_par(a, b):
    """
    Ate que vao a caminhada cobre entre estes dois pontos.

    O pior lugar do passeio e o MEIO do caminho, e ele precisa estar ao alcance
    dos dois — entao o vao coberto e o dobro do MENOR dos dois alcances. Usar a
    soma aprovaria um par em que so um dos lados chega la.

    `preparada=True` de proposito: aqui a pergunta e sobre a CAPTURA, e faltar
    camada de fundo nao se resolve voltando ao imovel — resolve-se com um botao
    no painel. Quem avisa disso e um achado proprio.
    """
    return 2.0 * min(passeio_da_cena(a, preparada=True),
                     passeio_da_cena(b, preparada=True))


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
        outras = [(_distancia(aqui, la), outra)
                  for outra, la in postas if outra is not cena]
        if not outras:
            saida.append((cena, None, None))
            continue
        metros, vizinha = min(outras, key=lambda par: par[0])
        saida.append((cena, metros, vizinha))
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
    distancias = [d for _c, d, _v in medidos if d is not None]
    alcances = [alcance_do_par(c, v) for c, d, v in medidos if d is not None]
    sem_camada = len([c for c in cenas
                      if c.get("profundidade")
                      and not (c.get("fundo") or {}).get("textura")])

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

    sem_fundo = [c for c in cenas
                 if c.get("profundidade") and not (c.get("fundo") or {}).get("textura")]
    for cena in sem_fundo:
        achados.append({
            "grau": "atrapalha", "cena": cena.get("nome", ""),
            "o_que": "Sem a camada de fundo: ao andar, o que está atrás dos "
                     "móveis aparece como buraco preto.",
            "fazer": "No painel, use Preparar — não precisa voltar ao imóvel."})

    for cena in sem_posicao:
        achados.append({
            "grau": "impede", "cena": cena.get("nome", ""),
            "o_que": "Sem posição no croqui: o sistema não sabe onde este ponto fica.",
            "fazer": "Arraste este ponto para o lugar certo no croqui do painel."})

    for cena, metros, vizinha in medidos:
        if metros is None:
            achados.append({
                "grau": "atrapalha", "cena": cena.get("nome", ""),
                "o_que": "É o único ponto posicionado do imóvel.",
                "fazer": "Capture ao menos mais um ponto, a uns 2 metros deste."})
            continue
        # o alcance e DESTE par, nao um numero fixo: comodo cheio de movel anda
        # menos, corredor vazio anda mais
        cobre = alcance_do_par(cena, vizinha)
        # ATRAPALHA, e nao impede. A seta leva o visitante ao ponto vizinho de
        # qualquer distancia — quem nao atravessa o vao e o passeio LIVRE, que
        # nasce desligado. Chamar isto de "impede" encheria o guia de alarme
        # falso: so na casa de 520 m2 foram 51 cenas marcadas assim.
        if metros > cobre:
            achados.append({
                "grau": "atrapalha", "cena": cena.get("nome", ""),
                "o_que": "O ponto mais próximo está a %.1f m, e juntos os dois "
                         "só alcançam %.1f m. Dá para pular de um ao outro pela "
                         "seta, mas não dá para andar entre eles."
                         % (metros, cobre),
                "fazer": "Capture um ponto no meio do caminho."})
        elif metros > cobre * FOLGA_BOA:
            achados.append({
                "grau": "atrapalha", "cena": cena.get("nome", ""),
                "o_que": "O ponto mais próximo está a %.1f m, perto do limite de "
                         "%.1f m: dá para andar, mas a imagem estica no meio do "
                         "caminho." % (metros, cobre),
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
        # calculados a partir do alcance real das cenas DESTE imovel
        "vao_maximo": round(sorted(alcances)[len(alcances) // 2], 2)
                      if alcances else VAO_MAXIMO,
        "vao_ideal": round(sorted(alcances)[len(alcances) // 2] * FOLGA_BOA, 2)
                     if alcances else VAO_IDEAL,
        "sem_camada": sem_camada,
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
