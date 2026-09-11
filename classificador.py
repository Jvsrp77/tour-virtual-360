# -*- coding: utf-8 -*-
"""
Identifica que comodo aparece num panorama.

Usa CLIP: o modelo aproxima imagens e textos num mesmo espaco, entao da para
perguntar "esta foto parece mais um quarto ou uma cozinha?" sem treinar nada.

Os textos sao sempre os mesmos, entao ficam pre-calculados em
modelos/clip_rotulos.npz. Em uso, so o codificador de imagem roda — o de texto
e o tokenizador servem apenas para gerar esse arquivo uma vez.

O panorama nao vai direto para o modelo: equirretangular distorce demais. Sao
recortadas quatro vistas em perspectiva ao redor do horizonte, e vence o comodo
com maior pontuacao somada.
"""
import os
import io
import json
import re

os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "disabled")

import cv2
import numpy as np

PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelos")
ARQ_VISAO = os.path.join(PASTA, "clip_visao.onnx")
ARQ_TEXTO = os.path.join(PASTA, "clip_texto.onnx")
ARQ_ROTULOS = os.path.join(PASTA, "clip_rotulos.npz")
ARQ_VOCAB = os.path.join(PASTA, "clip_vocab.json")
ARQ_MERGES = os.path.join(PASTA, "clip_merges.txt")

LADO = 224
MEDIA = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
DESVIO = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)

# Cada comodo tem varias frases: CLIP responde melhor a descricoes do que a
# palavras soltas, e a media entre elas reduce o peso de uma frase infeliz.
COMODOS = [
    ("Quarto", ["a photo of a bedroom", "a bedroom with a bed",
                "interior of a bedroom with a wardrobe"]),
    ("Sala", ["a photo of a living room", "a living room with a sofa and a tv",
              "interior of a living room"]),
    ("Cozinha", ["a photo of a kitchen", "a kitchen with a stove and cabinets",
                 "interior of a kitchen with a sink"]),
    ("Banheiro", ["a photo of a bathroom", "a bathroom with a shower and a toilet",
                  "interior of a bathroom with a sink and mirror"]),
    ("Varanda", ["a photo of a balcony", "an apartment balcony with a railing",
                 "a terrace overlooking outside"]),
    ("Área de serviço", ["a photo of a laundry room",
                         "a laundry area with a washing machine",
                         "a utility room with a laundry sink"]),
    ("Garagem", ["a photo of a garage", "a garage with a parked car",
                 "a covered parking space"]),
    ("Corredor", ["a photo of a hallway", "a narrow corridor with doors",
                  "an empty hallway inside a house"]),
    ("Escritório", ["a photo of a home office", "a desk with a computer in a room",
                    "a home office with a chair and monitor"]),
    ("Área externa", ["a photo of a backyard", "the exterior facade of a house",
                      "an outdoor garden area"]),
]

_SESSAO_VISAO = None
_ROTULOS = None


class ErroClassificador(Exception):
    pass


def disponivel():
    return os.path.exists(ARQ_VISAO) and os.path.exists(ARQ_ROTULOS)


# ------------------------------------------------------------- tokenizador
# Implementado aqui porque roda uma vez so, ao gerar os rotulos. Levar o
# tokenizer completo do transformers para producao seria peso sem uso.

def _pares(palavra):
    return set(zip(palavra[:-1], palavra[1:]))


class TokenizadorCLIP:
    def __init__(self):
        with io.open(ARQ_VOCAB, encoding="utf-8") as f:
            self.vocab = json.load(f)
        with io.open(ARQ_MERGES, encoding="utf-8") as f:
            linhas = f.read().split("\n")[1:49152 - 256 - 2 + 1]
        self.ranks = {tuple(l.split()): i for i, l in enumerate(linhas) if l}
        self.padrao = re.compile(
            r"<\|startoftext\|>|<\|endoftext\|>|'s|'t|'re|'ve|'m|'ll|'d|"
            r"[\p{L}]+|[\p{N}]|[^\s\p{L}\p{N}]+".replace("\\p{L}", "a-zA-Z")
            .replace("\\p{N}", "0-9"), re.IGNORECASE)

    def _bpe(self, token):
        palavra = tuple(token[:-1]) + (token[-1] + "</w>",)
        pares = _pares(palavra)
        while pares:
            par = min(pares, key=lambda p: self.ranks.get(p, 1e10))
            if par not in self.ranks:
                break
            primeiro, segundo = par
            nova, i = [], 0
            while i < len(palavra):
                try:
                    j = palavra.index(primeiro, i)
                except ValueError:
                    nova.extend(palavra[i:])
                    break
                nova.extend(palavra[i:j])
                if j < len(palavra) - 1 and palavra[j + 1] == segundo:
                    nova.append(primeiro + segundo)
                    i = j + 2
                else:
                    nova.append(palavra[j])
                    i = j + 1
            palavra = tuple(nova)
            if len(palavra) == 1:
                break
            pares = _pares(palavra)
        return palavra

    def codificar(self, texto, tamanho=77):
        ids = [self.vocab["<|startoftext|>"]]
        for token in self.padrao.findall(texto.lower().strip()):
            for pedaco in self._bpe(token):
                ids.append(self.vocab.get(pedaco, self.vocab["<|endoftext|>"]))
        ids.append(self.vocab["<|endoftext|>"])
        ids = ids[:tamanho]
        return ids + [0] * (tamanho - len(ids))


def gerar_rotulos():
    """Calcula e grava os vetores das frases. Roda uma vez, fora do caminho de uso."""
    import onnxruntime as ort
    if not os.path.exists(ARQ_TEXTO):
        raise ErroClassificador("Falta modelos/clip_texto.onnx para gerar os rótulos.")

    tok = TokenizadorCLIP()
    sessao = ort.InferenceSession(ARQ_TEXTO, providers=["CPUExecutionProvider"])
    entradas = {e.name for e in sessao.get_inputs()}

    nomes, vetores = [], []
    for nome, frases in COMODOS:
        ids = np.array([tok.codificar(f) for f in frases], dtype=np.int64)
        alimento = {"input_ids": ids}
        if "attention_mask" in entradas:
            alimento["attention_mask"] = (ids != 0).astype(np.int64)
        saida = sessao.run(None, alimento)[0]
        v = saida / np.linalg.norm(saida, axis=1, keepdims=True)
        v = v.mean(axis=0)
        vetores.append(v / np.linalg.norm(v))
        nomes.append(nome)

    np.savez(ARQ_ROTULOS, nomes=np.array(nomes), vetores=np.array(vetores, np.float32))
    return len(nomes)


# ------------------------------------------------------------------- uso

def _sessao_visao():
    global _SESSAO_VISAO
    if _SESSAO_VISAO is None:
        if not os.path.exists(ARQ_VISAO):
            raise ErroClassificador(
                "O modelo de reconhecimento não está instalado. "
                "Rode 'python baixar_modelo.py' uma vez.")
        import onnxruntime as ort
        _SESSAO_VISAO = ort.InferenceSession(ARQ_VISAO,
                                             providers=["CPUExecutionProvider"])
    return _SESSAO_VISAO


def _rotulos():
    global _ROTULOS
    if _ROTULOS is None:
        if not os.path.exists(ARQ_ROTULOS):
            raise ErroClassificador("Faltam os rótulos. Rode 'python baixar_modelo.py'.")
        d = np.load(ARQ_ROTULOS, allow_pickle=True)
        _ROTULOS = (list(d["nomes"]), d["vetores"])
    return _ROTULOS


def _vista(equi, yaw, fov=95.0):
    """Recorta uma janela em perspectiva: o equirretangular distorce demais."""
    He, We = equi.shape[:2]
    f = (LADO / 2.0) / np.tan(np.radians(fov) / 2.0)
    eixo = np.arange(LADO, dtype=np.float32) - LADO / 2.0
    u, v = np.meshgrid(eixo, eixo)
    d = np.stack([u, v, np.full_like(u, f)], -1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)

    y = np.radians(yaw)
    R = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    d = d @ R.T
    lon = np.arctan2(d[..., 0], d[..., 2])
    lat = np.arcsin(np.clip(d[..., 1], -1, 1))
    mx = ((lon / (2 * np.pi)) + 0.5) * We
    my = ((lat / np.pi) + 0.5) * He
    return cv2.remap(equi, mx.astype(np.float32), my.astype(np.float32),
                     cv2.INTER_AREA, borderMode=cv2.BORDER_WRAP)


def _vetor_imagem(bgr):
    x = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    x = ((x - MEDIA) / DESVIO).transpose(2, 0, 1)[None]
    saida = _sessao_visao().run(None, {"pixel_values": x})[0]
    return saida[0] / np.linalg.norm(saida[0])


def identificar(caminho_panorama, vistas=4):
    """
    Devolve [(comodo, confianca), ...] em ordem decrescente.
    A confianca vai de 0 a 1 e e comparativa entre os comodos da lista.
    """
    dados = np.fromfile(caminho_panorama, dtype=np.uint8)
    equi = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if equi is None:
        raise ErroClassificador("Não consegui abrir o panorama.")

    nomes, vetores = _rotulos()
    soma = np.zeros(len(nomes), np.float32)
    for i in range(vistas):
        v = _vetor_imagem(_vista(equi, i * (360.0 / vistas)))
        soma += vetores @ v

    # temperatura 100: o mesmo fator que o CLIP usa para transformar
    # similaridade de cosseno em probabilidade
    exp = np.exp((soma / vistas) * 100.0 - np.max(soma / vistas) * 100.0)
    prob = exp / exp.sum()
    ordem = np.argsort(-prob)
    return [(nomes[i], float(prob[i])) for i in ordem]
