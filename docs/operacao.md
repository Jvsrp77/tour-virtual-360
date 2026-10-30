# Operação

Pôr no ar e manter: produção, HTTPS, contas, backup, fila de processamento e
tratamento dos contatos recebidos.

Volta para o [README](../README.md).

## Produção

O `app.run()` do Flask é o servidor de desenvolvimento — o próprio Flask avisa para não
usar em produção. Quem atende agora é o **waitress**: WSGI de verdade, em Python puro,
que roda igual no Windows e no Linux (o gunicorn não roda no Windows).

```bash
python servidor.py            # local, porta 8000
docker compose up -d          # produção, com HTTPS pelo Caddy
```

### Um processo, várias threads — e isso é requisito, não preferência

| Estado | Onde vive | O que quebra com 2 processos |
|---|---|---|
| `_TRAVAS` | `app.py` | `threading.RLock` só serializa dentro do processo: duas requisições leem o mesmo `tour.json` e a segunda apaga o que a primeira gravou |
| `_TAREFAS` | `tarefas.py` | a costura seria enfileirada num processo e consultada no outro — o painel esperaria por uma tarefa que nunca aparece |

Escalar além de uma máquina exigiria trocar as travas por algo compartilhado (Redis,
banco) e a fila por um worker separado. Até lá, o caminho de crescimento é **mais thread e
mais CPU, não mais processo**.

### A armadilha que quase passou

As migrações rodavam dentro do `if __name__ == "__main__"` — bloco que um servidor WSGI
**não executa**, porque ele importa o módulo em vez de rodá-lo. Em produção, miniaturas,
esboços e a adoção de imóveis sem dono simplesmente não aconteceriam, sem erro nenhum.
Agora estão em `inicializar()`, chamada pelos dois caminhos.

### HTTPS

O Caddy na frente resolve o certificado sozinho e repassa ao app. Não é enfeite: a sessão
do painel dá acesso aos contatos capturados, e sem TLS o cookie viaja em texto claro.
Com `TOUR_ATRAS_DE_PROXY=1` o app marca o cookie como seguro e passa a registrar o IP real
do visitante em vez do IP do proxy.

Os timeouts do proxy e do waitress vão a 900 s de propósito: uma costura de 30 fotos leva
minutos, e o padrão de 120 s cortaria o envio no meio.

Marcar o cookie como seguro não basta: quem abrir o link em `http://` manda a senha do
corretor legível **antes** de qualquer cookie existir. Com `TOUR_EXIGIR_HTTPS=1` o app
deixa de atender em claro — desvia as páginas para `https` e **recusa** os envios em vez
de desviá-los, porque desviar um POST faria o navegador reenviar a senha que já viajou.

Ele nasce desligado de propósito: ligado sem HTTPS de verdade na frente, desviaria para um
endereço que não responde e tiraria o site do ar. Duas exceções ficam de fora do desvio, e
não são detalhe: `/saude` e as chamadas de `127.0.0.1` — é por ali que o vigia confere se o
site está vivo, e desviá-las poria o servidor em ciclo de reinício.

### Aviso de contato

Sem isto o contato é gravado e ninguém fica sabendo: o corretor só descobre se abrir o
painel. Para quem vende imóvel, contato que espera um dia é contato perdido.

O telefone vai no **assunto** do e-mail de propósito — o corretor lê a notificação no
celular, na rua, e precisa poder ligar sem abrir nada.

| Variável | Para quê |
|---|---|
| `TOUR_SMTP_SERVIDOR` | `smtp.gmail.com`, por exemplo |
| `TOUR_SMTP_PORTA` | `587` (STARTTLS) ou `465` (SSL direto) |
| `TOUR_SMTP_USUARIO` | a conta que envia |
| `TOUR_SMTP_SENHA` | senha **de aplicativo**, nunca a senha da conta |
| `TOUR_AVISO_PARA` | quem recebe o aviso, separado por vírgula |

Sem `TOUR_SMTP_SERVIDOR` e `TOUR_AVISO_PARA` nada é enviado e nada quebra — é o estado em
que o site nasce. A senha fica em variável de ambiente e nunca no `tour.json`, que vai
inteiro para o navegador de qualquer visitante.

O aviso roda **depois** de o contato já estar gravado, em outra thread e dentro de um
`try`: servidor de e-mail fora do ar não pode custar um lead.

### Aplicar uma publicação

Copiar os arquivos é a parte fácil: o processo em execução segue na memória com
o código antigo. O painel mostra o botão **Recarregar servidor** quando há versão
publicada esperando — e só quando há vigia para repor.

O processo simplesmente sai; quem o traz de volta é o `servico.py`, em segundos,
já lendo os arquivos novos. Por isso a rota **se recusa a agir sem vigia**: ali,
sair deixaria o site fora do ar até alguém ir até a máquina. Um botão que derruba
o site sem volta é pior que botão nenhum.

O vigia marca o processo que supervisiona com `TOUR_VIGIADO=1`. É essa marca que
liga as duas pontas — sem ela o site não teria como saber que há quem o reponha,
e o botão ficaria escondido para sempre.

### Senha esquecida

Não existe recuperação pela web, e não pode existir: redefinir sem a senha antiga por uma
rota seria tomada de conta. Quem opera o servidor resolve na linha de comando, onde a
autorização é o acesso ao disco:

```
python conta.py redefinir <usuario>
```

### Tentativas de login

Depois de 8 erros o endereço fica 5 minutos de fora, e nesse período nem a senha certa
entra — senão o robô acerta na nona tentativa e a trava não serviu de nada. A contagem é
por origem, não por usuário: travar por usuário deixaria qualquer um trancar o corretor
do lado de fora.

### Volumes

Os modelos (302 MB) e os dados ficam fora da imagem. Assim atualizar o código não reenvia
os modelos, e os tours sobrevivem à troca de versão. Depois de subir, baixe os modelos uma
vez:

```bash
docker compose exec app python baixar_modelo.py
docker compose exec app python baixar_modelo.py --fundo
```

`/saude` responde sem login e diz se os modelos estão instalados — é o que o container e o
proxy consultam.

Verificado sob o waitress: matriz de acesso com 9 verificações em 2 perfis (dona e outra
imobiliária), 0 falhas; e uma tarefa de fila completa — upload de 360, importação e
profundidade — sem erro.

## Backup

São 42 MB numa pasta: tours, panoramas, mapas de profundidade, contas e os contatos
capturados. Um disco que falha levava tudo, e **não havia de onde refazer** — as fotos
originais são apagadas depois que a cena é montada, e profundidade e camada de fundo
custam minutos de CPU cada.

```bash
python backup.py criar
python backup.py listar
python backup.py restaurar tour-2026-09-14-1520.zip
```

Em produção roda sozinho, uma vez por dia, guardando as 7 cópias mais recentes
(`TOUR_BACKUP_HORAS`, `TOUR_BACKUPS_GUARDAR`). Backup que depende de alguém lembrar de
rodar não é backup.

**Monte `backups/` num disco separado.** Cópia no mesmo disco dos dados não protege contra
o caso que mais importa: o disco falhar.

### Consistência sem travar o servidor

O backup roda fora do processo do servidor, então não pega as travas dele — e não precisa.
O `tour.json` é gravado com `os.replace`, que troca o arquivo inteiro de uma vez: quem lê
pega a versão antiga ou a nova, nunca um meio-termo. As imagens são escritas uma vez e
nunca alteradas.

O caso que sobra é uma cena criada **no meio** da cópia: o `tour.json` pode entrar sem ela,
ou a imagem entrar sem constar no `tour.json`. Nenhum dos dois corrompe nada — no pior caso
a cena não aparece, e o próprio servidor limpa arquivos órfãos no arranque.

O ZIP só vira backup quando está inteiro: grava como `.parcial` e renomeia no fim. Uma
queda de energia no meio deixa lixo, não uma cópia falsa que parece boa.

### A restauração foi testada, não só escrita

Backup que nunca foi restaurado é esperança, não cópia de segurança. O teste, num sandbox:
copiar os dados, fazer o backup, **apagar tudo**, restaurar e comparar SHA-256 arquivo por
arquivo.

| | |
|---|---|
| Arquivos no original | 9 |
| Restaurados | 9 |
| Faltando / diferentes / sobrando | nenhum |

Restaurar também não é caminho sem volta: o `data/` atual é movido para
`data-antes-de-restaurar-<data>` antes de ser substituído, para o caso de alguém restaurar
a cópia errada.

## Contas: uma por imobiliária

O painel estava aberto: qualquer pessoa com a URL editava imóveis, apagava ambientes e
lia os contatos capturados. Agora cada imobiliária tem a própria conta e enxerga apenas
os próprios imóveis.

**O tour publicado continua aberto** — é o produto. Ficam públicos o tour, o modo de
caminhada, as imagens das cenas, o registro de visita e o envio de lead. Ficam protegidos
a lista, o painel, as métricas, a exportação e toda escrita.

**Não existe cadastro aberto.** A primeira conta nasce no primeiro acesso a `/entrar`; as
demais saem do `conta.py`, na mão de quem opera o servidor. Num produto vendido a
imobiliárias, uma tela pública de "criar conta" só serviria para um estranho abrir conta
no servidor do cliente.

```bash
python conta.py criar imobiliaria2 "Nome da Imobiliária"
python conta.py listar
```

O imóvel guarda o `id` da conta, não o nome de login — trocar o nome no futuro não orfana
o acervo. Imóvel sem dono (o acervo criado antes das contas) é adotado pela primeira conta.

### O furo que o teste encontrou

A matriz de acesso passou em tudo, menos numa linha: **a conta B apagou o imóvel da conta
A**. `DELETE /api/imoveis/<id>` está registrada no `app`, não no Blueprint — então escapou
da checagem de posse que o `before_request` do Blueprint faz.

É a mesma armadilha que o commit da autenticação anterior já documentava, em outra direção:
rotas do `app` e rotas do Blueprint não se comportam igual, e é fácil proteger um grupo
achando que protegeu os dois. A checagem agora está dentro da própria rota.

Matriz final: 20 verificações, 3 perfis (visitante, dona, outra imobiliária), 0 falhas.

## O contato sai do arquivo

Antes o lead caía no `tour.json` e ficava lá: para vê-lo era preciso abrir o painel e
clicar num botão. Sem responder, sem marcar o que já foi atendido, sem exportar e sem
excluir. Com 40 leads isso deixa de ser viável — é onde o sistema perde para uma planilha.

| | |
|---|---|
| **Responder** | botão WhatsApp com a mensagem já escrita, citando o nome e o imóvel |
| **Atendido** | marca e reabre; o filtro mostra só os pendentes, com a contagem |
| **Exportar** | CSV para o CRM da imobiliária |
| **Excluir** | apaga o dado pessoal em definitivo |
| **Consentimento** | o visitante autoriza, e o texto aceito fica gravado |

**Por que WhatsApp e não e-mail:** o link `wa.me` não precisa de servidor de e-mail,
credencial nem configuração — funciona no dia em que você instala. E-mail exigiria SMTP,
que é uma decisão de infraestrutura sua.

**Por que o CSV usa ponto e vírgula e leva BOM:** o Excel em português abre CSV com
vírgula tudo numa coluna só, e sem o BOM ele estraga os acentos. São dois detalhes que
decidem se o arquivo é usável pelo corretor ou não.

**Por que guardar o texto do consentimento, e não só que houve:** a LGPD trata do que o
titular consentiu, e esse texto muda com o tempo. Guardar só um `true` não diz a quê a
pessoa concordou. Excluir também não é conveniência: é o direito de eliminação.

### O painel quebrou inteiro, e quase passou — e agora tem teste

Ao inserir esse código, um `

` virou quebra de linha literal dentro de uma string
JavaScript. String não terminada, erro de sintaxe, **e o painel inteiro parou de
funcionar** — não só o diálogo de contatos.

Os testes não pegaram: eles exercitam a API, não o JavaScript da página. Só apareceu
porque fui abrir a tela para conferir.

**Esse buraco foi fechado.** O `TestPaginas` extrai cada bloco `<script>` das páginas e
manda o próprio **Node** conferir a sintaxe, e checa que todo `onclick` do HTML aponta
para uma função que existe. As duas mutações correspondentes acusam.

Por que Node e não um verificador em Python: um scanner caseiro tropeçaria na primeira
expressão regular com aspas dentro — e o painel tem uma, `/[&<>"']/g`. Se o Node não
estiver instalado, o teste avisa que pulou em vez de fingir que passou.

## Leads ficam fora do tour público

`GET /api/imoveis/<id>/tour` alimenta o visualizador, que é público por natureza — é o
link que o corretor manda ao cliente. Essa rota **nunca** devolve `leads_capturados` nem
`visitas`.

Antes devolvia o tour inteiro: qualquer pessoa com o link lia nome, telefone e e-mail de
todos os contatos capturados. O painel busca esses dados em `/leads` e `/metricas`.

Não há login por enquanto: quem alcança a porta 5000 edita qualquer imóvel. Enquanto o
servidor roda só na máquina de vocês, tudo bem; no dia que subir para uma imobiliária
acessar, autenticação volta a ser o primeiro item.

## Fila de processamento

Costura e profundidade levam de 10 a 25 segundos. Enquanto rodavam dentro da requisição,
o navegador segurava a conexão aberta o tempo todo — numa rede de celular um proxy corta
antes do fim, e o corretor via erro **com o panorama já pronto no servidor**.

Agora a requisição devolve um número de tarefa em ~0,3 s e o painel pergunta o andamento
a cada segundo, mostrando a etapa real: *lendo 16 fotos → alinhando e costurando →
acabamento das bordas → gravando*.

**Um trabalhador só, de propósito.** A costura consome bastante memória; duas ao mesmo
tempo derrubariam o processo. Quando há duas na fila, a segunda mostra a posição em vez
de competir por memória.

Limitação conhecida: as tarefas vivem na memória do processo. Reiniciar o servidor no
meio de uma costura perde aquele trabalho — as fotos originais continuam em
`data/uploads/`, mas é preciso reenviar.

## Métricas de visita

O tour mede sozinho quanto tempo a visita durou e quanto tempo o visitante passou em
cada ambiente. O botão **Métricas** no painel mostra visitas, tempo típico, conversão
em lead, quantos abriram no celular, quantos usaram o modo caminhar, e o ranking de
ambientes por tempo médio.

Duas decisões que fazem o número valer alguma coisa:

- **A contagem para quando a aba fica escondida.** Um tour aberto e esquecido registraria
  horas de interesse que não existiram.
- **O envio usa `sendBeacon`.** A medição só fecha quando o visitante sai, e um `fetch`
  comum seria cancelado junto com a aba.

Visitas com menos de 3 segundos são descartadas — quem abriu e fechou não é visita.
O histórico guarda as últimas 500; como o armazenamento é um JSON, guardar tudo
cresceria sem limite.

Leads e visitas **não vão no ZIP exportado**: é dado da imobiliária, não do cliente que
recebe o link.

## Use 127.0.0.1, não localhost

No Windows, `localhost` resolve para IPv6 (`::1`) primeiro. O servidor escuta só IPv4,
então cada requisição espera o timeout antes de tentar o endereço certo — medi **2
segundos por chamada**. Navegadores disfarçam isso; scripts e ferramentas, não.

## Exportar e publicar

O botão **Exportar ZIP** gera um pacote com `index.html`, `tour.json`, as imagens e a
biblioteca do visualizador. Suba numa hospedagem qualquer e o tour funciona sem Python.

As páginas montam os endereços a partir do imóvel na URL. No ZIP não existe servidor,
então a exportação injeta um bloco de configuração logo após o `<head>` apontando para
os arquivos ao lado. Tem que ser antes de qualquer script: o cabeçalho das páginas lê
essas variáveis na primeira linha.

**Atenção:** o ZIP precisa ser servido por HTTP. Abrir o `index.html` com dois cliques
não funciona — o navegador bloqueia a leitura do `tour.json` via `file://`.
