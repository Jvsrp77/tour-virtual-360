# -*- coding: utf-8 -*-
"""
Exporta a geometria do imovel para OBJ + MTL.

Por que OBJ e nao glTF: OBJ abre no SketchUp, no Blender, no AutoCAD e em
qualquer visualizador 3D sem plugin nenhum, e e texto — da para conferir a olho
quando algo sai errado. A geometria daqui e caixa alinhada ao eixo com cor
chapada, que e exatamente o que o OBJ representa bem. glTF valeria a pena se
houvesse textura, animacao ou material com reflexo, e nao ha.

Convencao: Y para cima, medidas em METROS, origem no canto do imovel — a mesma
da planta, para a maquete e a planta baixa falarem a mesma lingua.
"""
import io
import os
import re
import zipfile

CANTOS = (
    # (indice do vertice) na ordem x0y0z0, x1y0z0, x1y1z0, x0y1z0,
    #                              x0y0z1, x1y0z1, x1y1z1, x0y1z1
    (0, 1, 2), (3, 1, 2), (3, 4, 2), (0, 4, 2),
    (0, 1, 5), (3, 1, 5), (3, 4, 5), (0, 4, 5),
)

# cada face: os quatro cantos, e a normal que aponta para FORA da caixa
FACES = (
    ((0, 3, 2, 1), (0.0, 0.0, -1.0)),      # z menor
    ((4, 5, 6, 7), (0.0, 0.0, 1.0)),       # z maior
    ((0, 4, 7, 3), (-1.0, 0.0, 0.0)),      # x menor
    ((1, 2, 6, 5), (1.0, 0.0, 0.0)),       # x maior
    ((0, 1, 5, 4), (0.0, -1.0, 0.0)),      # base
    ((3, 7, 6, 2), (0.0, 1.0, 0.0)),       # topo
)

ESPESSURA_CASCA = 0.14


def _nome_seguro(texto):
    """Nome de objeto que o OBJ aceita: sem espaco e sem acento."""
    troca = {"á": "a", "ã": "a", "â": "a", "à": "a", "é": "e", "ê": "e",
             "í": "i", "ó": "o", "ô": "o", "õ": "o", "ú": "u", "ç": "c"}
    limpo = "".join(troca.get(c, troca.get(c.lower(), c)) for c in texto)
    limpo = re.sub(r"[^A-Za-z0-9_.-]+", "_", limpo).strip("_")
    return limpo or "objeto"


def _rgb(cor_hex):
    c = (cor_hex or "#808080").lstrip("#")
    if len(c) != 6:
        c = "808080"
    return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _caixas_da_casca(geo):
    """
    As quatro paredes externas.

    Elas nao estao na lista de caixas porque no tracador de raios sao a CASCA
    do imovel — o raio bate nelas por fora, nao por colisao com um solido. No
    OBJ precisam existir de verdade, senao o modelo abre sem fachada.
    """
    L, F, PE, E = geo["larg"], geo["fundo"], geo["pe"], ESPESSURA_CASCA
    return [
        ([0.0, 0.0, 0.0, L, PE, E], "parede", "#b0aea8", "casca_frente"),
        ([0.0, 0.0, F - E, L, PE, F], "parede", "#b0aea8", "casca_fundo"),
        ([0.0, 0.0, 0.0, E, PE, F], "parede", "#b0aea8", "casca_esquerda"),
        ([L - E, 0.0, 0.0, L, PE, F], "parede", "#b0aea8", "casca_direita"),
    ]


def _pisos(geo):
    """Uma laje fina por comodo, com a cor do revestimento."""
    saida = []
    for z in geo.get("zonas", []):
        saida.append(([z["x0"], -0.06, z["z0"], z["x1"], 0.0, z["z1"]],
                      "piso_" + _nome_seguro(z["nome"]), z.get("piso", "#808080"),
                      "piso_" + _nome_seguro(z["nome"])))
    return saida


def para_obj(geo, base="maquete"):
    """Devolve (texto do .obj, texto do .mtl)."""
    pecas = []
    for c in geo.get("caixas", []):
        pecas.append((c["p"], c["m"], c.get("cor", "#808080"), c["m"]))
    pecas += _caixas_da_casca(geo)
    pecas += _pisos(geo)

    materiais = {}
    for _, mat, cor, _ in pecas:
        materiais.setdefault(_nome_seguro(mat), cor)

    obj = ["# Tour Virtual — maquete de %s" % geo.get("titulo", base),
           "# metros, Y para cima, origem no canto do imovel",
           "mtllib %s.mtl" % base]
    vertices, normais = [], []
    # as seis normais sao sempre as mesmas: uma por face da caixa
    for _, n in FACES:
        normais.append(n)
    for n in normais:
        obj.append("vn %.4f %.4f %.4f" % n)

    atual = None
    for p, mat, _, nome in pecas:
        x0, y0, z0, x1, y1, z1 = p
        base_v = len(vertices)
        for ex, ey, ez in ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                           (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)):
            vertices.append((ex, ey, ez))
        grupo = _nome_seguro(nome)
        if grupo != atual:
            obj.append("o %s" % grupo)
            atual = grupo
        obj.append("usemtl %s" % _nome_seguro(mat))
        for k, (cantos, _) in enumerate(FACES):
            obj.append("f " + " ".join(
                "%d//%d" % (base_v + c + 1, k + 1) for c in cantos))

    # os vertices vem antes das faces no arquivo
    corpo = ["v %.4f %.4f %.4f" % v for v in vertices]
    cabeca = obj[:3 + len(normais)]
    resto = obj[3 + len(normais):]
    texto_obj = "\n".join(cabeca + corpo + resto) + "\n"

    mtl = ["# materiais da maquete"]
    for nome, cor in sorted(materiais.items()):
        r, g, b = _rgb(cor)
        mtl += ["newmtl %s" % nome,
                "Kd %.4f %.4f %.4f" % (r, g, b),
                "Ka %.4f %.4f %.4f" % (r * 0.3, g * 0.3, b * 0.3),
                "Ks 0.0000 0.0000 0.0000",
                "d 1.0", "illum 1", ""]
    return texto_obj, "\n".join(mtl)


def zipar(geo, titulo=""):
    """
    Empacota .obj e .mtl juntos.

    Tem de ser os dois: o OBJ so guarda a geometria, e sem o MTL ao lado o
    modelo abre todo cinza. Separar os dois arquivos e do formato, nao escolha.
    """
    limpo = _nome_seguro(titulo or geo.get("titulo") or "maquete").lower()[:40]
    memoria = io.BytesIO()
    obj, mtl = para_obj(geo, limpo)
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(limpo + ".obj", obj)
        z.writestr(limpo + ".mtl", mtl)
        z.writestr("LEIA-ME.txt", _leiame(geo, limpo))
    memoria.seek(0)
    return memoria, limpo + ".zip"


def _leiame(geo, base):
    area = sum(z.get("m2", 0) for z in geo.get("zonas", []))
    return (
        "Maquete de %s\n\n"
        "%s.obj  — a geometria\n"
        "%s.mtl  — as cores (abra o .obj; o .mtl e lido junto, deixe os dois "
        "na mesma pasta)\n\n"
        "Medidas em METROS, eixo Y para cima, origem no canto do imovel.\n"
        "%.1f m2 em %d comodo(s), pe-direito %.2f m.\n\n"
        "Abre no SketchUp, Blender, AutoCAD e em qualquer visualizador 3D.\n"
        "No Blender: Arquivo > Importar > Wavefront (.obj).\n\n"
        "E um modelo GERADO, nao levantamento de imovel real.\n"
        % (geo.get("titulo", base), base, base, area,
           len(geo.get("zonas", [])), geo.get("pe", 2.7)))
