# -*- coding: utf-8 -*-
"""
Endereco fixo para o link do imovel.

O PROBLEMA QUE ISTO RESOLVE. O tour rodava atras de um tunel "rapido" do
Cloudflare, do tipo que nao pede conta: ele levanta em um segundo e entrega um
endereco sorteado, do feitio `pressing-randy-limitation-robert.trycloudflare.com`.
Serve para olhar uma vez. Nao serve para VENDER:

  - o endereco muda a cada reinicio, entao o link que o corretor mandou ontem
    para o cliente nao abre hoje — e ninguem avisa; o cliente so ve erro;
  - o tunel rapido cai sozinho depois de algumas horas;
  - "pressing-randy-limitation-robert" num WhatsApp parece golpe, e parte dos
    clientes simplesmente nao clica.

Com dominio reservado o endereco e sempre o mesmo. O link vira um endereco que
se pode imprimir num anuncio, mandar por e-mail e repetir ao telefone.

O QUE ESTE ARQUIVO NAO FAZ: tocar em credencial. O token do Cloudflare ou do
ngrok e seu, fica guardado por eles no perfil da sua maquina, e e configurado
UMA VEZ por voce — as instrucoes estao em docs/endereco-fixo.md. Aqui so entra
o NOME do dominio, que e publico por definicao: ele aparece na barra do
navegador de todo visitante.
"""
import os
import shutil
import subprocess
import sys
import threading


def _config():
    return {
        # "cloudflare", "ngrok" ou vazio (sem tunel)
        "tipo": (os.environ.get("TOUR_TUNEL") or "").strip().lower(),
        # o dominio JA RESERVADO, por exemplo "tour.suaimobiliaria.com.br"
        "dominio": (os.environ.get("TOUR_TUNEL_DOMINIO") or "").strip(),
        # so para o cloudflare: o nome do tunel criado com `tunnel create`
        "nome": (os.environ.get("TOUR_TUNEL_NOME") or "tour").strip(),
    }


def por_que_nao():
    """
    Por que o tunel nao vai subir, em portugues e com o conserto junto.

    Devolve None quando esta tudo certo. Recado vago aqui custa caro: quem
    descobre que o tunel nao subiu normalmente descobre pelo cliente dizendo
    que o link nao abre.
    """
    c = _config()
    if not c["tipo"]:
        return ("TOUR_TUNEL não está definido. Sem ele o tour fica só na rede "
                "local. Veja docs/endereco-fixo.md.")
    if c["tipo"] not in ("cloudflare", "ngrok"):
        return ("TOUR_TUNEL=%r não existe. Use 'cloudflare' ou 'ngrok'."
                % c["tipo"])
    if not c["dominio"]:
        return ("TOUR_TUNEL_DOMINIO está vazio. É o domínio que você reservou "
                "— sem ele o endereço volta a ser sorteado a cada reinício, "
                "que é exatamente o problema que o túnel fixo resolve.")
    exe = "cloudflared" if c["tipo"] == "cloudflare" else "ngrok"
    if not shutil.which(exe):
        return ("Não encontrei o %s no PATH. Instale com "
                "`winget install %s` e abra um terminal novo."
                % (exe, "cloudflare.cloudflared" if exe == "cloudflared"
                   else "ngrok.ngrok"))
    return None


def configurado():
    return por_que_nao() is None


def endereco():
    """O endereco publico do tour, ou None se nao ha tunel configurado."""
    c = _config()
    return "https://" + c["dominio"] if c["dominio"] else None


def _comando(porta):
    c = _config()
    alvo = "http://127.0.0.1:%d" % porta
    if c["tipo"] == "cloudflare":
        # `tunnel run` usa o tunel JA CRIADO e JA APONTADO para o dominio pelo
        # `tunnel route dns`. E o que garante o endereco fixo: o tunel rapido
        # (`--url` sozinho) sorteia um endereco novo toda vez.
        return ["cloudflared", "tunnel", "run", "--url", alvo, c["nome"]]
    return ["ngrok", "http", "--domain=" + c["dominio"], str(porta),
            "--log=stdout"]


def _repetir_saida(proc, prefixo):
    for linha in iter(proc.stdout.readline, ""):
        if not linha:
            break
        texto = linha.rstrip()
        if texto:
            print("  [%s] %s" % (prefixo, texto))
            sys.stdout.flush()


def subir(porta, relatar=print):
    """
    Levanta o tunel ao lado do servidor e devolve o processo.

    Devolve None quando nao ha tunel configurado — e isso NAO e erro: rodar so
    na rede local e um modo de uso legitimo, e derrubar o servidor porque o
    tunel nao subiu trocaria um problema por um pior.
    """
    motivo = por_que_nao()
    if motivo:
        relatar("  sem endereço fixo: " + motivo)
        return None

    c = _config()
    try:
        proc = subprocess.Popen(
            _comando(porta), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors="replace",
            bufsize=1)
    except OSError as erro:
        relatar("  não consegui subir o túnel: %s" % erro)
        return None

    threading.Thread(target=_repetir_saida, args=(proc, c["tipo"]),
                     daemon=True, name="tunel").start()
    relatar("  endereço fixo: %s" % endereco())
    return proc
