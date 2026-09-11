# -*- coding: utf-8 -*-
"""
Fila de processamento pesado.

Costura e profundidade levam de 10 a 25 segundos. Enquanto rodavam dentro da
requisicao, o navegador ficava segurando a conexao aberta o tempo todo — numa
rede de celular um proxy pode cortar antes do fim, e o corretor via erro mesmo
com o panorama pronto no servidor.

Aqui a requisicao devolve na hora um numero de tarefa; o trabalho acontece numa
thread separada e o painel pergunta o andamento de tempos em tempos.

Um trabalhador so, de proposito: a costura consome bastante memoria e duas ao
mesmo tempo derrubariam o processo.
"""
import uuid
import queue
import threading
import traceback
from datetime import datetime

_FILA = queue.Queue()
_TAREFAS = {}
_TRAVA = threading.Lock()

LIMITE_HISTORICO = 60          # tarefas antigas somem; o painel so olha as recentes


class Cancelada(Exception):
    pass


def criar(imovel, tipo, titulo):
    tid = uuid.uuid4().hex[:12]
    with _TRAVA:
        _TAREFAS[tid] = {
            "id": tid, "imovel": imovel, "tipo": tipo, "titulo": titulo,
            "estado": "na_fila", "progresso": 0, "etapa": "aguardando a vez",
            "erro": None, "resultado": None,
            "criado_em": datetime.now().isoformat(timespec="seconds"),
        }
        _limpar()
    return tid


def _limpar():
    """Chamado com a trava tomada."""
    if len(_TAREFAS) <= LIMITE_HISTORICO:
        return
    encerradas = [t for t in _TAREFAS.values() if t["estado"] in ("pronto", "erro")]
    encerradas.sort(key=lambda t: t["criado_em"])
    for t in encerradas[:len(_TAREFAS) - LIMITE_HISTORICO]:
        _TAREFAS.pop(t["id"], None)


def atualizar(tid, **campos):
    with _TRAVA:
        tarefa = _TAREFAS.get(tid)
        if tarefa:
            tarefa.update(campos)


def obter(tid):
    with _TRAVA:
        tarefa = _TAREFAS.get(tid)
        if not tarefa:
            return None
        copia = dict(tarefa)
    if copia["estado"] == "na_fila":
        copia["posicao"] = _posicao_na_fila(tid)
    return copia


def _posicao_na_fila(tid):
    with _TRAVA:
        pendentes = [t for t in _TAREFAS.values() if t["estado"] == "na_fila"]
    pendentes.sort(key=lambda t: t["criado_em"])
    for i, t in enumerate(pendentes):
        if t["id"] == tid:
            return i + 1
    return 1


def listar(imovel):
    with _TRAVA:
        itens = [dict(t) for t in _TAREFAS.values() if t["imovel"] == imovel]
    itens.sort(key=lambda t: t["criado_em"], reverse=True)
    return itens


def enfileirar(tid, funcao):
    """
    funcao recebe um relator: relatar(progresso, etapa) para contar o andamento.
    O que ela devolver vira o resultado da tarefa.
    """
    _FILA.put((tid, funcao))


def _trabalhador():
    while True:
        tid, funcao = _FILA.get()
        tarefa = obter(tid)
        if not tarefa:
            _FILA.task_done()
            continue

        atualizar(tid, estado="processando", progresso=5, etapa="começando")

        def relatar(progresso, etapa):
            atualizar(tid, progresso=int(progresso), etapa=etapa)

        try:
            resultado = funcao(relatar)
            atualizar(tid, estado="pronto", progresso=100,
                      etapa="concluído", resultado=resultado)
        except Exception as e:
            traceback.print_exc()
            atualizar(tid, estado="erro", erro=str(e), etapa="falhou")
        finally:
            _FILA.task_done()


def iniciar():
    t = threading.Thread(target=_trabalhador, daemon=True, name="processamento")
    t.start()
    return t
