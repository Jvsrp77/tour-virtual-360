# Captura

Como fotografar para o resultado prestar, as formas de criar um ambiente,
captura em fileiras e correção de cenas antigas.

Volta para o [README](../README.md).

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

## Celular

O painel funciona no telefone: abaixo de 1000px vira coluna única, com o visualizador
no topo. Isso importa porque a captura acontece com o celular na mão — em três colunas
fixas, a coluna de "Gerar profundidade" ficava fora da tela.

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

## Marca e descrição

O painel aceita a logo da imobiliária (PNG, JPG, WEBP ou SVG) e um texto de descrição.
Os dois aparecem no cartão do tour. A logo também é empacotada no ZIP.
