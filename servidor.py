# -*- coding: utf-8 -*-
"""
Entrada de producao.

O `app.run()` do Flask e o servidor de desenvolvimento: um pedido por vez na
pratica, sem limite de fila, sem timeout, e o proprio Flask avisa para nao usar
em producao. Aqui quem atende e o waitress — WSGI de verdade, em Python puro,
que roda igual no Windows e no Linux (o gunicorn nao roda no Windows).

UM PROCESSO, VARIAS THREADS. Isto nao e preferencia, e requisito:

  - `_TRAVAS` em app.py sao `threading.RLock`, que so serializam dentro do
    mesmo processo. Com dois processos, duas requisicoes leem o mesmo tour.json
    e a segunda apaga o que a primeira gravou — foi assim que 27 de 40 visitas
    se perderam antes das travas existirem.
  - `_TAREFAS` em tarefas.py vive na memoria, e a fila roda numa thread. Num
    segundo processo a costura seria enfileirada num lugar e consultada noutro:
    o painel ficaria esperando por uma tarefa que nunca aparece.

Para escalar alem de uma maquina seria preciso trocar as travas por algo
compartilhado (Redis, banco) e a fila por um worker separado. Enquanto isso, o
caminho de crescimento e mais thread e mais CPU, nao mais processo.
"""
import os
import sys

from waitress import serve

import app as aplicacao


def main():
    porta = int(os.environ.get("TOUR_PORTA", "8000"))
    endereco = os.environ.get("TOUR_ENDERECO", "0.0.0.0")
    # costura e profundidade seguram uma thread por dezenas de segundos; o resto
    # e leve. Sobra folga para o visitante enquanto o corretor processa.
    threads = int(os.environ.get("TOUR_THREADS", "16"))

    aplicacao.inicializar()

    print("")
    print("  Tour Virtual em producao")
    print("  waitress em %s:%d, %d threads, 1 processo" % (endereco, porta, threads))
    if os.environ.get("TOUR_ATRAS_DE_PROXY") == "1":
        print("  atras de proxy reverso: cookie de sessao marcado como seguro")
    else:
        print("  SEM proxy reverso: o cookie de sessao vai sem a marca de seguro.")
        print("  Publique atras de HTTPS e ligue TOUR_ATRAS_DE_PROXY=1.")
    print("")
    sys.stdout.flush()

    serve(aplicacao.app, host=endereco, port=porta, threads=threads,
          # uma costura pode levar minutos; o padrao de 120s derrubaria o envio
          channel_timeout=900,
          ident="tour-virtual")


if __name__ == "__main__":
    main()
