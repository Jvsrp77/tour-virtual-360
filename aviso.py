# -*- coding: utf-8 -*-
"""
Avisa o corretor quando um contato chega.

O motivo de existir: o lead era gravado no tour.json e ninguem ficava sabendo. O
corretor so descobria se abrisse o painel. Para quem vende imovel, contato que
espera um dia e contato perdido — o comprador ja falou com outro corretor. Era o
maior buraco do produto, e o mais barato de fechar.

Configuracao por variaveis de ambiente, porque senha de e-mail nao entra no
codigo nem no tour.json:

  TOUR_SMTP_SERVIDOR    smtp.gmail.com
  TOUR_SMTP_PORTA       587           (587 = STARTTLS, 465 = SSL direto)
  TOUR_SMTP_USUARIO     conta@dominio
  TOUR_SMTP_SENHA       a senha de aplicativo
  TOUR_SMTP_DE          remetente, se diferente do usuario
  TOUR_AVISO_PARA       para quem avisar (separado por virgula)

Sem TOUR_SMTP_SERVIDOR e TOUR_AVISO_PARA nada e enviado e nada quebra: o site
funciona igual, so nao avisa. E o estado em que ele nasce.

NUNCA derruba o cadastro do lead. O contato ja esta gravado quando isto roda; se
o e-mail falhar, o que nao pode acontecer e perder o contato por causa do aviso.
"""
import os
import smtplib
import ssl
import threading
import traceback
from email.message import EmailMessage
from email.utils import formataddr


def _config():
    return {
        "servidor": (os.environ.get("TOUR_SMTP_SERVIDOR") or "").strip(),
        "porta": int(os.environ.get("TOUR_SMTP_PORTA") or "587"),
        "usuario": (os.environ.get("TOUR_SMTP_USUARIO") or "").strip(),
        "senha": os.environ.get("TOUR_SMTP_SENHA") or "",
        "de": (os.environ.get("TOUR_SMTP_DE")
               or os.environ.get("TOUR_SMTP_USUARIO") or "").strip(),
        "para": [e.strip() for e in
                 (os.environ.get("TOUR_AVISO_PARA") or "").split(",") if e.strip()],
    }


def configurado():
    c = _config()
    return bool(c["servidor"] and c["para"] and c["de"])


def por_que_nao():
    """Recado para o painel dizer o que falta, em vez de silencio."""
    c = _config()
    if not c["servidor"]:
        return "falta TOUR_SMTP_SERVIDOR"
    if not c["de"]:
        return "falta TOUR_SMTP_USUARIO (ou TOUR_SMTP_DE)"
    if not c["para"]:
        return "falta TOUR_AVISO_PARA"
    return ""


def montar(lead, titulo_imovel, link=""):
    """
    Monta o aviso. Separado do envio para poder ser conferido sem rede.

    O telefone vai no ASSUNTO de proposito: o corretor le a notificacao no
    celular, na rua, e precisa poder ligar sem abrir nada.
    """
    nome = (lead.get("nome") or "sem nome").strip()
    tel = (lead.get("telefone") or "").strip()
    email = (lead.get("email") or "").strip()

    assunto = "Novo contato: %s" % nome
    if tel:
        assunto += " — %s" % tel
    if titulo_imovel:
        assunto += " (%s)" % titulo_imovel

    linhas = ["Um visitante deixou contato no tour.", ""]
    linhas.append("Imóvel:   %s" % (titulo_imovel or "—"))
    linhas.append("Nome:     %s" % nome)
    linhas.append("Telefone: %s" % (tel or "—"))
    linhas.append("E-mail:   %s" % (email or "—"))
    if lead.get("quando"):
        linhas.append("Quer visitar: %s" % lead["quando"])
    linhas.append("Recebido: %s" % lead.get("recebido_em", "—"))
    if link:
        linhas += ["", "Painel: %s" % link]
    if lead.get("consentimento"):
        linhas += ["", "Consentiu com: %s" % lead["consentimento"]]
    return assunto, "\n".join(linhas)


def _enviar_agora(assunto, corpo):
    c = _config()
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = formataddr(("Tour Virtual", c["de"]))
    msg["To"] = ", ".join(c["para"])
    msg.set_content(corpo)

    contexto = ssl.create_default_context()
    if c["porta"] == 465:
        with smtplib.SMTP_SSL(c["servidor"], c["porta"], context=contexto,
                              timeout=20) as s:
            if c["usuario"]:
                s.login(c["usuario"], c["senha"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(c["servidor"], c["porta"], timeout=20) as s:
            s.starttls(context=contexto)
            if c["usuario"]:
                s.login(c["usuario"], c["senha"])
            s.send_message(msg)


def testar():
    """
    Manda um e-mail de teste e devolve (ok, recado).

    Existe porque configurar SMTP erra em silencio: porta trocada, senha de
    aplicativo em vez da senha da conta, remetente que o servidor recusa. Sem
    um botao de teste, o corretor so descobre quando perde um contato de
    verdade — e ai ja perdeu.

    Devolve o erro REAL do servidor, nao "falhou": e a diferenca entre arrumar
    em dois minutos e ficar adivinhando.
    """
    falta = por_que_nao()
    if falta:
        return False, falta
    try:
        _enviar_agora("Teste do aviso de contato",
                      "Se voce recebeu este e-mail, o aviso de contato esta "
                      "funcionando.\n\nQuando um visitante deixar o contato no "
                      "tour, um aviso como este chega aqui.")
    except Exception as erro:
        return False, "%s: %s" % (type(erro).__name__, erro)
    return True, "Enviado para %s." % ", ".join(_config()["para"])


def avisar(lead, titulo_imovel, link="", esperar=False):
    """
    Dispara o aviso. Devolve True se chegou a tentar.

    Vai em outra thread: um SMTP lento seguraria a resposta ao VISITANTE, que
    ficaria olhando o botao girar depois de ja ter deixado o contato. O cadastro
    ja esta gravado quando isto roda — o aviso nunca pode derrubar o lead.

    `esperar` existe para o teste: sem ele a thread terminaria depois da assercao.
    """
    if not configurado():
        return False
    assunto, corpo = montar(lead, titulo_imovel, link)

    def tarefa():
        try:
            _enviar_agora(assunto, corpo)
        except Exception:
            traceback.print_exc()

    if esperar:
        tarefa()
        return True
    threading.Thread(target=tarefa, daemon=True, name="aviso-lead").start()
    return True
