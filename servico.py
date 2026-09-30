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
    # Sem console (pythonw) o sys.stdout e None — e ai o print simplesmente NAO
    # FAZ NADA, medido: ele nao estoura. Quem estoura e mexer no stdout direto,
    # tipo sys.stdout.flush(). Por isso aqui nao ha guarda: ela nao protegeria
    # de nada, e guarda decorativa engana quem le.
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
    # A marca diz ao proprio site que HA quem o reponha. Sem ela o botao de
    # recarregar do painel se recusa a agir: derrubar um servidor sem vigia
    # deixaria o site fora do ar ate alguem ir la na maquina.
    ambiente = dict(os.environ, TOUR_VIGIADO="1")
    # Rodando sob pythonw nao ha console, e o servidor.py imprime um cabecalho
    # na subida: sem destino, o print estouraria e o site nem comecaria. A saida
    # vai para arquivo, que de quebra guarda o traceback de uma queda.
    try:
        saida = open(os.path.join(RAIZ, "servidor.log"), "a", encoding="utf-8")
    except OSError:
        saida = subprocess.DEVNULL
    return subprocess.Popen([sys.executable, COMANDO], cwd=RAIZ, env=ambiente,
                            stdout=saida, stderr=subprocess.STDOUT)


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


def interpretador_sem_console():
    """
    pythonw.exe quando existir, senao o python normal.

    Isto e o que faz o vigia SOBREVIVER. Agendado com python.exe, ele ganha um
    console; quando esse console fecha, o Windows manda CTRL_CLOSE_EVENT e o
    processo morre. Medido aqui: a tarefa terminou tres vezes com 0xC000013A,
    que e exatamente esse encerramento. pythonw nao tem console, entao nao ha
    evento de console para mata-lo.
    """
    if os.name != "nt":
        return sys.executable
    candidato = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidato if os.path.exists(candidato) else sys.executable


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
    alvo = '"%s" "%s"' % (interpretador_sem_console(),
                          os.path.join(RAIZ, "servico.py"))
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


def _gravado_mais_recente():
    """
    A data do fonte mais novo do projeto, ou None se nao houver nenhum.

    Extraida de codigo_no_ar para poder ser MEDIDA. O teste que a usa fingia
    um processo de "duas horas atras" e comparava com esta data — entao ele so
    passava se alguem tivesse editado um arquivo nas ultimas duas horas, e
    reprovava sozinho num dia parado. Teste que reprova por calendario ensina
    a ignorar teste vermelho.
    """
    import glob
    fontes = (glob.glob(os.path.join(RAIZ, "*.py"))
              + glob.glob(os.path.join(RAIZ, "static", "*.html")))
    if not fontes:
        return None
    return max(os.path.getmtime(f) for f in fontes)


def codigo_no_ar():
    """
    Diz se o processo que atende agora carregou os arquivos que estao no disco.

    Nasceu de um prejuizo real: os arquivos novos foram copiados, o processo
    velho continuou de pe segurando a porta, e o `estado` respondeu "sim,
    respondendo" durante a publicacao inteira. Perguntar a porta so responde
    "tem alguem ai" — nao responde "e a versao que eu publiquei".

    Devolve (veredito, detalhe). O veredito e None quando nao deu para saber:
    fingir certeza aqui seria repetir o erro de ontem por outro caminho.
    """
    try:
        gravado = _gravado_mais_recente()
    except OSError as e:
        return None, "não consegui ler a data dos arquivos: %s" % e
    if gravado is None:
        return None, "não achei os arquivos do projeto"

    subiu = _inicio_do_servidor()
    if subiu is None:
        return None, "não achei o processo do servidor"
    if subiu >= gravado:
        return True, "processo subiu depois do arquivo mais novo"
    atraso = (gravado - subiu) / 60.0
    return False, ("o processo é %.0f min MAIS VELHO que o arquivo mais novo: "
                   "derrube-o para o vigia repor com o código publicado" % atraso)


def _inicio_do_servidor():
    """Instante em que o servidor.py vigiado comecou, ou None."""
    if os.name != "nt":
        return None
    # O filtro por python nao e detalhe: sem ele a PROPRIA consulta casa, porque
    # a linha de comando dela contem "servidor.py". Achava um processo so — ela
    # mesma, recem-nascida — e o veredito dava "esta no ar" sempre. Check cego e
    # pior que check nenhum: mente com cara de conferencia.
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' "
          "-and $_.CommandLine -like '*%s*' } | ForEach-Object { "
          "(Get-Process -Id $_.ProcessId).StartTime.ToUniversalTime()"
          ".ToString('o') }" % COMANDO)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, errors="ignore")
    except OSError:
        return None
    linhas = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
    if len(linhas) != 1:            # nenhum, ou varios: nao da para afirmar
        return None
    try:
        from datetime import timezone
        texto = linhas[0].replace("Z", "+00:00")
        return datetime.fromisoformat(texto).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None


def modo_do_agendamento(xml):
    """
    Le o modo a partir do XML da tarefa. Nao olha texto traduzido.

    Primeira versao procurava a palavra "SYSTEM" na saida em lista — e o Windows
    daqui responde em portugues, "SISTEMA". O check passou a mentir de um jeito
    novo: dizia "sobe quando alguem entra" numa tarefa que sobe na inicializacao.
    Os nomes das marcas do XML (BootTrigger, LogonTrigger) nao sao traduzidos.
    """
    if not xml:
        return "não está agendado"
    sistema = "S-1-5-18" in xml            # SID da conta de sistema, universal
    if "<BootTrigger" in xml:
        return ("sobe ao LIGAR a máquina, sem depender de login"
                + (", como SISTEMA" if sistema else ""))
    if "<LogonTrigger" in xml:
        return "sobe quando alguém entra no Windows"
    return "agendado, mas não soube dizer quando dispara"


def estado():
    r = _schtasks(["/Query", "/TN", TAREFA, "/XML"])
    xml = (r.stdout or "") if r.returncode == 0 else ""
    print("  agendamento: %s" % modo_do_agendamento(xml))
    print("  respondendo agora em %s: %s" % (SAUDE, "sim" if responde() else "não"))

    veredito, detalhe = codigo_no_ar()
    if veredito is True:
        print("  código publicado está no ar: sim (%s)" % detalhe)
    elif veredito is False:
        print("  código publicado está no ar: NÃO — %s" % detalhe)
    else:
        print("  código publicado está no ar: não deu para saber (%s)" % detalhe)
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
