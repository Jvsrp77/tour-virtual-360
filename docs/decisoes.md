# Decisões de engenharia

As decisões técnicas do projeto e os números que as sustentam. Cada seção
registra o que foi medido, o que foi escolhido e — quando foi o caso — o que
foi testado e recusado.

Volta para o [README](../README.md).

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

## Alinhamento estável, e a resolução que ele destravou

A mesma captura dava panoramas diferentes a cada tentativa. Medido com 34 fotos a
1600 px, cinco execuções:

```
8269x4084 | recusado | 6645x2904 | recusado | 8123x3321     4 resultados distintos
```

Causa: o alinhamento do OpenCV usa RANSAC, que sorteia. `cv2.setRNGSeed()` antes de cada
tentativa levou a **5 de 5 idênticos**, com custo zero.

Rodar com uma thread só também daria determinismo, e foi testado: **5 de 5 recusados**.
Seria trocar "imprevisivelmente bom" por "previsivelmente ruim".

### A lógica da resolução estava invertida

`_largura_trabalho` reduzia a resolução conforme o número de fotos crescia — quem
capturava melhor era punido com menos nitidez. Com 34 fotos de iPhone o software usava
1000 px de 3024 disponíveis: **11% dos pixels que a câmera capturou**.

Agora é uma escada que começa alto e cai se o alinhamento não convergir. A queda não é
luxo: o comportamento do OpenCV **não é monotônico na resolução** — 1600 aprovou, 2000 foi
recusado por deformação, 2400 aprovou com o melhor preenchimento de todos (0,917).

### Dois defeitos que a resolução maior revelou

**A volta deixou de fechar.** A 2400 px o ajuste de feixe devolve uma focal fora da
realidade, a estimativa cai para não-confiável, e o código recorria à **proporção da
imagem** — critério que o próprio `_geometria` já documentava como errado para captura em
fileiras, porque fileiras aumentam a altura. O panorama saiu 8000×3729 (proporção 2,15),
a regra exigia 2,6, e a cena perdia esfera completa, teto refeito e caminhada.

Conserto: julgar pelos **ângulos de giro**, que vêm das matrizes de rotação e não passam
pela focal. Só a comparação antiga dependia dela.

**Uma mancha preta no meio da imagem.** O buraco interior foi de 0,43% (a 1000 px) para
**2,11%** (a 2400 px). A extensão de bordas não o cobria: ele tem conteúdo válido dos dois
lados. Tapado com `cv2.inpaint` — e vale notar que é o mesmo `cv2.inpaint` **rejeitado**
para tirar móvel da frente da parede. Lá a área é grande e ele vira borrão; aqui são
buracos pequenos cercados de textura, que é para o que ele foi feito.

### Resultado, nas 34 fotos do quarto

| | Antes | Agora |
|---|---|---|
| Repetibilidade (5 execuções) | 4 resultados | **1** |
| Volta fechada | False | **True** |
| Resolução angular | 12,0 px/grau | **22,2 px/grau** |
| Buraco interior | 2,11% | **0,01%** |
| Tempo | 23 s | 76 s |

O tempo triplicou, e isso é aceitável: a costura roda na fila, em segundo plano.

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

## A gravação que falhava no Windows

Ao rodar a suíte inteira, 1 de 40 contatos simultâneos se perdia — e só na suíte
completa, nunca no teste isolado. A instrumentação mostrou a causa:

```
PermissionError [WinError 5]: tour.json.tmp -> tour.json
```

No Windows, `MoveFileEx` **recusa a troca enquanto o destino tiver um handle aberto**. As
escritas eram serializadas pela trava, mas as leituras não — de propósito, para o visitante
não esperar. Bastava um GET com o arquivo aberto no instante da troca. No Linux isso não
acontece: lá o rename é atômico mesmo com leitores.

**O conserto foi mover a trava para a camada de dados**: `carregar_tour` e `salvar_tour`
pegam a trava do imóvel. Assim nenhuma thread nossa tem o arquivo aberto na hora da troca.
Custa pouco — ler é questão de microssegundos, e as rotas pesadas continuam fora da trava.

### O teste era fraco, e por isso quase passou

O defeito aparecia em 1 execução a cada 3. O teste tinha só escritores; **quem provoca o
erro é o leitor**. Agora ele roda 4 visitantes lendo o tour sem parar enquanto os 40
contatos chegam. Com isso o defeito virou determinístico: sem a trava na leitura, 38 a 40
dos 40 se perdem, em 3 de 3 execuções.

Fica a lição: o teste existia e passava, mas não reproduzia a condição real. Teste de
concorrência sem a outra ponta da concorrência é teste de nada.

### O retry ficou, mas não é o conserto

Havia também um retry no `os.replace`. Depois da trava, medi: **a suíte passa sem ele**.
Ele ficou para os handles que não são nossos — antivírus varrendo o arquivo recém-escrito,
indexador do Windows, ferramenta de backup. Nenhum teste aqui produz isso, então está no
código como precaução declarada, não como conserto medido.

## A emenda serrilhada do teto

Olhando para cima aparecia um degrau em ziguezague na junta do teto com a parede — bem
visível no modo de caminhada.

A causa não era o preenchimento, era a **volta**. O teto é reconstruído numa projeção
azimutal de 640×640, e o resultado era misturado de volta sobre a **calota inteira** de
70°, não apenas onde houve preenchimento. A 60° do polo esse disco tem 4,8 px por grau
contra 14 do equirretangular: subamostragem de 3×. Pixel bom estava sendo trocado por
pixel borrado, e a fronteira disso virava o serrilhado.

Agora só volta o que foi preenchido: o peso do preenchimento viaja pelo mesmo `remap` da
imagem e vira a máscara da mistura.

| Alteração média fora do buraco | |
|---|---|
| Antes | 1,93 níveis |
| Agora | **0,10 níveis** |

Ou seja: fora da região sem foto, o panorama fica intacto.

### E a tampa do chão baixou de 50° para 36°

Pelo mesmo erro de método que já tinha me pegado: escolhi 50° porque a energia de cunha
caía 71% contra 21%. Mas essa métrica mede **quanto do anel foi coberto**, não se o
artefato saiu sem comer conteúdo — e na tela 50° apagava o piso e a base da cama.

É a segunda vez que essa métrica engana neste mesmo problema. Fica o registro: no polo, a
imagem manda na métrica.

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

## Testes

```bash
python testes.py        # 19 testes, ~8 s
python mutacoes.py      # confere se os testes não estão cegos
```

Rodam numa pasta descartável (`TOUR_DADOS`), nunca sobre os dados reais, e usam o cliente
de teste do Flask — não precisam de servidor no ar.

**Cada teste existe porque o defeito correspondente aconteceu de verdade** durante o
desenvolvimento, e só foi pego por verificação manual:

| Teste | Defeito que ele guarda |
|---|---|
| `TestAcesso` | a conta B apagava o imóvel da conta A pelo `DELETE` registrado no `app` |
| `TestAcesso` | o tour público devolvia `leads_capturados` a qualquer um com o link |
| `TestConcorrencia` | 27 de 40 escritas simultâneas se perdiam antes das travas |
| `TestCobertura` | foto 3:1 espalhada pela volta inteira, esticando a cena 1,8 vez |
| `TestForaDoContexto` | `montar_cena` quebrava na thread da fila aos 92% da costura |
| `TestSerializavel` | `ndarray` no `json.dump` estourava depois do trabalho pesado |
| `TestBackup` | restauração comparada por SHA-256, arquivo por arquivo |
| `TestContas` | senha em texto, senha curta, cadastro aberto |

### Os testes foram testados

Teste que passa em código quebrado é pior do que teste nenhum: dá confiança sem dar
proteção. O `mutacoes.py` quebra cada proteção de propósito — uma por vez, no arquivo
real — roda o teste que deveria pegar aquilo, e desfaz a mudança.

```
tira posse do DELETE de imovel     ACUSOU
tira posse da API do imovel        ACUSOU
tira a trava por imovel            ACUSOU
tour publico devolve os leads      ACUSOU
espalha foto parcial em 360        ACUSOU
ndarray vaza para o JSON           ACUSOU
sessao deixa de ser exigida        ACUSOU

7 de 7 mutacoes detectadas
```
