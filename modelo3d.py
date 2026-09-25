# -*- coding: utf-8 -*-
"""
Modelo 3D vindo de fora: o OBJ que sai de um escaneamento de celular.

Por que existe: a maquete so funcionava em imovel GERADO, porque ela precisa de
geometria e foto nao tem geometria. Um aplicativo de escaneamento (Polycam,
Scaniverse e afins) transforma fotos ou video num OBJ com paredes e moveis
medidos — e com ele a maquete passa a valer para imovel de verdade.

O que este modulo faz: conferir o arquivo ANTES de aceitar, e medir o que veio.
Nao converte nem simplifica; o navegador desenha o OBJ como ele chegou.

A conferencia nao e burocracia. OBJ e texto, qualquer arquivo pode se chamar
.obj, e um modelo que so se descobre quebrado na hora de abrir deixa o corretor
sem entender o que houve.
"""
import os
import re

LIMITE_BYTES = 80 * 1024 * 1024        # 80 MB: escaneamento de celular cabe folgado
LIMITE_VERTICES = 2_000_000            # acima disso o navegador do celular trava

# Um escaneamento sai em metros na esmagadora maioria dos aplicativos, mas nao
# ha garantia no formato. Estes limites nao recusam nada — servem para AVISAR
# quando o numero destoa de um imovel, que e quando a escala costuma estar em
# centimetros ou em polegadas.
COMODO_MINIMO = 1.5
IMOVEL_MAXIMO = 120.0


class ErroModelo(Exception):
    pass


def _numeros(linha):
    return [float(p) for p in linha.split()[1:4]]


def medir(texto):
    """
    Le o OBJ e devolve o que ele tem dentro.

    Devolve dict com vertices, faces, materiais, a caixa envolvente e o
    tamanho em metros. E de propositio uma leitura barata: so as linhas que
    comecam com v e f, sem montar malha nenhuma.
    """
    vx = vy = vz = None
    maiores = None
    vertices = faces = 0
    materiais = set()
    tem_mtl = False

    for linha in texto.splitlines():
        if linha.startswith("v "):
            try:
                x, y, z = _numeros(linha)
            except (ValueError, IndexError):
                continue
            vertices += 1
            if vx is None:
                vx, vy, vz = [x, x], [y, y], [z, z]
            else:
                vx[0] = min(vx[0], x); vx[1] = max(vx[1], x)
                vy[0] = min(vy[0], y); vy[1] = max(vy[1], y)
                vz[0] = min(vz[0], z); vz[1] = max(vz[1], z)
        elif linha.startswith("f "):
            faces += 1
        elif linha.startswith("usemtl "):
            materiais.add(linha.split(None, 1)[1].strip())
        elif linha.startswith("mtllib "):
            tem_mtl = True

    if not vertices or not faces:
        raise ErroModelo("O arquivo não tem geometria: nenhum vértice ou face. "
                         "Confira se exportou mesmo em OBJ.")

    largura = vx[1] - vx[0]
    altura = vy[1] - vy[0]
    fundo = vz[1] - vz[0]
    return {"vertices": vertices, "faces": faces,
            "materiais": sorted(materiais), "tem_mtl": tem_mtl,
            "largura": round(largura, 2), "altura": round(altura, 2),
            "fundo": round(fundo, 2),
            "centro": [round((vx[0] + vx[1]) / 2, 3),
                       round(vy[0], 3),                 # o chao, nao o meio
                       round((vz[0] + vz[1]) / 2, 3)]}


def conferir(texto, tamanho_bytes):
    """
    Devolve (medidas, avisos) ou levanta ErroModelo.

    Aviso nao impede de usar: escaneamento tem mesmo geometria estranha, e
    recusar por isso seria decidir pelo corretor. Erro impede, e so para o que
    o navegador nao conseguiria desenhar.
    """
    if tamanho_bytes > LIMITE_BYTES:
        raise ErroModelo(
            "O arquivo tem %.0f MB e o limite é %d MB. No aplicativo de "
            "escaneamento, exporte em qualidade média — o celular de quem vai "
            "ver também precisa dar conta."
            % (tamanho_bytes / 1048576.0, LIMITE_BYTES // 1048576))

    medidas = medir(texto)
    if medidas["vertices"] > LIMITE_VERTICES:
        raise ErroModelo(
            "O modelo tem %d vértices, acima do limite de %d. Exporte com menos "
            "detalhe: acima disso o navegador do celular trava."
            % (medidas["vertices"], LIMITE_VERTICES))

    avisos = []
    maior = max(medidas["largura"], medidas["fundo"])
    if maior < COMODO_MINIMO:
        avisos.append(
            "O modelo mede %.2f m no lado maior. Parece pequeno demais para um "
            "ambiente — provavelmente foi exportado em outra unidade." % maior)
    elif maior > IMOVEL_MAXIMO:
        avisos.append(
            "O modelo mede %.0f m no lado maior. Parece grande demais para um "
            "imóvel — provavelmente foi exportado em centímetros." % maior)
    if medidas["altura"] < 1.2:
        avisos.append(
            "A altura do modelo é de %.2f m. Um ambiente de pé-direito normal "
            "tem perto de 2,70 m; confira a orientação dos eixos."
            % medidas["altura"])
    if medidas["tem_mtl"] and not medidas["materiais"]:
        avisos.append("O arquivo cita um .mtl mas não usa material nenhum.")
    return medidas, avisos


def nome_do_mtl(texto):
    """O .mtl que o OBJ pede, se pedir algum."""
    achado = re.search(r"^mtllib\s+(.+)$", texto, re.M)
    return achado.group(1).strip() if achado else None
