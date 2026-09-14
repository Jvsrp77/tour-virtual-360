# Tour Virtual — protótipo

Software que recebe fotos de um imóvel, costura em panorama 360 e publica um tour
navegável. Roda inteiro na máquina local, sem depender de Kuula, CloudPano ou internet.

**Repositório:** https://github.com/Jvsrp77/tour-virtual-360 *(privado)*

## Clonar

```bash
git clone https://github.com/Jvsrp77/tour-virtual-360.git
```

Os modelos (~240 MB) não vêm no repositório. Depois de clonar, rode
`python baixar_modelo.py` uma vez — sem eles tudo funciona, menos o modo "andar" e o
reconhecimento de ambiente.

## Como rodar

Dê dois cliques em `iniciar.bat`. O navegador abre sozinho no painel.

Manualmente:

```bash
python -m pip install -r requirements.txt
python app.py
```

Abra **http://localhost:5000/imoveis** — é a lista de imóveis, ponto de entrada do sistema.

## Vários imóveis

Cada imóvel é uma pasta isolada em `data/imoveis/<id>/`, com o próprio `tour.json` e as
próprias cenas. Dois imóveis nunca se misturam, e apagar um não toca no outro.

| Endereço | O que é |
|---|---|
| `/imoveis` | Lista, criar e excluir |
| `/painel/<id>` | Editor daquele imóvel |
| `/tour/<id>` | Link público para mandar ao cliente |
| `/andar/<id>` | Modo caminhar |

A API inteira vive sob `/api/imoveis/<id>/...`, num Blueprint do Flask que carrega o
imóvel no próprio caminho — nenhuma rota precisa recebê-lo como parâmetro.

Quem já tinha o formato antigo (um `data/tour.json` só) não perde nada: na primeira
subida o servidor migra sozinho para dentro de `data/imoveis/<id>/`.

## As três formas de criar um ambiente

| Forma | Quando usar | O que acontece |
|---|---|---|
| **Costurar em 360** | Você tirou 8–12 fotos girando no eixo | O servidor alinha e costura numa panorâmica |
| **Importar equirretangular** | Você já tem a foto 360 (câmera 360 ou app) | Sobe direto, sem processar |
| **Panorama do celular** | Você usou o modo Panorama do iPhone/Android | Converte de cilíndrico para equirretangular |
| **Gerar ambiente de teste** | Não tem foto nenhuma | Cria uma cena sintética para demonstrar |

### Sobre o panorama do celular

O modo Panorama do iPhone entrega uma faixa em projeção **cilíndrica**, não esférica:
ali a altura cresce com a tangente da latitude, no equirretangular cresce com a
latitude direta. Carregar do jeito que vem esticaria teto e chão.

O campo vertical não precisa ser informado — sai da própria proporção da imagem,
porque no cilindro `largura/altura = haov / (2·tan(vfov/2))`. Num teste com uma
varredura de 9000x1980 o valor deduzido errou 0,3° contra o real.

Vantagem: uma varredura de 20 segundos substitui as 12 fotos. Desvantagem: o campo
vertical é menor (~69° contra ~81° de uma volta com 12 fotos), então sobra mais teto
e chão para preencher por aproximação.

## Funcionalidades

- Costura automática de fotos em panorama (OpenCV), com 5 configurações tentadas em ordem
- Acabamento: preenche as bordas pretas irregulares e completa a esfera em 2:1, para o
  visitante não ver preto ao olhar para cima ou para baixo
- Validação do resultado: rejeita costura estreita demais ou deformada, em vez de
  entregar um panorama inútil que só daria problema depois de montado o tour
- Detecção de proporção 2:1 e ajuste de cobertura angular
- Setas de navegação entre ambientes (clique no panorama para posicionar)
- Pontos de informação com texto ao passar o mouse
- Vista de abertura configurável por ambiente
- Menu de ambientes com miniaturas
- Dados do imóvel (título, endereço, preço) e cor de destaque
- Captura de lead dentro do tour, com os contatos gravados no servidor
- Giroscópio no celular e tela cheia
- Código de embed para colar no site da imobiliária
- Exportação em ZIP: site estático autocontido

## Andar pelo ambiente

Um panorama comum é uma casca lisa: o visitante gira, mas não se desloca. O botão
**Gerar profundidade** calcula a distância de cada ponto do panorama e transforma a
casca em geometria — aí o deslocamento produz paralaxe de verdade (o que está perto
se move mais que o que está longe).

Como funciona, já que o modelo de profundidade só entende foto em perspectiva:

1. o panorama é recortado em 6 vistas, cobrindo a esfera;
2. cada vista passa pelo modelo (Depth Anything V2 Small, ONNX, ~0,5 s cada);
3. as vistas são alinhadas entre si pelas regiões que se sobrepõem — profundidade
   monocular é relativa, cada vista sai com uma escala própria e sem esse alinhamento
   o resultado fica em degraus;
4. tudo volta para um mapa equirretangular, salvo em PNG com os 16 bits repartidos
   entre os canais R e G (o canvas do navegador só entrega 8 bits por canal).

Total: cerca de 5 segundos por ambiente, em CPU.

## Caminhar pelo imóvel inteiro

Um ponto sozinho dá ~1 metro de deslocamento. Para percorrer a casa toda, o caminho é
o mesmo da Matterport: **vários pontos de captura encadeados**, e não um modelo 3D da
casa inteira.

Fotografe de 2 a 3 posições por cômodo, mais uma em cada corredor e porta — pontos a
cada 1,5 a 2 metros, sempre em linha de visão um do outro. Gere a profundidade de cada
um. Depois, no painel, arraste os pontos na **planta** para as posições reais.

No modo caminhar, o visitante anda livremente e o sistema troca de ponto sozinho ao
se aproximar do vizinho, com transição suave. O minimapa mostra onde ele está e para
onde pode ir.

Três detalhes que fazem isso funcionar:

- **Escala calibrada pelo chão.** Profundidade estimada não tem metro: ela diz o que
  está perto, não quão perto. O piso logo abaixo da câmera fica a ~1,5 m (altura do
  peito), e é por ele que a escala é calibrada — sem isso, o passo não teria tamanho.
- **Colisão pela geometria.** O passo só vale se couber dentro da distância real da
  parede naquela direção. Sem isso a câmera atravessa a parede e passa a ver a cena
  por fora.
- **Só o ponto atual é desenhado.** Cada ponto é uma esfera em volta da câmera; duas
  visíveis ao mesmo tempo se tapam e a tela fica preta pela metade.

**Limites honestos.** Dentro de cada bolha o alcance segue em ~1 metro, e atrás dos
móveis não existe informação nenhuma. A transição entre pontos é suave, mas com pontos
distantes demais (acima de ~3 m) ela volta a parecer teleporte.

Para movimento realmente livre seria reconstrução 3D (Gaussian Splatting), que exige
refotografar **andando** pelo cômodo: fotos tiradas girando no eixo não têm paralaxe
e não permitem triangular profundidade.

O modelo não vem no repositório. Rode uma vez:

```bash
python baixar_modelo.py
```

## Abertura instantânea

O panorama tem 1,3 MB. Em 4G fraco são ~7 s olhando *"Carregando o tour..."* antes de
ver qualquer coisa — e quem procura imóvel no celular não espera 7 s.

Cada cena guarda um **esboço** de ~40 KB: um recorte em perspectiva no enquadramento
exato em que o tour vai abrir. O Pannellum o exibe como pôster enquanto o panorama
vem pela rede.

| Rede | Antes | Agora |
|---|---|---|
| 4G típico (6 Mbps) | 1,8 s | 0,2 s |
| 4G fraco (1,5 Mbps) | 7,1 s | 0,6 s |
| 3G (0,7 Mbps) | 15,3 s | 1,3 s |

91% menos bytes até a primeira imagem, ao custo de 40 KB em disco por ambiente (3% do
panorama).

**Tem de ser perspectiva, não equirretangular reduzido.** O Pannellum desenha o
`preview` como imagem de fundo chapada (`background-size: cover`), não sobre a esfera —
um equirretangular apareceria esmagado. O recorte é refeito sempre que a vista inicial,
a cobertura ou o panorama mudam.

Dois detalhes sem os quais o ganho não aparecia na tela: o overlay de carregamento
cobria o esboço até o panorama inteiro chegar (agora sai assim que o pôster monta, e no
lugar dele fica uma pílula discreta *"carregando em alta definição"*), e a caixa
*"Loading..."* do próprio Pannellum ficava por cima anunciando que não havia nada na
tela — justamente quando já havia.

## Modelo de profundidade maior: testado e recusado

A hipótese era direta: o relevo do modo de caminhada vem do Depth Anything V2 **Small**
(94 MB). Trocar pelo **Base** (389 MB, 4× os parâmetros) deveria dar paralaxe melhor —
e talvez consertar a metragem.

Comparação justa exige calibrar cada modelo separadamente: as constantes de `_raio()`
foram ajustadas à distribuição de disparidade do Small, e aplicá-las ao Base seria
condená-lo de saída. Cada um recebeu sua própria calibração pelo plano do piso.

| | Small (94 MB) | Base (389 MB) |
|---|---|---|
| Processamento | **3,7 s** | 9,1 s |
| Chão fora do nível | **0,36°** | 1,28° |
| Resíduo do plano | 0,1829 | **0,1658** |
| Nitidez de borda | 0,6153 | **0,6451** |
| Malha duvidosa | **2,9%** | 3,6% |
| Dimensões (real 5,26 × 2,58) | 3,99 × 2,28 | 4,35 × 3,43 |

O Base tem uma vantagem real e visível: o Small produz um **artefato** — uma mancha de
objeto fantasma muito perto da câmera, que não existe no cômodo — e no Base ela some.

Mas o veredito é não, por três razões. O ganho **não aparece no produto**: lado a lado,
no mesmo ponto de vista, o modo de caminhada fica indistinguível. O chão fica **menos**
nivelado (0,36° → 1,28°), que é a métrica mais próxima de "a geometria está certa", já
que o panorama foi nivelado e o piso real é horizontal. E a metragem continua errada nos
dois: os 14,9 m² do Base (+10%) saem de erros que se cancelam — 4,35 × 3,43 contra
5,26 × 2,58 é comprimento 17% curto e largura 33% larga, não acerto.

4× o tamanho e 2,5× o tempo por um ganho invisível não se paga. Para repetir o teste:
baixe `onnx-community/depth-anything-v2-base` em `modelos/depth_base.onnx`.

Terceiro modelo grande recusado por medição, junto com o LaMa e o CLIP. O padrão se
repete: neste projeto, modelo maior não tem ganhado de técnica simples bem aplicada.

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

## O chão sob a câmera: três tentativas e o que sobrou

Olhando para baixo aparece um **leque de riscos escuros** — o "degradê preto". Causa: a
captura de uma fileira não alcança o chão sob a câmera, e o preenchimento estica a cor de
cada coluna, o que no polo vira um leque.

Três abordagens testadas, todas medidas pela energia de cunha (34,72 no estado original):

| Abordagem | Resultado | Veredito |
|---|---|---|
| Superfície suave (a do teto, invertida) | −86% | apaga piso, tapete e pé da cama |
| LaMa por máscara de detalhe | −0% | a máscara erra: o leque **tem** gradiente |
| LaMa por raio (38°/45°/52°) | −5% a −15% | troca leque por borrão escuro |
| **Tampa na cor do piso** | **−72%** | **adotada** |

Por que o LaMa falha aqui e ganhou atrás dos móveis: lá o buraco é pequeno e cercado de
estrutura para continuar; aqui é 23–43% do disco, sem nada em volta para copiar. Polo é
caso degenerado para inpainting — a conclusão do teto valia, e vale também para o chão.

A tampa não recupera o piso. Ela troca um artefato por uma superfície lisa da cor certa,
amostrada só na metade mais clara do anel em volta (a mediana crua puxa para cinza,
porque o anel contém sombra e pé de móvel). Sem logo é o que dá para fazer; **com a logo
da imobiliária fica melhor**, e é o que toda foto 360 profissional faz. O botão agora
funciona nos dois casos.

A solução de verdade continua sendo captura em **três fileiras**: aí o chão é real.

## Camada de fundo: reconstruir o que está atrás dos móveis

Caminhando, o visitante enxerga além das bordas do que a foto registrou. Ali não há
dado — a câmera nunca viu. Antes isso virava sombra escura; agora o vão pode ganhar
conteúdo próprio, gerado por IA.

**É conteúdo gerado, não o imóvel.** A cena fica marcada e o visualizador avisa na tela:
*"11,31% reconstruído por IA (atrás dos móveis)"*.

Primeiro a medição que justificou encarar: para andar 1 m, só **2,2%** do campo de visão
precisa ser inventado; 3,3% em 1,5 m. Bem menos que a reconstrução de teto que o projeto
já aceitava (43° da esfera).

### LaMa ganhou — e isso contradiz o teste anterior

| | cv2.inpaint | LaMa (208 MB) |
|---|---|---|
| Caneca sobre a mesa | vira cone borrado | removida limpa |
| Violão na parede | desfigurado | reconstruído coerente |
| Quina da mesa, piso | esborrachados | preservados |

O mesmo LaMa **havia perdido** para a técnica clássica no teto (37,3 contra 2,58). A
diferença é o caso: teto é polo, superfície lisa, sem estrutura a preservar — degenerado.
Remover objeto de cena estruturada é exatamente o que o modelo aprendeu a fazer.

Lição: aquela rejeição era específica do caso, não veredito sobre o modelo. Vale reabrir
uma conclusão quando o problema muda de natureza.

### Dois defeitos que só a tela revelou

**A camada gerada nascia na frente da real.** O desfoque na profundidade do fundo puxava
valores para perto. Invariante aplicada: `raio_fundo = max(raio_fundo, raio)` — o fundo
nunca está mais perto do que a foto viu.

**E ainda assim cobria a cena inteira.** Pintei a camada de vermelho para diagnosticar: a
tela ficou toda vermelha. Medindo vértice a vértice, **71,4% do fundo estava à frente**. A
causa era o slider "Profundidade do relevo": em 70% ele comprime a malha real em direção
ao raio médio, enquanto o fundo usava o raio cru — duas regras diferentes, camadas
entrelaçadas. Agora as duas passam pela mesma mistura; como ela é monótona no raio, a
invariante sobrevive. Resultado: 0,0% à frente.

Custo: ~3 min de processamento na fila, 200 KB de textura e 650 KB de profundidade por
ambiente, só carregados no modo de caminhada. O modelo é opcional:
`python baixar_modelo.py --fundo`.

## O borrão ao caminhar: o que dá e o que não dá

Andando pelo ambiente, algumas regiões esticam num borrão — tipicamente o chão atrás de
um móvel, ou o vão sob a mesa.

**A causa não tem conserto por reprocessamento.** É oclusão: a foto foi tirada de um
ponto só, e o que estava escondido atrás da mesa nunca foi registrado. A malha liga a
borda da mesa à parede do fundo com um triângulo, e ao caminhar esse triângulo estica.
Não existe algoritmo que recupere pixels que a câmera não viu — só outra foto, de outro
ponto, veria ali.

**O que dá para fazer é parar de fingir.** Um triângulo cujos vértices têm raios muito
diferentes (salto acima de 18% do menor) não é superfície do cômodo: é o vão. Esses
triângulos vão para um segundo grupo da malha, com material próprio.

Por que não simplesmente apagá-los: **parado no ponto de captura a imagem é perfeita.**
Ali esses triângulos estão de perfil, escondidos atrás das próprias superfícies. Apagá-los
abre buracos numa vista que não tinha defeito nenhum — testei, e fica pior. O borrão
nasce só quando a câmera sai do ponto.

Então eles escurecem conforme você se afasta: intactos na origem, sombra a 1,6 m. E
escurecem em vez de sumir, porque um furo na esfera deixaria ver a parede oposta através
dele. No quarto de teste são 2,6% da malha, e o painel informa isso em vez de deixar a
sombra sem explicação.

**A solução de verdade é capturar de mais pontos.** O que um ponto não viu, o vizinho vê,
e o sistema já encadeia pontos. Um cômodo com móvel no meio pede dois ou três.

## Corrigir cenas antigas

O pipeline ganhou nivelamento e reconstrução de teto no meio do caminho. Cenas montadas
antes disso ficaram com o horizonte torto e com o **leque de cunhas** no teto — riscos
escuros que convergem no zênite, muito visíveis no modo de caminhada, onde a textura
esticada vira geometria quebrada. As fotos originais já foram apagadas, mas as duas
correções trabalham sobre o equirretangular pronto.

Botão **Endireitar e refazer o teto** no painel. No quarto de teste:

| | Antes | Depois |
|---|---|---|
| Energia de cunha no teto | 22,79 | 6,45 (−72%) |
| Horizonte fora do prumo | 4,86° | 0,82° |
| Chão fora do nível (aferição independente) | 3,29° | 1,88° |

A última linha é a verificação que importa: medir o nivelamento com o próprio detector de
verticais é circular, então o prumo foi conferido ajustando um plano aos pontos de chão do
mapa de profundidade — um caminho que não compartilha nada com o detector.

Refaz a profundidade junto, porque endireitar gira o panorama e o mapa antigo passaria a
apontar para as direções erradas.

### Todo caminho de entrada recebe o mesmo tratamento

A costura já aplicava exposição, nivelamento e teto. Os outros dois não:

| Entrada | Exposição | Nivelamento | Teto |
|---|---|---|---|
| Costura de fotos | sim | sim | sim |
| Varredura | sim | sim | **faltava** |
| Foto 360 pronta | não | **faltava** | **faltava** |

Quem enviava uma foto 360 do modo Panorama do celular não recebia correção nenhuma.
Agora recebe nivelamento e teto — as duas se protegem sozinhas (o nivelamento ignora
desvios abaixo de 0,8° e o teto só age quando falta mais de 4° de foto), então uma
imagem já boa sai intacta. Exposição fica de fora de propósito: o CLAHE é incondicional
e uma foto já tratada pela câmera só teria a perder.

### O chão não recebe a mesma correção

O leque existe igual no polo inferior, e a mesma função aplicada lá derruba a energia de
cunha de 28,46 para 3,93. **Mesmo assim foi rejeitada:** o número melhora e a imagem
piora. O buraco embaixo é maior (55° contra 43°) e ali existe conteúdo real perto da
câmera — a reconstrução apagou o piso, o tapete e o pé da cama, trocando tudo por um
disco liso. Teto branco e liso é o caso fácil; chão texturizado não é.

Para o nadir a resposta continua sendo a marca no chão: cobre a área sem informação com
um logotipo declarado, em vez de inventar piso.

## Metragem

Botão **Medir o ambiente**: estima comprimento, largura e m² a partir do mapa de
profundidade. Aferido contra o LiDAR do iPhone num quarto real.

| | Real (iPhone) | Medido | Erro |
|---|---|---|---|
| Comprimento | 5,26 m | 5,38 m | +2,3% |
| Largura | 2,58 m | 2,59 m | +0,4% |
| Área | 13,57 m² | 13,9 m² | +2,4% |

Cada pixel vira ponto 3D; os que estão a ~1,5 m abaixo da câmera são piso. Para cada
direção o código caminha do chão para fora até o piso acabar, e a um retângulo é ajustado
ao contorno.

**Por que retângulo, e por que percentil alto.** O polígono de piso sozinho mede *piso
livre*, não o cômodo: móvel encostado interrompe o piso antes da parede, e aqui isso deu
7,7 m² — 55% do cômodo. Cômodo é retangular e o móvel só esconde a parede em algumas
direções, então a extensão usa percentil 96: alcança a parede onde ela está visível e
ainda descarta ponto solto de profundidade ruim. Percentil 88 mede o móvel (−37%);
percentil 100 mede o ruído.

O painel mostra os dois números — a metragem e o piso livre.

### Medir e publicar são passos separados

Medir só serve se o número chegar a quem compra. Depois de medir, o painel oferece
**Publicar**: a metragem fica gravada na cena e passa a aparecer no cartão do tour
(`13,9 m² em 1 de 1 ambiente(s)`), embaixo de cada miniatura do menu, e como selo na
lista de imóveis, que soma os ambientes publicados.

A publicação é um passo à parte de propósito. A estimativa tem uns 2% de erro e o
corretor muitas vezes tem o número da matrícula, que vale mais — por isso o campo ao
lado do botão é editável e aceita vírgula decimal. Fica gravado se o número foi
`medido` ou `informado`.

O tour nunca extrapola: se só metade dos ambientes tem metragem, ele diz *"em 2 de 5
ambiente(s)"* em vez de anunciar um total que não cobre a casa inteira.

### Um episódio que vale registrar

Esta funcionalidade foi **implementada, descartada e restaurada**. A primeira aferição usou
uma referência de 3,20 × 2,80 m, contra a qual o resultado dava −39% e nenhum ajuste
salvava. Foi removida com um commit explicando por que não funcionava.

A medição correta (LiDAR) era 5,26 × 2,58. Contra ela, o mesmo código acerta as duas
dimensões dentro de 2,3%. **O código estava certo; a referência é que estava errada.**

Fica a lição: uma verificação vale o que vale o padrão de comparação. Antes de concluir
que algo não funciona, confirme contra o que está sendo comparado.

### E uma segunda lição, em sentido contrário

Ao corrigir a cena de teste (nivelamento + teto), a mesma medição caiu de 13,9 para
8,3 m². O nivelamento foi confirmado como **correto** por aferição independente — logo o
frágil é a medição, não a correção.

A causa é `_raio()`: a conversão de disparidade para metros usa constantes fixas
(`1,542` e `0,125`) ajustadas a uma única imagem. A disparidade do modelo é relativa e
sua distribuição muda a cada imagem, então o deslocamento fixo deforma a geometria de
modo não uniforme — o comprimento caiu 30% e a largura só 12%. A calibração atual no
nadir corrige apenas escala, e escala não desfaz deslocamento.

Tentativa de conserto: ajustar os dois coeficientes por imagem, usando o próprio piso
como régua (um plano a 1,5 m obedece `1/raio = sen(lat)/1,5`, o que é linear em
disparidade). Os coeficientes saíram estáveis entre as variantes, mas a área piorou em
todas (−26% a −44%). **Não foi embarcada.**

O padrão que sobra: a largura sai perto do real em toda variante (2,47–2,61 m contra
2,58), o comprimento é que desaba. Faz sentido — a ponta distante do cômodo é vista em
ângulo raso, onde profundidade monocular erra mais.

Conclusão honesta: **os +2,4% valiam para aquela imagem específica.** A medição não está
validada de forma geral, e cena corrigida fica marcada para revisão no painel. Medir
mais cômodos com LiDAR — quadrado, vazio, em L — continua sendo o que falta.

## Reconstrução do teto

O preenchimento padrão estica a cor de cada coluna para cima. No polo isso vira um leque
de cunhas — o defeito mais visível ao olhar para cima, e o que motivou este trabalho.

O teto observado é projetado numa vista azimutal (o polo vira o centro, sem a distorção
do equirretangular), ajusta-se uma superfície suave a ele, e essa superfície é estendida
para dentro do buraco. Só entram no ajuste os pixels mais claros do anel: o anel contém
topo de armário e quina escura, e incluir isso puxava o resultado para um disco cinza
evidente.

Energia de cunha medida no quarto de teste, pelos harmônicos angulares:

| Abordagem | Cunha |
|---|---|
| Preenchimento anterior | 50,8 |
| `cv2.inpaint` (Telea / Navier-Stokes) | ~50 (sem mudança) |
| **LaMa, 198 MB** | **37,3** |
| **Extrapolação da superfície** | **2,6** |

**A técnica simples ganhou do modelo de IA por uma margem larga**, e sem 198 MB de
download nem 4 s de inferência. O LaMa foi baixado, testado nos dois modos de preparo e
descartado.

Não é invenção de conteúdo: é a continuação da superfície que a própria foto mostra.
Diferente de gerar piso, que afirmaria algo sobre característica usada na decisão de
compra.

O limite do buraco é medido **na imagem**, varrendo de cima até aparecer detalhe. Deduzir
do campo da lente não funciona: a estimativa de foco do OpenCV saía inflada (115°),
apontando um buraco de 7° quando o real era 44°.

## Marca no chão

Toda foto 360 profissional cobre o ponto exatamente abaixo da câmera: ali fica o tripé,
o pé de quem fotografou, ou — numa captura de uma fileira só — o preenchimento sintético
que não alcança o chão.

Medido no quarto de teste: **cerca de 40% da altura do equirretangular é preenchimento**,
com nitidez praticamente zero nas faixas de topo e base. A marca cobre a parte pior disso
e ainda reforça a marca de quem publicou.

O disco é desenhado direto no equirretangular: cada pixel da faixa de baixo vira
coordenada polar no chão — a distância ao polo vira raio, a longitude vira ângulo. É o
inverso da projeção que o visualizador faz. A borda externa dissolve para não virar um
círculo recortado.

**Não inventa conteúdo.** Substitui área sem informação por um logotipo declarado.
Diferente de gerar piso com IA, que afirmaria algo falso sobre uma característica que o
comprador usa para decidir.

O panorama original fica guardado ao lado (`orig_<arquivo>`), então dá para trocar a logo
ou desfazer sem recosturar as fotos.

## Nivelamento do horizonte

Quem fotografa com o celular na mão quase nunca fica no prumo. Num panorama torto o chão
"escorrega" quando o visitante gira — desconforto físico que aparece acima de uns 2°.
A captura de teste estava **4,9° fora do prumo**.

Como se descobre onde é "para baixo": pelas verticais da própria cena. Batente de porta,
quina de parede e lateral de armário são verticais reais. Cada linha dessas, vista da
câmera, define um plano que passa pelo centro óptico; a direção da gravidade está contida
em todos esses planos ao mesmo tempo. Achar essa direção é achar o prumo — RANSAC sobre
as normais, refinado com os inliers ponderados pelo comprimento.

Resultado medido: 4,86° → **0,59°**, com 76 das 133 linhas concordando, em 0,7 s.
No fluxo completo: 5,2° → 0,29°, conferido relendo o arquivo salvo.

**Por que não pela profundidade.** Também dá para estimar ajustando um plano ao piso do
mapa de profundidade. Testei: deu 19°, contra os 4,9° reais. Profundidade monocular é
relativa e o ajuste saiu com planaridade 0,22 — ruim demais. As verticais são geometria
direta e o resultado se verifica sozinho: mede, corrige, mede de novo.

Só acontece em panorama 360 fechado: a rotação trata a imagem como superfície completa,
e numa faixa parcial o mapeamento seria outro. Abaixo de 0,8° não mexe, para não perder
nitidez reamostrando à toa. Cena sem quinas (parede lisa) é recusada com explicação, e o
panorama segue intacto.

## Correção de exposição

Fotografar cômodo tem um problema constante: janela clara contra parede escura. Medindo
as 16 fotos de um quarto real, o brilho variava de 109,6 a 149,2 entre elas — 40 níveis.

O OpenCV já compensa esse ganho entre fotos, e medi que ele faz bem: o brilho médio do
panorama sai uniforme. O que sobrava era **perda de detalhe nas sombras**: 11% dos pixels
esmagados abaixo de 25, sem informação recuperável.

A correção é **local, não global**. Achatar o brilho do panorama inteiro destruiria a
iluminação real — a parede da janela é mesmo mais clara que o canto. Com CLAHE no canal
de luminância, a sombra esmagada caiu para 7,2% e o estouro ficou igual (0,02% → 0,08%).

Limite 4,0 foi testado e **piorou**: 15,4% de sombra esmagada, por redistribuir demais.
Ficou 2,5 com grade 16x8.

## Miniaturas

As listas mostram o panorama num quadradinho de 109x60 — mas carregavam a imagem de
5807x2903. Num tour de 13 ambientes, **o menu baixava 17 MB antes do visitante clicar em
nada**.

Cada cena passou a ter uma miniatura de 480px (~15 KB). Abrir o tour caiu de 17,2 MB para
1,5 MB, uma redução de 91%. As miniaturas que faltam nos imóveis antigos são geradas na
subida do servidor.

## Limpeza das fotos originais

As fotos enviadas ficam em `data/uploads/` e valem a pena guardar: já foi preciso
recosturar um ambiente com ajustes melhores. Mas nada as apagava — eram **226 MB** de
lotes de costuras que falharam ou de cenas já removidas.

Agora cada cena guarda de qual lote veio. Apagar a cena (ou o imóvel) apaga as originais
junto, e na subida o servidor remove lotes órfãos com mais de 7 dias. O prazo existe
porque um lote recém-criado pode ser de uma costura ainda na fila.

O mesmo vale para `scenes/`: costura recusada no meio, cena substituída ou profundidade
de cena já removida deixavam arquivo para trás. A faxina na subida encontrou 1,9 MB assim
num imóvel com um único ambiente.

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

## Escrita concorrente

Quase toda rota que escreve faz ler-alterar-gravar no `tour.json`. Sem serializar, duas
requisições leem a mesma versão e a segunda apaga o que a primeira gravou. **Num teste
com 40 visitas simultâneas, 27 se perdiam** — e várias devolviam HTTP 500, porque outra
thread lia o arquivo no meio da gravação e encontrava JSON pela metade.

Basta o corretor mandar o link num grupo de WhatsApp para isso acontecer.

Duas correções:

- **Gravação atômica.** Escreve num arquivo temporário e troca com `os.replace`. Quem lê
  sempre pega a versão inteira, velha ou nova — nunca metade.
- **Uma trava por imóvel**, para requisições que escrevem. Leituras seguem em paralelo.

As rotas pesadas (costura, profundidade) **não** seguram a trava enquanto processam, só
no momento de gravar. Segurando o tempo todo, um visitante esperava 10,7 s para registrar
a visita. Depois da correção: 26 ms normalmente, 151 ms no pior caso durante uma costura.

Depois: 120 escritas simultâneas, 120 gravadas, zero erros.

## Use 127.0.0.1, não localhost

No Windows, `localhost` resolve para IPv6 (`::1`) primeiro. O servidor escuta só IPv4,
então cada requisição espera o timeout antes de tentar o endereço certo — medi **2
segundos por chamada**. Navegadores disfarçam isso; scripts e ferramentas, não.

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

## Marca e descrição

O painel aceita a logo da imobiliária (PNG, JPG, WEBP ou SVG) e um texto de descrição.
Os dois aparecem no cartão do tour. A logo também é empacotada no ZIP.

## Celular

O painel funciona no telefone: abaixo de 1000px vira coluna única, com o visualizador
no topo. Isso importa porque a captura acontece com o celular na mão — em três colunas
fixas, a coluna de "Gerar profundidade" ficava fora da tela.

## Exportar e publicar

O botão **Exportar ZIP** gera um pacote com `index.html`, `tour.json`, as imagens e a
biblioteca do visualizador. Suba numa hospedagem qualquer e o tour funciona sem Python.

As páginas montam os endereços a partir do imóvel na URL. No ZIP não existe servidor,
então a exportação injeta um bloco de configuração logo após o `<head>` apontando para
os arquivos ao lado. Tem que ser antes de qualquer script: o cabeçalho das páginas lê
essas variáveis na primeira linha.

**Atenção:** o ZIP precisa ser servido por HTTP. Abrir o `index.html` com dois cliques
não funciona — o navegador bloqueia a leitura do `tour.json` via `file://`.

## Captura em fileiras

Uma volta só (~12 fotos) cobre cerca de 80° na vertical — as paredes ficam reais, mas
teto e chão são preenchidos por aproximação. Três voltas (~30 fotos: nivelado, inclinado
~35° para cima e ~35° para baixo) levam a cobertura vertical para ~150°, com teto e chão
de verdade.

Não existe campo separado para cada fileira: envie todas as fotos juntas. O sistema lê a
orientação que o OpenCV calculou para cada foto e descobre sozinho quantas fileiras você
fez, se a volta fechou e qual o vão sem cobertura. Esse diagnóstico aparece no painel e
define se o panorama vira esfera 2:1 ou fica parcial.

## Guia de captura

O software só entrega um bom 360 se a foto entrar certa. No painel há o botão
**Guia de captura** com o passo a passo. O resumo:

1. Fique parado no centro do cômodo — você gira, não anda.
2. Celular na vertical, altura do peito (~150 cm), nivelado.
3. Foto, gira ~30°, foto. Volta completa: 8 a 12 fotos.
4. Cada foto repete ~30% da anterior.
5. Trave foco e exposição.

Sem sobreposição não existe costura possível — é limitação de física, não do software.

## Estrutura

```
app.py                    servidor Flask e API
stitcher.py               costura OpenCV e diagnóstico de falhas
cena_demo.py              gerador de cena 360 sintética
static/admin.html         painel de administração
static/viewer.html        visualizador público do tour
static/vendor/            Pannellum (visualizador 360, local)
static/imoveis.html       lista de imóveis
data/imoveis/<id>/        um imóvel: tour.json + scenes/
data/uploads/             fotos originais
fotos_exemplo_costura/    6 fotos sobrepostas para testar a costura
```

## Nota técnica: OpenCL desligado de propósito

O `stitcher.py` desliga a aceleração por GPU **antes de importar o cv2**, via variável de
ambiente. Não mexa nisso sem ler o motivo:

O OpenCV usa OpenCL para projetar a esfera. Com muitas fotos isso estoura a memória de
vídeo, e o erro resultante chama o `terminate handler` — derruba o processo Python inteiro,
sem exceção que dê para capturar. Do lado do navegador aparece como "Failed to fetch",
porque o servidor simplesmente sumiu.

`cv2.ocl.setUseOpenCL(False)` **não basta**: a flag é por thread, e o Flask atende cada
requisição numa thread nova, que voltaria a usar a GPU. Só a variável de ambiente resolve
no processo todo.

Além de estável, ficou mais rápido: 15 fotos passaram de 28s para 10s.

## Limitações conhecidas

- A costura roda em CPU e leva de 10 a 25 segundos por ambiente. Em produção isso vira fila.
- Fotos tiradas andando pelo cômodo (em vez de girar no eixo) não costuram.
- Não faz reconstrução 3D — o visitante olha em volta de pontos fixos, não caminha
  livremente. Para isso seria Gaussian Splatting, que exige GPU.
- Os leads ficam num arquivo JSON. Em produção, banco de dados.
- Sem autenticação: qualquer um que alcance a porta 5000 edita o tour.
