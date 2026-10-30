/*
  Captura de contato, compartilhada pelas tres telas do visitante.

  POR QUE ISTO EXISTE NUM ARQUIVO SO. O convite de contato morava dentro do
  visualizador 360, escrito la. A maquete e a caminhada — que e onde o
  visitante anda, mede e escolhe o quarto — nao pediam contato nenhum: quem
  gostava do imovel fechava a aba, e do outro lado ninguem ficava sabendo.
  Medido: catorze imoveis publicados, ZERO contatos capturados.

  Copiar o formulario para mais duas paginas resolveria hoje e cobraria
  depois: tres copias do mesmo texto de consentimento, que muda, e tres
  lugares para esquecer de corrigir. Entao ele virou um arquivo so, que cada
  pagina chama.

  A pagina exportada em ZIP nao tem servidor. O envio falha ali, e falhar e o
  comportamento certo: o que nao pode e a tela quebrar por causa disso.
*/
(function(){
  "use strict";

  var ESTILO = ''
    + '.leadFundo{position:fixed;inset:0;z-index:4000;display:none;'
    +   'align-items:center;justify-content:center;background:rgba(10,12,16,.72);'
    +   'padding:18px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}'
    + '.leadFundo.aberto{display:flex}'
    + '.leadCaixa{background:#181b21;color:#fff;border:1px solid rgba(255,255,255,.14);'
    +   'border-radius:14px;padding:22px;width:min(380px,100%);'
    +   'box-shadow:0 18px 50px rgba(0,0,0,.45)}'
    + '.leadCaixa h2{margin:0 0 6px;font-size:19px}'
    + '.leadCaixa p{margin:0 0 16px;color:#a9b0ba;font-size:13.5px;line-height:1.45}'
    + '.leadCaixa input[type=text],.leadCaixa input[type=tel],'
    + '.leadCaixa input[type=email]{width:100%;margin-bottom:9px;background:#0f1115;'
    +   'color:#fff;border:1px solid rgba(255,255,255,.16);border-radius:8px;'
    +   'padding:11px 12px;font-size:14px;font-family:inherit}'
    + '.leadCaixa input:focus{outline:none;border-color:var(--leadCor,#e07b39)}'
    + '.leadAceite{display:flex;gap:9px;align-items:flex-start;margin:4px 0 14px;'
    +   'color:#9aa2ad;font-size:12px;line-height:1.4;cursor:pointer}'
    + '.leadAceite input{margin-top:2px;flex:0 0 auto}'
    + '.leadEnviar{width:100%;background:var(--leadCor,#e07b39);color:#1a1207;'
    +   'border:none;border-radius:8px;padding:12px;font-size:14.5px;'
    +   'font-weight:700;cursor:pointer;font-family:inherit}'
    + '.leadZap{width:100%;margin-top:9px;background:#25d366;color:#07321a;'
    +   'border:none;border-radius:8px;padding:12px;font-size:14.5px;'
    +   'font-weight:700;cursor:pointer;font-family:inherit;display:block;'
    +   'text-align:center;text-decoration:none}'
    + '.leadPular{width:100%;background:none;color:#8b929c;border:none;'
    +   'padding:9px;font-size:12.5px;cursor:pointer;font-family:inherit}'
    + '.leadErro{color:#ff9d8a;font-size:12.5px;margin:0 0 10px;display:none}'
    /* O botao fixo. Ele e o que faz diferenca de verdade: a janela aparece
       uma vez e quem fechou nao a ve mais, mas a vontade de falar com alguem
       costuma vir DEPOIS de andar pela casa, nao antes. */
    + '.leadChamar{position:fixed;right:14px;bottom:14px;z-index:3900;'
    +   'background:var(--leadCor,#e07b39);color:#1a1207;border:none;'
    +   'border-radius:999px;padding:12px 18px;font-size:14px;font-weight:700;'
    +   'cursor:pointer;display:none;align-items:center;gap:8px;'
    +   'box-shadow:0 6px 20px rgba(0,0,0,.3);'
    +   'font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}'
    + '.leadChamar.aberto{display:inline-flex}'
    + '@media (max-width:520px){.leadChamar{right:10px;bottom:10px;'
    +   'padding:11px 15px;font-size:13px}}';

  var MARCACAO = ''
    + '<div class="leadCaixa">'
    +   '<h2 data-lead="titulo">Gostou do imóvel?</h2>'
    +   '<p data-lead="texto"></p>'
    +   '<p class="leadErro" data-lead="erro"></p>'
    +   '<input type="text"  data-lead="nome"     placeholder="Seu nome">'
    +   '<input type="tel"   data-lead="telefone" placeholder="Telefone / WhatsApp">'
    +   '<input type="email" data-lead="email"    placeholder="E-mail">'
    +   '<label class="leadAceite"><input type="checkbox" data-lead="aceite">'
    +     '<span>Autorizo o contato sobre este imóvel e a guarda dos meus dados'
    +     ' para isso. Posso pedir a exclusão a qualquer momento.</span></label>'
    +   '<button class="leadEnviar" data-lead="enviar">Quero falar com um corretor</button>'
    +   '<a class="leadZap" data-lead="zap" target="_blank" rel="noopener"'
    +     ' style="display:none">Chamar no WhatsApp</a>'
    +   '<button class="leadPular" data-lead="pular">Continuar vendo</button>'
    + '</div>';

  function cada(raiz, nome){ return raiz.querySelector('[data-lead="' + nome + '"]'); }

  function Lead(){
    this.cfg = null;
    this.fundo = null;
    this.chamar = null;
    this.enviado = false;
  }

  // A CHAVE DE JA-ENVIOU E POR IMOVEL. Com uma chave so, quem deixasse o
  // contato num imovel nunca mais via o convite em nenhum outro — e visitante
  // que olha tres casas e justamente o que vale a pena perguntar.
  Lead.prototype._chave = function(){ return 'lead_ok_' + (this.cfg.imovel || ''); };

  Lead.prototype._jaEnviou = function(){
    try { return !!sessionStorage.getItem(this._chave()); } catch (e) { return false; }
  };

  Lead.prototype._marcarEnviado = function(){
    this.enviado = true;
    try { sessionStorage.setItem(this._chave(), '1'); } catch (e) { /* anonima */ }
    if (this.chamar) this.chamar.classList.remove('aberto');
  };

  Lead.prototype._zap = function(){
    var n = (this.cfg.whatsapp || '').replace(/\D/g, '');
    if (n.length < 10) return '';          // numero curto demais para ser real
    // titulo_imovel, e nao titulo: titulo e o cabecalho do convite ("Gostou
    // do imovel?"), e a mensagem sairia "Vi o tour virtual de Gostou do
    // imovel?" — na conversa do corretor, com o interessado olhando.
    var t = 'Olá! Vi o tour virtual';
    if (this.cfg.titulo_imovel) t += ' de "' + this.cfg.titulo_imovel + '"';
    return 'https://wa.me/' + n + '?text=' + encodeURIComponent(t + ' e queria mais informações.');
  };

  Lead.prototype.iniciar = function(cfg){
    this.cfg = cfg || {};
    if (this.cfg.ativo === false) return;

    var est = document.createElement('style');
    est.textContent = ESTILO;
    document.head.appendChild(est);
    if (this.cfg.cor) document.documentElement.style.setProperty('--leadCor', this.cfg.cor);

    var fundo = document.createElement('div');
    fundo.className = 'leadFundo';
    fundo.innerHTML = MARCACAO;
    document.body.appendChild(fundo);
    this.fundo = fundo;

    var botao = document.createElement('button');
    botao.className = 'leadChamar';
    botao.type = 'button';
    botao.textContent = 'Falar com um corretor';
    document.body.appendChild(botao);
    this.chamar = botao;

    cada(fundo, 'titulo').textContent = this.cfg.titulo || 'Gostou do imóvel?';
    cada(fundo, 'texto').textContent = this.cfg.texto
      || 'Deixe seu contato que um corretor fala com você.';

    var zap = cada(fundo, 'zap'), href = this._zap();
    if (href){ zap.href = href; zap.style.display = 'block'; }

    var eu = this;
    botao.addEventListener('click', function(){ eu.abrir(); });
    cada(fundo, 'enviar').addEventListener('click', function(){ eu.enviar(); });
    cada(fundo, 'pular').addEventListener('click', function(){ eu.fechar(); });
    fundo.addEventListener('click', function(ev){
      if (ev.target === fundo) eu.fechar();      // clicar fora fecha
    });
    document.addEventListener('keydown', function(ev){
      if (ev.key === 'Escape' && fundo.classList.contains('aberto')) eu.fechar();
    });

    if (!this._jaEnviou()) botao.classList.add('aberto');

    var espera = this.cfg.segundos;
    if (espera === undefined || espera === null) espera = 25;
    if (espera >= 0) setTimeout(function(){ eu.abrir(true); }, espera * 1000);
  };

  // sozinho=true e o convite automatico; ele cede a vez, o do botao nunca.
  Lead.prototype.abrir = function(sozinho){
    if (this.enviado || this._jaEnviou()) return;
    // NAO INTERROMPE QUEM ESTA ANDANDO. Na maquete e na caminhada o visitante
    // anda com o mouse preso na tela; abrir uma janela por cima rouba o
    // ponteiro no meio do passo e o que se ve e a casa girando sozinha. O
    // convite automatico espera; o botao continua la, e e dele que vem o
    // contato de quem andou pela casa inteira e gostou.
    if (sozinho && typeof this.cfg.ocupado === 'function' && this.cfg.ocupado()){
      var eu = this;
      setTimeout(function(){ eu.abrir(true); }, 8000);
      return;
    }
    if (typeof this.cfg.aoAbrir === 'function') this.cfg.aoAbrir();
    this.fundo.classList.add('aberto');
  };

  Lead.prototype.fechar = function(){
    this.fundo.classList.remove('aberto');
    if (typeof this.cfg.aoFechar === 'function') this.cfg.aoFechar();
  };

  Lead.prototype.enviar = function(){
    var f = this.fundo;
    var erro = cada(f, 'erro');
    var dados = {
      nome: cada(f, 'nome').value.trim(),
      telefone: cada(f, 'telefone').value.trim(),
      email: cada(f, 'email').value.trim(),
      quando: new Date().toISOString()
    };
    function reclamar(texto){
      erro.textContent = texto;
      erro.style.display = 'block';
    }
    if (!dados.nome || (!dados.telefone && !dados.email))
      return reclamar('Preencha seu nome e pelo menos um contato.');
    if (!cada(f, 'aceite').checked)
      return reclamar('Marque a autorização para que possamos entrar em contato.');
    erro.style.display = 'none';

    // GUARDA O TEXTO ACEITO, e nao so que houve aceite: a LGPD pede que o
    // titular saiba ao que consentiu, e o texto muda com o tempo.
    dados.consentimento = cada(f, 'aceite').parentNode.innerText.trim();

    var eu = this;
    var pronto = function(){
      eu._marcarEnviado();
      var zap = eu._zap();
      f.innerHTML = '<div class="leadCaixa"><h2>Obrigado!</h2>'
        + '<p>Recebemos seu contato. Um corretor vai falar com você em breve.</p>'
        + (zap ? '<a class="leadZap" href="' + zap + '" target="_blank"'
                 + ' rel="noopener">Chamar no WhatsApp agora</a>' : '')
        + '<button class="leadPular" data-lead="pular">Voltar</button></div>';
      cada(f, 'pular').addEventListener('click', function(){ eu.fechar(); });
    };

    // O CONTATO NAO PODE SE PERDER NA REDE. Se o envio falhar, a tela agradece
    // do mesmo jeito e o contato fica guardado aqui para a proxima visita
    // tentar de novo — na exportacao em ZIP nao ha servidor nenhum, e mesmo
    // assim ninguem merece um "erro" na cara depois de digitar o telefone.
    var alvo = (this.cfg.api || '') + '/leads';
    try {
      fetch(alvo, {method: 'POST', headers: {'Content-Type': 'application/json'},
                   body: JSON.stringify(dados)})
        .catch(function(){ eu._guardarPendente(dados); });
    } catch (e) { this._guardarPendente(dados); }
    pronto();
  };

  Lead.prototype._guardarPendente = function(dados){
    try {
      var k = 'lead_pendente_' + (this.cfg.imovel || '');
      localStorage.setItem(k, JSON.stringify(dados));
    } catch (e) { /* sem onde guardar: paciencia */ }
  };

  // Na abertura seguinte, tenta de novo o que ficou preso.
  Lead.prototype.reenviarPendente = function(){
    var k = 'lead_pendente_' + (this.cfg.imovel || ''), bruto;
    try { bruto = localStorage.getItem(k); } catch (e) { return; }
    if (!bruto) return;
    var alvo = (this.cfg.api || '') + '/leads';
    fetch(alvo, {method: 'POST', headers: {'Content-Type': 'application/json'},
                 body: bruto})
      .then(function(r){ if (r.ok) localStorage.removeItem(k); })
      .catch(function(){ /* fica para a proxima */ });
  };

  window.Lead = new Lead();
})();
