# Endereço fixo para o link do imóvel

O tour rodava atrás de um túnel "rápido" do Cloudflare — aquele que levanta
sem conta e entrega um endereço sorteado, do feitio
`pressing-randy-limitation-robert.trycloudflare.com`.

Serve para olhar uma vez. Não serve para vender:

- **o endereço muda a cada reinício.** O link que você mandou ontem para o
  cliente não abre hoje, e ninguém avisa: o cliente só vê erro;
- **o túnel rápido cai sozinho** depois de algumas horas;
- `pressing-randy-limitation-robert` num WhatsApp **parece golpe**, e parte
  das pessoas simplesmente não clica.

Com domínio reservado o endereço é sempre o mesmo. Vira um endereço que dá
para imprimir num anúncio, mandar por e-mail e repetir ao telefone.

---

## O token é seu

A configuração abaixo guarda uma credencial na sua máquina (no perfil do
`cloudflared` ou do `ngrok`). **Faça você mesmo os passos marcados com 🔑** —
o token não passa por este projeto, não entra em arquivo do repositório e não
precisa ser dito a ninguém.

O que o projeto precisa saber é só o **nome do domínio**, que é público por
definição: ele aparece na barra do navegador de todo visitante.

---

## Opção A — Cloudflare (recomendada se você tem um domínio)

Sem custo, e o endereço fica no seu próprio domínio
(`tour.suaimobiliaria.com.br`), que é o que mais transmite confiança.

1. Instale:

```bash
winget install cloudflare.cloudflared
```

2. 🔑 Entre na sua conta (abre o navegador, você escolhe o domínio):

```bash
cloudflared tunnel login
```

3. Crie o túnel (uma vez só):

```bash
cloudflared tunnel create tour
```

4. Aponte o domínio para ele (uma vez só):

```bash
cloudflared tunnel route dns tour tour.suaimobiliaria.com.br
```

5. Diga ao projeto qual é o domínio:

```bash
setx TOUR_TUNEL cloudflare
setx TOUR_TUNEL_DOMINIO tour.suaimobiliaria.com.br
```

Abra um terminal **novo** depois do `setx` — ele não altera o terminal que já
está aberto.

---

## Opção B — ngrok (se você não tem domínio próprio)

O plano gratuito dá **um** domínio estático, do feitio
`algum-nome.ngrok-free.app`. Não é tão bonito quanto o seu domínio, mas é
fixo, que é o que importa.

1. Instale:

```bash
winget install ngrok.ngrok
```

2. 🔑 Guarde seu token (pegue em dashboard.ngrok.com):

```bash
ngrok config add-authtoken SEU_TOKEN_AQUI
```

3. Reserve o domínio gratuito no painel do ngrok, em **Domains**.

4. Diga ao projeto qual é:

```bash
setx TOUR_TUNEL ngrok
setx TOUR_TUNEL_DOMINIO algum-nome.ngrok-free.app
```

---

## Conferindo

Suba o servidor normalmente:

```bash
python servidor.py
```

Ele imprime o endereço fixo na partida. Se algo faltar, ele diz **o quê** e
como resolver, em vez de subir calado sem túnel — porque túnel que não subiu
em silêncio é descoberto pelo cliente, não por você.

## O cookie de sessão

Com túnel, quem termina o HTTPS é o Cloudflare ou o ngrok, e o servidor passa
a ficar atrás de um proxy. Nesse caso o `servidor.py` liga sozinho o
`TOUR_ATRAS_DE_PROXY`, que marca o cookie de sessão como seguro. Sem isso o
cookie viajaria sem a marca, e um cookie de sessão sem marca de seguro é um
convite para ser lido no caminho.
