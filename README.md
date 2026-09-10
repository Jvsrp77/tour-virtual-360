# Tour Virtual — protótipo

Software que recebe fotos de um imóvel, costura em panorama 360 e publica um tour
navegável. Roda inteiro na máquina local, sem depender de Kuula, CloudPano ou internet.

**Repositório:** https://github.com/Jvsrp77/tour-virtual-360 *(privado)*

## Clonar

```bash
git clone https://github.com/Jvsrp77/tour-virtual-360.git
```

O modelo de profundidade (94 MB) não vem no repositório. Depois de clonar, rode
`python baixar_modelo.py` uma vez — sem ele tudo funciona, menos o modo "andar".

## Como rodar

Dê dois cliques em `iniciar.bat`. O navegador abre sozinho no painel.

Manualmente:

```bash
python -m pip install -r requirements.txt
python app.py
```

- Painel: http://localhost:5000/painel
- Tour: http://localhost:5000/tour

## As três formas de criar um ambiente

| Forma | Quando usar | O que acontece |
|---|---|---|
| **Costurar em 360** | Você tirou 8–12 fotos girando no eixo | O servidor alinha e costura numa panorâmica |
| **Importar equirretangular** | Você já tem a foto 360 (câmera 360 ou app) | Sobe direto, sem processar |
| **Gerar ambiente de teste** | Não tem foto nenhuma | Cria uma cena sintética para demonstrar |

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

## Exportar e publicar

O botão **Exportar ZIP** gera um pacote com `index.html`, `tour.json`, as imagens e a
biblioteca do visualizador. Suba numa hospedagem qualquer e o tour funciona sem Python.

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
data/scenes/              panorâmicas geradas
data/uploads/             fotos originais
data/tour.json            estrutura do tour e leads capturados
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
