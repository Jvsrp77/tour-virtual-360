# -*- coding: utf-8 -*-
"""
Mantem o servidor de pe.

  python servico.py                     vigia e reinicia enquanto estiver aberto
  python servico.py instalar            sobe quando ALGUEM entra no Windows
  python servico.py instalar servidor   sobe ao LIGAR, sem depender de login
  python servico.py remover             desfaz o agendamento
  python servico.py estado              diz se esta agendado e se esta no ar
  python servico.py espiar "OutraTarefa"  mostra como outra tarefa ja agendada
                                          esta configurada, para copiar o que
                                          comprovadamente funciona na maquina

POR QUE EXISTE. O `servidor.py` sozinho morre com a janela que o abriu, e nao
volta depois que a maquina reinicia. Num anuncio enviado a uma imobiliaria isso
e o site fora do ar sem ninguem perceber — o cliente abre o link e nao carrega.

DUAS FALHAS DIFERENTES. Processo que MORRE o sistema operacional denuncia pelo
codigo de saida. Processo que TRAVA continua vivo, segurando a porta, e nao
responde — e o pior dos dois, porque parece que esta tudo bem. Por isso aqui ha
vigia de saude alem de vigia de processo.

ESPERA CRESCENTE. Se o servidor cai logo depois de subir, reiniciar na hora vira
laco infinito que consome a maquina e enche o disco de log. A espera cresce a
cada queda rapida e volta ao minimo assim que ele se aguenta de pe.
"""
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

RAIZ = os.path.dirname(os.path.abspath(__file__))
PORTA = int(os.environ.get("TOUR_PORTA", "8000"))
SAUDE = "http://127.0.0.1:%d/saude" % PORTA
REGISTRO = os.path.join(RAIZ, "servico.log")
TAREFA = "TourVirtual"

# alvo configuravel para o teste vigiar um processo de mentira, e nao o servidor
COMANDO = os.environ.get("TOUR_COMANDO") or "servidor.py"

ESPERA_MINIMA = 2.0
ESPERA_MAXIMA = 60.0
DE_PE = 30.0          # segundos vivo para a queda contar como "aguentou"
TOLERANCIA_TRAVADO = 3   # checagens de saude falhas seguidas antes de derrubar


def anotar(texto):
    linha = "%s  %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto)
    print(linha, flush=True)
    try:
        with open(REGISTRO, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass                      # log e conveniencia; nao pode derrubar o vigia


def responde(prazo=5.0):
    try:
        with urllib.request.urlopen(SAUDE, timeout=prazo) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _subir():
    return subprocess.Popen([sys.executable, COMANDO], cwd=RAIZ)


def vigiar(limite_de_quedas=None):
    """
    Roda ate ser interrompido. `limite_de_quedas` existe para o teste terminar;
    em uso real fica None e o laco nao acaba.
    """
    espera = ESPERA_MINIMA
    quedas = 0
    while True:
        inicio = time.time()
        proc = _subir()
        anotar("servidor iniciado (pid %d)" % proc.pid)

        falhas_seguidas = 0
        while proc.poll() is None:
            time.sleep(5)
            if proc.poll() is not None:
                break
            if time.time() - inicio < 20:
                continue          # ainda subindo: nao cobrar saude tao cedo
            if responde():
                falhas_seguidas = 0
            else:
                falhas_seguidas += 1
                anotar("nao respondeu (%d de %d)" % (falhas_seguidas, TOLERANCIA_TRAVADO))
                if falhas_seguidas >= TOLERANCIA_TRAVADO:
                    anotar("travado: derrubando para reiniciar")
                    proc.kill()
                    break

        vivo_por = time.time() - inicio
        codigo = proc.poll()
        proc.wait()
        quedas += 1
        anotar("caiu depois de %.0fs (codigo %s)" % (vivo_por, codigo))

        if limite_de_quedas is not None and quedas >= limite_de_quedas:
            return quedas

        # aguentou de pe: a proxima queda merece reinicio rapido de novo
        espera = ESPERA_MINIMA if vivo_por >= DE_PE else min(espera * 2, ESPERA_MAXIMA)
        anotar("reiniciando em %.0fs" % espera)
        time.sleep(espera)


# ------------------------------------------------------- agendamento no Windows

def _schtasks(args):
    return subprocess.run(["schtasks"] + args, capture_output=True, text=True,
                          errors="ignore")


def instalar(modo_servidor=False):
    """
    modo_servidor=False  sobe quando ALGUEM entra no Windows (micro de mesa)
    modo_servidor=True   sobe ao LIGAR a maquina, sem depender de login

    A diferenca importa e ja custou confusao: num servidor de verdade ninguem faz
    login, entao a tarefa "ao entrar no Windows" simplesmente nunca dispara e o
    site nunca sobe. So que rodar sem login exige conta de sistema, que tem mais
    poder do que um servidor web precisa — por isso nao e o padrao.
    """
    if os.name != "nt":
        print("  o agendamento automático só vale no Windows.")
        return 1
    alvo = '"%s" "%s"' % (sys.executable, os.path.join(RAIZ, "servico.py"))
    if modo_servidor:
        args = ["/Create", "/TN", TAREFA, "/TR", alvo, "/SC", "ONSTART",
                "/RU", "SYSTEM", "/RL", "HIGHEST", "/F"]
    else:
        args = ["/Create", "/TN", TAREFA, "/TR", alvo, "/SC", "ONLOGON",
                "/RL", "LIMITED", "/F"]
    r = _schtasks(args)
    if r.returncode != 0:
        saida = (r.stderr or r.stdout).strip()
        print("  não consegui agendar:\n%s" % saida)
        if "negad" in saida.lower() or "denied" in saida.lower():
            print("  abra o PowerShell como administrador e repita.")
        return 1
    if modo_servidor:
        print("  agendado: sobe ao LIGAR a máquina, sem precisar de login.")
        print("  roda como SYSTEM — confira se ele enxerga a pasta de dados.")
    else:
        print("  agendado: o servidor sobe quando você entrar no Windows.")
    print("  para começar agora sem reiniciar:  python servico.py")
    return 0


def espiar(nome_tarefa):
    """
    Mostra como OUTRA tarefa ja agendada esta configurada.

    Serve para copiar o que comprovadamente funciona naquele servidor em vez de
    adivinhar: se a rotina do Olist roda todo dia la, ela ja resolveu a questao
    de login, conta e privilegio.
    """
    r = _schtasks(["/Query", "/TN", nome_tarefa, "/V", "/FO", "LIST"])
    if r.returncode != 0:
        print("  não encontrei a tarefa %r." % nome_tarefa)
        print("  para listar todas:  schtasks /Query /FO TABLE")
        return 1
    interessa = ("Executar como", "Run As", "Agendar Tipo", "Schedule Type",
                 "Tarefa a ser", "Task To Run", "Status", "Iniciar em", "Start In")
    for linha in r.stdout.splitlines():
        if any(linha.strip().startswith(p) for p in interessa):
            print("  " + linha.strip())
    return 0


def remover():
    r = _schtasks(["/Delete", "/TN", TAREFA, "/F"])
    print("  agendamento removido." if r.returncode == 0
          else "  não havia agendamento.")
    return 0


def estado():
    r = _schtasks(["/Query", "/TN", TAREFA])
    print("  agendado para subir no login: %s" % ("sim" if r.returncode == 0 else "não"))
    print("  respondendo agora em %s: %s" % (SAUDE, "sim" if responde() else "não"))
    return 0


def main():
    comando = sys.argv[1] if len(sys.argv) > 1 else "vigiar"
    if comando == "instalar":
        return instalar(modo_servidor="servidor" in sys.argv)
    if comando == "remover":
        return remover()
    if comando == "estado":
        return estado()
    if comando == "espiar":
        return espiar(sys.argv[2] if len(sys.argv) > 2 else TAREFA)
    anotar("vigia iniciado; Ctrl+C encerra")
    try:
        vigiar()
    except KeyboardInterrupt:
        anotar("vigia encerrado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
