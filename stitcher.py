# -*- coding: utf-8 -*-
"""
Costura de fotos em panorama 360 (equirretangular).

Recebe varias fotos tiradas girando no proprio eixo e devolve uma unica
imagem panoramica em projecao esferica, pronta para o visualizador 360.
"""
import os

# A aceleracao por GPU (OpenCL) estoura a memoria de video ao projetar a esfera e o
# erro que ela levanta e irrecuperavel: chama o terminate handler e derruba o processo
# inteiro, sem excecao para capturar. Na CPU a costura e mais lenta, porem estavel.
#
# Precisa ser desligado por variavel de ambiente, ANTES de importar o cv2:
# cv2.ocl.setUseOpenCL(False) vale so para a thread que chamou, e o Flask atende
# cada requisicao numa thread nova, que voltaria a usar a GPU.
os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "disabled")
os.environ.setdefault("OPENCV_OPENCL_DEVICE", "disabled")

import uuid
import cv2
import numpy as np

import nivelamento

cv2.ocl.setUseOpenCL(False)   # reforco para a thread de importacao

LARGURA_MAX_SAIDA = 8000     # teto de seguranca da imagem final
MINIMO_RECOMENDADO = 6       # abaixo disso a chance de sucesso cai muito


def _largura_trabalho(quantidade):
    """
    Reduz a resolucao de trabalho conforme o numero de fotos cresce.
    O custo da costura sobe com o total de pixels, entao sem isso um lote
    grande leva minutos e consome memoria demais.
    """
    if quantidade >= 30:      # captura em 3 fileiras
        return 1000
    if quantidade >= 20:      # 2 fileiras
        return 1200
    if quantidade >= 14:
        return 1400
    return 1600


def _geometria(cameras, largura_foto):
    """
    Le a orientacao que o OpenCV calculou para cada foto e devolve a cobertura real
    da captura. E o unico jeito confiavel de saber se a volta fechou: a proporcao da
    imagem nao serve, porque fotografar em fileiras aumenta a altura e derruba a
    proporcao mesmo quando o giro horizontal foi completo.
    """
    yaws, pitches, focais = [], [], []
    for c in cameras:
        R = np.array(c.R, dtype=np.float64)
        yaws.append(np.degrees(np.arctan2(R[0, 2], R[2, 2])))
        pitches.append(np.degrees(np.arcsin(np.clip(-R[1, 2], -1.0, 1.0))))
        focais.append(float(c.focal))

    yaws = np.array(yaws)
    pitches = np.array(pitches)
    focal = float(np.median(focais)) or 1.0
    fov = float(np.degrees(2 * np.arctan(largura_foto / (2 * focal))))

    ordenados = np.sort(np.mod(yaws, 360.0))
    buracos = np.diff(np.concatenate([ordenados, [ordenados[0] + 360.0]]))
    maior_buraco = float(buracos.max())

    # a volta fechou se nenhum vao entre fotos vizinhas for maior que o campo de
    # visao de uma foto - abaixo disso as imagens ainda se tocam e cobrem a esfera
    fechada = maior_buraco < fov * 0.95

    span_pitch = float(pitches.max() - pitches.min())

    # Camera de celular fica entre 50 e 80 graus de campo horizontal. Muito fora
    # disso, a estimativa de foco nao fecha com a realidade — acontece quando as
    # fotos nao sao um giro no eixo, e o resultado seria um haov sem sentido.
    confiavel = 25.0 <= fov <= 120.0

    # cobertura vertical: o quanto as fotos inclinaram mais o campo de uma foto.
    # Celular em pe tem o sensor mais alto que largo, dai o 4/3.
    vaov_real = min(180.0, span_pitch + fov * 4.0 / 3.0)

    return {
        "haov": 360.0 if fechada else min(360.0, (360.0 - maior_buraco) + fov),
        "vaov_real": vaov_real,
        "fechada": fechada,
        "maior_buraco": maior_buraco,
        "fov": fov,
        "confiavel": confiavel,
        "fileiras": 1 if span_pitch < 15 else (2 if span_pitch < 50 else 3),
    }


class ErroCostura(Exception):
    """Falha de costura com mensagem explicativa para o usuario final."""


def _ler_imagem(caminho):
    dados = np.fromfile(caminho, dtype=np.uint8)   # suporta acento no caminho
    img = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if img is None:
        raise ErroCostura("Não consegui abrir o arquivo: %s" % os.path.basename(caminho))
    return img


def _salvar(img, caminho, qualidade=90):
    ext = os.path.splitext(caminho)[1]
    ok, buf = cv2.imencode(ext, img, [cv2.IMWRITE_JPEG_QUALITY, qualidade])
    if not ok:
        raise ErroCostura("Falha ao gravar a imagem final.")
    buf.tofile(caminho)


def _redimensionar(img, largura_alvo):
    h, w = img.shape[:2]
    if w <= largura_alvo:
        return img
    escala = largura_alvo / float(w)
    return cv2.resize(img, (int(w * escala), int(h * escala)), interpolation=cv2.INTER_AREA)


def _cortar_bordas_pretas(img):
    """Remove a moldura preta que a costura esferica deixa em volta."""
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, mascara = cv2.threshold(cinza, 1, 255, cv2.THRESH_BINARY)
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return img
    x, y, w, h = cv2.boundingRect(max(contornos, key=cv2.contourArea))
    recorte = img[y:y + h, x:x + w]

    # encolhe ate nao sobrar preto nas bordas
    for _ in range(60):
        r = recorte
        if r.shape[0] < 40 or r.shape[1] < 40:
            break
        topo = r[0, :, :].max() < 8
        base = r[-1, :, :].max() < 8
        esq = r[:, 0, :].max() < 8
        dir_ = r[:, -1, :].max() < 8
        if not (topo or base or esq or dir_):
            break
        recorte = r[1 if topo else 0: r.shape[0] - (1 if base else 0),
                    1 if esq else 0: r.shape[1] - (1 if dir_ else 0)]
    return recorte


def _maior_retangulo_cheio(mascara):
    """
    Maior retangulo sem nenhum pixel vazio, pelo metodo do histograma.
    Devolve (x0, y0, x1, y1) em coordenadas da mascara.
    """
    altura, largura = mascara.shape
    alturas = np.zeros(largura, dtype=np.int32)
    melhor = (0, 0, 0, 0, 0)

    for i in range(altura):
        alturas = np.where(mascara[i], alturas + 1, 0)
        pilha = []
        for j in range(largura + 1):
            atual = int(alturas[j]) if j < largura else 0
            inicio = j
            while pilha and pilha[-1][1] >= atual:
                inicio, alt = pilha.pop()
                area = alt * (j - inicio)
                if area > melhor[0]:
                    melhor = (area, inicio, i - alt + 1, j, i + 1)
            pilha.append((inicio, atual))

    _, x0, y0, x1, y1 = melhor
    return x0, y0, x1, y1


# Medido nas 16 fotos de um quarto real: o OpenCV ja compensa o ganho entre as
# fotos, entao o brilho medio do panorama sai uniforme. O que sobrava era perda
# de detalhe nas sombras — 11% dos pixels esmagados abaixo de 25.
#
# A correcao e local, nao global: achatar o brilho do panorama inteiro destruiria
# a iluminacao real, porque a parede da janela e mesmo mais clara que o canto.
# Com CLAHE no canal de luminancia, a sombra esmagada caiu para 7,2% sem mexer
# no estouro. Limite 4,0 foi testado e PIOROU (15%), por redistribuir demais.
LIMITE_CLAHE = 2.5
GRADE_CLAHE = (16, 8)


def ajustar_exposicao(img):
    """Recupera detalhe nas sombras sem estourar as partes claras."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=LIMITE_CLAHE, tileGridSize=GRADE_CLAHE).apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def medir_exposicao(img):
    """Numeros que o painel mostra para o corretor julgar a captura."""
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    validos = cinza[cinza > 6]
    if validos.size == 0:
        return {}
    return {
        "brilho": round(float(validos.mean()), 1),
        "sombra_esmagada": round(float((validos < 25).mean() * 100), 2),
        "estourado": round(float((validos > 250).mean() * 100), 2),
    }


def _preencher_bordas_irregulares(img):
    """
    Elimina o recorte preto ondulado de cima e de baixo estendendo, em cada coluna,
    a cor do ultimo pixel valido ate a borda — depois suaviza so o que foi preenchido.

    Recortar no retangulo cheio seria mais simples, mas custa caro: numa costura
    tipica de quarto o maior retangulo 100% preenchido guarda menos de 20% da area,
    o que jogaria fora quase todo o campo de visao vertical.
    """
    altura, largura = img.shape[:2]
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    valido = cinza > 6

    tem_conteudo = valido.any(axis=0)
    if not tem_conteudo.any():
        return img

    primeira = np.argmax(valido, axis=0)
    ultima = altura - 1 - np.argmax(valido[::-1], axis=0)

    saida = img.copy()
    preenchido = np.zeros((altura, largura), dtype=bool)

    # A cor de cada coluna e suavizada na horizontal ANTES de ser esticada. Sem isso,
    # um movel escuro encostado na borda vira uma listra vertical subindo pelo teto.
    cor_topo = np.array([img[int(primeira[x]), x] for x in range(largura)], dtype=np.float32)
    cor_base = np.array([img[int(ultima[x]), x] for x in range(largura)], dtype=np.float32)
    cor_topo = cv2.GaussianBlur(cor_topo.reshape(1, largura, 3), (0, 0), sigmaX=70)[0]
    cor_base = cv2.GaussianBlur(cor_base.reshape(1, largura, 3), (0, 0), sigmaX=70)[0]

    for x in range(largura):
        if not tem_conteudo[x]:
            continue
        p, u = int(primeira[x]), int(ultima[x])
        if p > 0:
            saida[:p, x] = cor_topo[x]
            preenchido[:p, x] = True
        if u < altura - 1:
            saida[u + 1:, x] = cor_base[x]
            preenchido[u + 1:, x] = True

    # colunas totalmente vazias herdam a vizinha mais proxima que tenha conteudo
    if not tem_conteudo.all():
        indices = np.where(tem_conteudo)[0]
        for x in np.where(~tem_conteudo)[0]:
            saida[:, x] = saida[:, indices[np.argmin(np.abs(indices - x))]]
            preenchido[:, x] = True

    # sem isso o preenchimento vira listras verticais visiveis
    suave = cv2.GaussianBlur(saida, (0, 0), sigmaX=25, sigmaY=9)
    peso = cv2.GaussianBlur(preenchido.astype(np.float32), (0, 0), sigmaX=9, sigmaY=9)
    peso = np.clip(peso, 0, 1)[:, :, None]
    return (saida * (1 - peso) + suave * peso).astype(np.uint8)


def _completar_esfera(img):
    """
    Encaixa a faixa panoramica numa tela 2:1 (equirretangular completa) e preenche
    teto e chao esticando as cores das bordas, com desfoque progressivo.

    Sem isso o visitante ve preto ao olhar para cima ou para baixo, porque a faixa
    cobre so a altura que a camera alcancou. O preenchimento nao inventa detalhe:
    e a propria cor do teto e do piso, borrada ate o polo.
    """
    h, w = img.shape[:2]
    altura_alvo = w // 2
    if h >= altura_alvo:
        return cv2.resize(img, (w, altura_alvo), interpolation=cv2.INTER_AREA)

    tela = np.zeros((altura_alvo, w, 3), dtype=np.uint8)
    topo = (altura_alvo - h) // 2
    tela[topo:topo + h] = img

    def preencher(faixa_origem, destino_ini, destino_fim, para_cima):
        if destino_fim <= destino_ini:
            return
        base = cv2.GaussianBlur(faixa_origem.mean(axis=0).astype(np.float32)
                                .reshape(1, w, 3), (61, 1), 0)[0]
        cor_polo = base.mean(axis=0)
        n = destino_fim - destino_ini
        for k in range(n):
            t = (k + 1) / float(n) if para_cima else (n - k) / float(n)
            t = t ** 0.7                     # aproxima do polo mais rapido
            linha = base * (1 - t) + cor_polo * t
            tela[destino_ini + k] = linha.astype(np.uint8)

    preencher(img[:12], 0, topo, para_cima=False)
    preencher(img[-12:], topo + h, altura_alvo, para_cima=True)
    return tela


def _contar_pares_com_sobreposicao(imagens):
    """
    Mede quantos pares consecutivos realmente compartilham conteudo.
    Serve para dar um diagnostico honesto quando a costura falha.
    """
    orb = cv2.ORB_create(1200)
    casador = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    descritores = []
    for img in imagens:
        cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, desc = orb.detectAndCompute(cinza, None)
        descritores.append(desc)

    pares_ok = 0
    for i in range(len(descritores) - 1):
        a, b = descritores[i], descritores[i + 1]
        if a is None or b is None or len(a) < 10 or len(b) < 10:
            continue
        casamentos = casador.match(a, b)
        bons = [m for m in casamentos if m.distance < 45]
        if len(bons) >= 25:
            pares_ok += 1
    return pares_ok


def _diagnostico(codigo, imagens):
    qtd = len(imagens)

    if qtd < MINIMO_RECOMENDADO:
        pares = _contar_pares_com_sobreposicao(imagens)
        if pares == 0:
            return ("Estas %d fotos não têm trecho em comum. Pelo que a análise mostra, "
                    "elas foram tiradas de pontos diferentes do cômodo — você andou entre "
                    "uma foto e outra. Para o 360 funcionar você precisa ficar parado no "
                    "mesmo lugar e girar o corpo, tirando de 8 a 12 fotos, cada uma "
                    "repetindo cerca de 30%% do que apareceu na anterior." % qtd)
        return ("Só %d fotos não fecham uma volta completa. Fique parado no centro do "
                "cômodo e tire de 8 a 12 fotos girando aos poucos, sem sair do lugar."
                % qtd)

    if codigo == cv2.STITCHER_ERR_NEED_MORE_IMGS:
        return ("As fotos não têm sobreposição suficiente. Cada foto precisa repetir cerca "
                "de 30%% do que aparece na anterior. Você enviou %d fotos — gire menos a "
                "cada clique e tire mais fotos no mesmo ponto." % qtd)
    if codigo == cv2.STITCHER_ERR_HOMOGRAPHY_EST_FAIL:
        return ("Não consegui alinhar as fotos. Isso costuma acontecer quando a câmera sai "
                "do lugar entre um clique e outro, ou quando a parede é lisa demais e não "
                "tem pontos de referência.")
    if codigo == cv2.STITCHER_ERR_CAMERA_PARAMS_ADJUST_FAIL:
        return ("As fotos foram tiradas de posições diferentes do cômodo. Para o 360 "
                "funcionar, você precisa girar no próprio eixo, sem andar.")
    return "A costura falhou (código %s)." % codigo


PREENCHIMENTO_MINIMO = 0.85   # costura boa fica ~100%; deformada cai para ~60%


def _preenchimento(panorama):
    """Fracao da imagem que tem conteudo real (o resto e vazio deixado pela projecao)."""
    cinza = cv2.cvtColor(panorama, cv2.COLOR_BGR2GRAY)
    return (cinza > 6).sum() / float(cinza.size)


def _resolucao_emenda(quantidade):
    """
    Resolucao em que o OpenCV procura onde cortar entre duas fotos vizinhas.
    E a etapa mais cara da composicao e cresce muito com o numero de fotos: em
    30 fotos, baixar de 0,1 para 0,015 levou o tempo de 122s para 16s sem
    diferenca visivel nas emendas.
    """
    if quantidade >= 20:
        return 0.015
    if quantidade >= 10:
        return 0.04
    return 0.08


def _resultado_aproveitavel(panorama, imagens, usadas=None):
    """
    O OpenCV as vezes devolve STITCHER_OK com um resultado inutil. Dois casos:

    1. Juntou so uma faixa minima e o panorama fica do tamanho de uma foto sozinha.
    2. Encaixou tudo, mas com a geometria errada — o comodo vira um arco torto e
       sobra vazio em volta. Acontece quando as fotos saem de pontos diferentes.

    Ambos sao piores que um erro claro, porque o usuario so descobre o problema
    depois de montar o tour inteiro. Devolve (aprovado, motivo).
    """
    if panorama is None:
        return False, "vazio"

    # Quantas fotos o OpenCV realmente aproveitou. Se descartou a maioria, sobrou
    # so um pedaco do comodo por mais que a imagem pareca aceitavel.
    if usadas is not None and len(usadas) < max(2, int(len(imagens) * 0.6)):
        return False, "descartadas"

    # Checagem minima de largura: pega fotos praticamente iguais, em que a costura
    # devolve algo do tamanho de uma foto so. Nao da para exigir muito mais que isso,
    # porque uma captura parcial legitima (meia volta) tambem produz panorama curto.
    if panorama.shape[1] < imagens[0].shape[1] * 1.3:
        return False, "estreito"

    if _preenchimento(panorama) < PREENCHIMENTO_MINIMO:
        return False, "deformado"

    return True, "ok"


def _tentar_costurar(imagens):
    """
    Tenta a costura em varias configuracoes, da mais exigente para a mais tolerante,
    e so aceita um resultado que realmente seja um panorama.
    Devolve (panorama, codigo_do_ultimo_erro, houve_resultado_fraco).
    """
    # Ordenadas por custo x chance de acerto: as tres primeiras sao rapidas.
    tentativas = [
        (cv2.Stitcher_PANORAMA, 1.0),   # padrao, camera girando no eixo
        (cv2.Stitcher_PANORAMA, 0.6),   # aceita pares com menos confianca
        (cv2.Stitcher_SCANS,    1.0),   # pouca rotacao / camera quase transladando
        (cv2.Stitcher_PANORAMA, 0.3),   # ultimo recurso esferico
        (cv2.Stitcher_SCANS,    0.6),   # lento: so vale a pena em lotes pequenos
    ]
    # cada tentativa refaz a costura inteira: com muitas fotos as duas ultimas
    # sozinhas passariam de um minuto, o que trava a tela do usuario.
    if len(imagens) >= 10:
        tentativas = tentativas[:3]

    ultimo_codigo = cv2.STITCHER_ERR_NEED_MORE_IMGS
    motivo_recusa = None

    for modo, confianca in tentativas:
        st = cv2.Stitcher_create(modo)
        try:
            st.setPanoConfidenceThresh(confianca)
            st.setSeamEstimationResol(_resolucao_emenda(len(imagens)))
        except cv2.error:
            pass
        try:
            # em duas etapas para poder ler as cameras: o stitch() de uma tacada
            # so devolve a imagem e descarta a geometria da captura
            codigo = st.estimateTransform(imagens)
            if codigo != cv2.STITCHER_OK:
                ultimo_codigo = codigo
                continue
            geo = _geometria(st.cameras(), imagens[0].shape[1])
            usadas = st.component()
            codigo, panorama = st.composePanorama(imagens)
        except cv2.error:
            ultimo_codigo = cv2.STITCHER_ERR_NEED_MORE_IMGS
            continue

        if codigo == cv2.STITCHER_OK and panorama is not None:
            # corta ANTES de medir: a moldura preta infla a largura e
            # faria um resultado ruim passar na validacao.
            panorama = _cortar_bordas_pretas(panorama)
            aprovado, motivo = _resultado_aproveitavel(panorama, imagens, usadas)
            if aprovado:
                return panorama, codigo, None, geo
            motivo_recusa = motivo          # resultado inutil: descarta e segue
            continue
        ultimo_codigo = codigo

    return None, ultimo_codigo, motivo_recusa, None


ABERTURA_TETO = 70.0        # graus a partir do polo considerados na analise
SUAVIDADE_TETO = 16.0


def limite_do_teto(equi, limiar=8.0):
    """
    Ate quantos graus do polo superior nao existe foto de verdade.

    Medido na propria imagem, varrendo de cima ate aparecer detalhe. A alternativa
    seria deduzir do campo da lente, mas essa estimativa vem do ajuste de foco do
    OpenCV e sai inflada: num caso real dava 115 graus de lente, o que apontaria
    um buraco de 7 graus quando o real era 44.
    """
    H = equi.shape[0]
    for y in range(0, H // 2, 6):
        faixa = cv2.cvtColor(equi[y:y + 14], cv2.COLOR_BGR2GRAY)
        if cv2.Laplacian(faixa, cv2.CV_32F).var() > limiar:
            return max(0.0, 90.0 - (y / float(H)) * 180.0)
    return 0.0


def preencher_teto(equi, graus_sem_dado):
    """
    Refaz o teto onde a captura nao alcancou.

    O preenchimento padrao estica a cor de cada coluna para cima, o que no polo
    vira um leque de cunhas — o defeito mais visivel ao olhar para cima. Aqui o
    teto observado e projetado numa vista azimutal (o polo vira o centro, sem a
    distorcao do equirretangular), ajusta-se uma superficie suave a ele e essa
    superficie e estendida para dentro do buraco.

    So entram no ajuste os pixels mais claros do anel: o anel tambem contem topo
    de armario e quina escura, e incluir isso puxava a cor para um disco cinza.

    Nao e invencao de conteudo: e a continuacao da superficie que a foto mostra.
    Medido no quarto de teste, a energia de cunha caiu de 50,8 para 3,7. O LaMa
    (198 MB) foi testado no mesmo caso e chegou a 37,3 — a tecnica simples ganhou.
    """
    H, W = equi.shape[:2]
    if abs(W / float(H) - 2.0) > 0.1 or graus_sem_dado < 4:
        return equi

    lado = 640
    eixo = (np.arange(lado, dtype=np.float32) - lado / 2.0) / (lado / 2.0)
    X, Y = np.meshgrid(eixo, eixo)
    raio = np.sqrt(X * X + Y * Y)
    theta = raio * np.radians(ABERTURA_TETO)

    # equirretangular -> vista azimutal do zenite
    phi = np.arctan2(X, -Y)
    lat = -(np.pi / 2 - theta)
    mx = ((phi / (2 * np.pi)) + 0.5) * W
    my = ((lat / np.pi) + 0.5) * H
    vista = cv2.remap(equi, mx.astype(np.float32), my.astype(np.float32),
                      cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)

    limite = np.radians(min(graus_sem_dado, ABERTURA_TETO - 8))
    buraco = (theta < limite) & (raio <= 1)
    anel = (theta >= limite) & (theta < limite + np.radians(18)) & (raio <= 1)
    if buraco.sum() < 400 or anel.sum() < 400:
        return equi

    cinza = cv2.cvtColor(vista, cv2.COLOR_BGR2GRAY)
    claros = anel & (cinza > np.percentile(cinza[anel], 55))
    if claros.sum() < 200:
        claros = anel

    def termos(x, y):
        return np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], 1)

    A = termos(X[claros], Y[claros])
    B = termos(X[buraco], Y[buraco])
    saida = vista.copy().astype(np.float32)
    for canal in range(3):
        coef, *_ = np.linalg.lstsq(A, vista[claros][:, canal].astype(np.float32),
                                   rcond=None)
        saida[buraco, canal] = np.clip(B @ coef, 0, 255)

    # ruido fraco com a mesma textura do teto observado: sem isso fica plastico
    desvio = float(cinza[claros].std()) * 0.10
    ruido = np.random.default_rng(7).normal(0, desvio, (lado, lado, 1)).astype(np.float32)
    saida[buraco] += ruido[buraco]

    peso = cv2.GaussianBlur((buraco * 255).astype(np.uint8), (0, 0),
                            SUAVIDADE_TETO).astype(np.float32)[..., None] / 255.0
    vista = (vista * (1 - peso) + np.clip(saida, 0, 255) * peso).astype(np.uint8)
    # mapa de "aqui eu mexi", em 8 bits para viajar pelo mesmo remap da imagem
    mexido = (peso[..., 0] * 255).astype(np.uint8)

    # de volta para o equirretangular, so na calota de cima
    lon = (np.arange(W, dtype=np.float32) / W - 0.5) * 2 * np.pi
    latE = (np.arange(H, dtype=np.float32) / H - 0.5) * np.pi
    lonG, latG = np.meshgrid(lon, latE)
    thetaE = np.pi / 2 + latG                      # 0 no polo de cima
    dentro = thetaE < np.radians(ABERTURA_TETO)
    rr = thetaE / np.radians(ABERTURA_TETO)
    ux = (0.5 + 0.5 * rr * np.sin(lonG)) * (lado - 1)
    uy = (0.5 - 0.5 * rr * np.cos(lonG)) * (lado - 1)
    volta_peso = cv2.remap(mexido, ux.astype(np.float32), uy.astype(np.float32),
                           cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    volta = cv2.remap(vista, ux.astype(np.float32), uy.astype(np.float32),
                      cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    # So o que foi PREENCHIDO volta do disco. Misturar a calota inteira trocava
    # pixel bom por pixel do disco de 640 px, que a 60 graus do polo tem 4,8 px
    # por grau contra 14 do equirretangular — subamostragem de 3x, que aparecia
    # como uma emenda serrilhada na junta do teto com a parede.
    mistura = (volta_peso.astype(np.float32) / 255.0)
    mistura *= np.clip((np.radians(ABERTURA_TETO) - thetaE) / np.radians(10), 0, 1)
    mistura = (mistura * dentro)[..., None]
    return (equi * (1 - mistura) + volta * mistura).astype(np.uint8)


def _nivelar(panorama):
    """Endireita o horizonte, engolindo a falha: cena sem quinas nao tem prumo."""
    try:
        img, info = nivelamento.nivelar(panorama)
        # o vetor de prumo e detalhe interno e nao sobrevive ao json.dump do tour
        info.pop("direcao", None)
        return img, info
    except nivelamento.ErroNivelamento as e:
        return panorama, {"aplicado": False, "motivo": str(e)}
    except Exception:
        return panorama, {"aplicado": False, "motivo": "falha ao nivelar"}


def costurar(caminhos, pasta_saida, relatar=None):
    """
    Costura N fotos numa panoramica esferica.
    relatar(progresso, etapa) e opcional e serve para a fila mostrar o andamento.
    """
    aviso = relatar or (lambda p, e: None)
    if len(caminhos) < 2:
        raise ErroCostura("Envie pelo menos 2 fotos para costurar um panorama.")

    # a flag e por thread e esta funcao roda na thread da requisicao, nao na de import
    cv2.ocl.setUseOpenCL(False)

    aviso(10, "lendo %d fotos" % len(caminhos))
    largura = _largura_trabalho(len(caminhos))
    imagens = [_redimensionar(_ler_imagem(c), largura) for c in caminhos]

    aviso(25, "alinhando e costurando")
    panorama, codigo, motivo, geo = _tentar_costurar(imagens)
    if panorama is None:
        if motivo == "estreito":
            raise ErroCostura(
                "Consegui encaixar só uma faixa estreita das fotos — o resultado ficaria "
                "quase do tamanho de uma foto só, sem servir como 360. Isso indica que as "
                "fotos pegam pedaços diferentes do cômodo e mal se tocam. Fique parado no "
                "mesmo ponto e tire de 8 a 12 fotos girando aos poucos.")
        if motivo == "descartadas":
            raise ErroCostura(
                "A maioria das fotos não encaixou com as vizinhas e ficou de fora, "
                "então sobraria só um pedaço do cômodo. Isso costuma acontecer quando "
                "a sequência tem saltos: você girou demais entre alguns cliques, ou "
                "misturou fotos de ambientes diferentes no mesmo envio.")
        if motivo == "deformado":
            raise ErroCostura(
                "As fotos até se encaixaram, mas o cômodo saiu torto: as paredes viraram "
                "um arco e sobrou vazio em volta. Isso acontece quando as fotos são tiradas "
                "de pontos diferentes do cômodo — ao mudar de lugar, os móveis se deslocam "
                "uns em relação aos outros e não existe encaixe correto possível. "
                "Refaça ficando parado no mesmo ponto, girando só o corpo, com 8 a 12 fotos.")
        raise ErroCostura(_diagnostico(codigo, imagens))

    # O corte das bordas e a validacao ja aconteceram dentro de _tentar_costurar.
    # O acabamento vem depois de propositio: preencher as bordas deixaria a imagem
    # 99% cheia e a checagem de panorama deformado nunca mais reprovaria nada.
    aviso(78, "corrigindo a exposição")
    antes = medir_exposicao(panorama)
    panorama = ajustar_exposicao(panorama)
    depois = medir_exposicao(panorama)

    aviso(85, "acabamento das bordas")
    panorama = _preencher_bordas_irregulares(panorama)

    info = dict(geo)
    if not geo["confiavel"]:
        # sem geometria confiavel, volta para a leitura pela proporcao: uma faixa
        # bem mais larga que alta so acontece quando o giro deu quase a volta
        proporcao = panorama.shape[1] / float(panorama.shape[0])
        info["fechada"] = proporcao >= 2.6
        info["haov"] = 360.0 if info["fechada"] else min(360.0, proporcao * 45.0)

    # A esfera 2:1 so faz sentido quando o giro fechou a volta. Se a captura foi
    # parcial, esticar para 360 graus deformaria o comodo inteiro; nesse caso o
    # panorama fica parcial e o haov real vai junto para o visualizador.
    if info["fechada"]:
        panorama = _completar_esfera(panorama)
        # Nivelar so depois da esfera fechada: a rotacao trata o panorama como
        # uma superficie completa, e numa faixa parcial o mapeamento seria outro.
        aviso(88, "nivelando o horizonte")
        panorama, info["nivelamento"] = _nivelar(panorama)

        aviso(94, "refazendo o teto")
        sem_dado = limite_do_teto(panorama)
        panorama = preencher_teto(panorama, sem_dado)

    aviso(92, "gravando o panorama")
    panorama = _redimensionar(panorama, LARGURA_MAX_SAIDA)

    nome = "cena_%s.jpg" % uuid.uuid4().hex[:12]
    _salvar(panorama, os.path.join(pasta_saida, nome))
    h, w = panorama.shape[:2]

    info["vaov"] = 180.0 if info["fechada"] else info["haov"] * (h / float(w))
    info["exposicao"] = {"antes": antes, "depois": depois}
    return nome, w, h, info


def importar_equirretangular(caminho_origem, pasta_saida):
    """
    Aceita uma foto 360 ja pronta (camera 360 ou app de celular).

    Passa pelo mesmo nivelamento e reconstrucao de teto da costura: o modo
    Panorama do celular sai torto com a mesma frequencia, e quem gira o aparelho
    na mao raramente alcanca o zenite. As duas correcoes se protegem sozinhas —
    o nivelamento ignora desvios abaixo de 0,8 grau e o teto so age quando falta
    mais de 4 graus de foto —, entao uma imagem ja boa sai intacta.

    Exposicao fica de fora de proposito: o CLAHE e incondicional e uma foto que
    ja veio tratada pela camera so teria a perder.
    """
    img = _ler_imagem(caminho_origem)
    img = _redimensionar(img, LARGURA_MAX_SAIDA)
    info = {"nivelamento": {"aplicado": False}, "teto": 0.0}
    if eh_equirretangular(img.shape[1], img.shape[0]):
        img, info["nivelamento"] = _nivelar(img)
        info["teto"] = limite_do_teto(img)
        img = preencher_teto(img, info["teto"])
    nome = "cena_%s.jpg" % uuid.uuid4().hex[:12]
    _salvar(img, os.path.join(pasta_saida, nome))
    h, w = img.shape[:2]
    return nome, w, h


def reprocessar(caminho_panorama):
    """
    Reaplica nivelamento e reconstrucao de teto num panorama ja gravado.

    Cenas montadas por versoes anteriores do pipeline ficaram com o horizonte
    torto e com o leque de cunhas no teto. Recostura-las exigiria as fotos
    originais, que o sistema apaga depois de montar a cena; estas duas correcoes
    trabalham sobre o equirretangular pronto, entao ainda dao para aplicar.

    Exposicao nao entra: o CLAHE ja foi aplicado uma vez e repetir escureceria
    o resultado a cada passagem.
    """
    img = _ler_imagem(caminho_panorama)
    if not eh_equirretangular(img.shape[1], img.shape[0]):
        raise ErroCostura("Só dá para corrigir panorama 360 completo (proporção 2:1).")

    img, nivel = _nivelar(img)
    graus = limite_do_teto(img)
    antes = img
    img = preencher_teto(img, graus)
    _salvar(img, caminho_panorama)
    return {
        "nivelamento": nivel,
        "teto_graus": round(float(graus), 1),
        "teto_aplicado": bool(graus >= 4 and img is not antes),
    }


def importar_varredura(caminho_origem, pasta_saida, haov_graus=360.0):
    """
    Converte um panorama de varredura de celular (modo Panorama do iPhone/Android)
    em equirretangular.

    A varredura sai em projecao CILINDRICA, nao esferica: a altura cresce com a
    tangente da latitude, nao com a latitude. Carregar do jeito que vem esticaria
    teto e chao. A conversao amostra, para cada linha do equirretangular, a altura
    correspondente no cilindro.

    O campo vertical nao precisa ser informado: com a cobertura horizontal conhecida,
    ele sai da propria proporcao da imagem, porque no cilindro
    largura/altura = haov / (2*tan(vfov/2)).
    """
    cil = _ler_imagem(caminho_origem)
    cil = _redimensionar(cil, LARGURA_MAX_SAIDA)
    Hc, Wc = cil.shape[:2]

    haov = np.radians(max(30.0, min(360.0, float(haov_graus))))
    vfov = 2.0 * np.arctan(haov * Hc / (2.0 * Wc))
    if not np.isfinite(vfov) or vfov <= 0:
        raise ErroCostura("Não consegui interpretar a geometria dessa varredura.")

    # tela equirretangular na mesma escala angular da entrada
    W = int(round(Wc * (2 * np.pi) / haov))
    W = max(1024, min(LARGURA_MAX_SAIDA, W - (W % 2)))
    H = W // 2

    lon = (np.arange(W, dtype=np.float32) / W - 0.5) * 2 * np.pi
    lat = (np.arange(H, dtype=np.float32) / H - 0.5) * np.pi
    lon, lat = np.meshgrid(lon, lat)

    # cilindro: x acompanha a longitude, y e a tangente da latitude
    mx = (lon / haov + 0.5) * Wc
    my = (np.tan(lat) / (2 * np.tan(vfov / 2)) + 0.5) * Hc

    dentro = (np.abs(lat) < vfov / 2 - 1e-4) & (np.abs(lon) <= haov / 2 + 1e-6)
    mx = np.where(dentro, mx, -1).astype(np.float32)
    my = np.where(dentro, my, -1).astype(np.float32)

    equi = cv2.remap(cil, mx, my, cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))

    equi = ajustar_exposicao(equi)
    equi = _preencher_bordas_irregulares(equi)
    nivel = {"aplicado": False}
    if haov_graus >= 359.0:
        equi, nivel = _nivelar(equi)
        # a varredura sobe pouco: o topo fica tao esticado quanto na costura
        equi = preencher_teto(equi, limite_do_teto(equi))
    nome = "cena_%s.jpg" % uuid.uuid4().hex[:12]
    _salvar(equi, os.path.join(pasta_saida, nome))

    fechada = haov_graus >= 359.0
    return nome, equi.shape[1], equi.shape[0], {
        "nivelamento": nivel,
        "haov": 360.0 if fechada else float(haov_graus),
        "vaov": 180.0 if fechada else float(np.degrees(vfov)),
        "fechada": fechada,
        "maior_buraco": 0.0 if fechada else 360.0 - float(haov_graus),
        "fov": float(np.degrees(vfov)),
        "confiavel": True,
        "fileiras": 1,
    }


def eh_equirretangular(largura, altura):
    """Equirretangular completa tem proporcao 2:1 (tolerancia de 5%)."""
    if altura == 0:
        return False
    return abs((largura / float(altura)) - 2.0) < 0.1


VAOV_CELULAR = 65.0      # campo vertical tipico de camera de celular


def cobertura_parcial(largura, altura):
    """
    Cobertura estimada de uma foto que NAO esta em 2:1.

    Assumir 360 graus aqui era um erro caro: um panorama 3:1 do celular cobre uns
    195 graus na pratica, e espalha-lo pela volta inteira estica a cena 1,8 vez —
    parede entortada, comodo parecendo maior do que e. Sem metadado nao da para
    saber o angulo real, mas o campo vertical de camera de celular varia pouco,
    entao partir dele erra muito menos do que partir de 360.

    O painel tem o campo "Cobertura horizontal" para o corretor acertar na mao.
    """
    vaov = VAOV_CELULAR
    haov = min(360.0, vaov * (largura / float(altura)))
    return round(haov, 2), round(vaov, 2)


def cobertura_angular(largura, altura, haov=None):
    """
    Em projecao esferica os graus por pixel sao constantes.
    Logo vaov = haov * altura / largura.
    """
    if haov is None:
        haov = 360.0
    vaov = haov * (altura / float(largura))
    return round(haov, 2), round(min(vaov, 180.0), 2)
