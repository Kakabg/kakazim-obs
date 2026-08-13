const MAX_ITENS_TELA_CHAT = 60;
const LIMIAR_SCROLL_PX = 80;
const INTERVALO_ATUALIZACAO_TEMPO_MS = 30000;

function formatarNumero(valor) {
  return valor == null ? '—' : Number(valor).toLocaleString('pt-BR');
}

// Emotes da Kick chegam embutidos no texto da mensagem, no formato bruto
// "[emote:ID:Nome]" (a Kick não manda imagem nenhuma, só isso) - CDN pública
// deles pra buscar a imagem pelo ID: https://files.kick.com/emotes/{id}/
// fullsize (confirmado batendo o ID de um emote real visto ao vivo no chat).
const REGEX_EMOTE_KICK = /\[emote:(\d+):([^\]]*)\]/g;

function urlEmoteKick(id) {
  return `https://files.kick.com/emotes/${id}/fullsize`;
}

/**
 * Preenche `elemento` com o texto da mensagem, trocando cada
 * "[emote:ID:Nome]" por um <img> - resto do texto vira nó de texto normal
 * ao redor. Via createTextNode/createElement (não innerHTML) de propósito:
 * o texto vem de mensagem de chat de terceiros, não pode virar HTML.
 */
function preencherMensagemComEmotes(elemento, texto) {
  const valor = texto || '';
  let ultimoIndice = 0;

  for (const match of valor.matchAll(REGEX_EMOTE_KICK)) {
    const [completo, id, nome] = match;
    const indice = match.index ?? 0;

    if (indice > ultimoIndice) {
      elemento.appendChild(document.createTextNode(valor.slice(ultimoIndice, indice)));
    }

    const img = document.createElement('img');
    img.src = urlEmoteKick(id);
    img.alt = nome || `emote ${id}`;
    if (nome) img.title = nome;
    img.className = 'emote-kick';
    elemento.appendChild(img);

    ultimoIndice = indice + completo.length;
  }

  if (ultimoIndice < valor.length) {
    elemento.appendChild(document.createTextNode(valor.slice(ultimoIndice)));
  }
}

function formatarTempoRelativo(timestampMs) {
  const diffMin = Math.floor((Date.now() - timestampMs) / 60000);
  if (diffMin < 1) return 'agora';
  if (diffMin < 60) return `há ${diffMin}min`;

  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `há ${diffH}h`;

  const diffD = Math.floor(diffH / 24);
  if (diffD < 30) return `há ${diffD}d`;

  return new Date(timestampMs).toLocaleDateString('pt-BR');
}

// Kick/Twitch mostram o ícone de marca de verdade via mask-image em CSS (ver
// style.css) - sem letra. StreamElements continua no monograma de letra.
const LETRA_POR_PLATAFORMA = { streamelements: '$' };

function iconeMini(plataforma, { sub = false } = {}) {
  const span = document.createElement('span');
  span.className = `icone-plataforma-mini ${plataforma}${sub ? ' sub' : ''}`;
  span.setAttribute('aria-hidden', 'true');
  const letra = LETRA_POR_PLATAFORMA[plataforma];
  if (letra) span.textContent = letra;
  return span;
}

// Perfil na própria plataforma, a partir do mesmo indicador (K/T) que já
// identifica cada linha - StreamElements não entra aqui (doação não tem
// perfil de Kick/Twitch garantido por trás do nome mostrado).
const URL_PERFIL_POR_PLATAFORMA = {
  kick: (usuario) => `https://kick.com/${encodeURIComponent(usuario)}`,
  twitch: (usuario) => `https://www.twitch.tv/${encodeURIComponent(usuario)}`,
};

function criarNomeUsuario(item) {
  const montarUrl = URL_PERFIL_POR_PLATAFORMA[item.plataforma];

  if (!item.usuario || !montarUrl) {
    const span = document.createElement('span');
    span.className = 'item-usuario';
    span.textContent = item.usuario || '(anônimo)';
    return span;
  }

  const link = document.createElement('a');
  link.className = 'item-usuario';
  link.href = montarUrl(item.usuario);
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = item.usuario;
  return link;
}

function textoAtividade(item) {
  if (item.tipo === 'seguidor') return 'seguiu o canal';
  if (item.tipo === 'inscricao') {
    // Resub da Twitch já vem com o detalhe pronto pra virar a frase inteira
    // ("renovou por X meses: mensagem") - "se inscreveu (renovou por...)"
    // ficava redundante. Kick e a primeira inscrição (com/sem presente)
    // continuam como antes.
    if (item.plataforma === 'twitch' && (item.detalhe === 'renovação' || item.detalhe?.startsWith('renovou por'))) {
      return item.detalhe;
    }
    return item.detalhe ? `se inscreveu (${item.detalhe})` : 'se inscreveu';
  }
  if (item.tipo === 'raid') return item.detalhe ? `fez raid com ${item.detalhe} viewers` : 'fez raid';
  if (item.tipo === 'doacao') return item.detalhe ? `doou ${item.detalhe}` : 'doou';
  return item.tipo;
}

function atualizarCard(plataforma, dados) {
  const card = document.getElementById(`card-${plataforma}`);
  if (!card) return;

  if ('aoVivo' in dados) {
    card.querySelector('.ao-vivo').dataset.aoVivo = String(Boolean(dados.aoVivo));
  }
  for (const campo of ['viewers', 'seguidores', 'inscritos']) {
    if (campo in dados) {
      card.querySelector(`[data-campo="${campo}"]`).textContent = formatarNumero(dados[campo]);
    }
  }
}

// mutado: true|false|null (null = desconhecido, ver hub.py). Indicador ainda
// não validado com uma live de verdade (relatos de bug do voiceStateUpdate
// em algumas versões do discord.js - ver kakazim-bot: discord/muteStatus.js).
function atualizarDiscordIndicador(dados) {
  const indicador = document.getElementById('indicador-discord');
  if (!indicador || !dados || !('mutado' in dados)) return;

  const mutado = dados.mutado;
  indicador.dataset.mutado = mutado === true ? 'true' : mutado === false ? 'false' : 'desconhecido';
  indicador.querySelector('.rotulo').textContent = mutado === true ? 'Mutado' : mutado === false ? 'Ativo' : 'Discord';
}

// Ícone de "repetir/reexibir" por item (qualquer um da lista, não só o mais
// recente) - manda o próprio item (tipo/plataforma/usuario/detalhe) pro
// backend local, que repassa pro kakazim-bot mostrar o alerta de novo na
// AlertBox da StreamElements (ver kakazim_panel/streamelements.py e
// server.js: /api/streamelements/repetir-evento). Generaliza o botão
// "Repetir Alerta LivePix" do Stream Deck (que só repete o ÚLTIMO alerta da
// LivePix, sem escolha de qual) pra qualquer evento desta lista.
function botaoRepetirAtividade(item) {
  const botao = document.createElement('button');
  botao.type = 'button';
  botao.className = 'botao-repetir';
  botao.title = 'Repetir o alerta desse evento';
  botao.setAttribute('aria-label', 'Repetir o alerta desse evento');
  botao.textContent = '🔁';

  botao.addEventListener('click', async () => {
    if (botao.disabled) return;
    botao.disabled = true;

    try {
      const resposta = await fetch('/api/atividades/repetir', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tipo: item.tipo,
          plataforma: item.plataforma,
          usuario: item.usuario,
          detalhe: item.detalhe,
        }),
      });
      const corpo = await resposta.json().catch(() => ({}));
      if (!resposta.ok) throw new Error(corpo.erro || `Falha ao repetir (HTTP ${resposta.status})`);

      botao.textContent = '✅';
      botao.title = 'Alerta repetido!';
    } catch (erro) {
      console.error('Falha ao repetir alerta:', erro);
      botao.textContent = '⚠️';
      botao.title = erro.message || String(erro);
    } finally {
      setTimeout(() => {
        botao.textContent = '🔁';
        botao.title = 'Repetir o alerta desse evento';
        botao.disabled = false;
      }, 2500);
    }
  });

  return botao;
}

function criarItemAtividade(item) {
  const li = document.createElement('li');
  li.dataset.timestamp = String(item.timestamp);
  li.appendChild(iconeMini(item.plataforma));
  li.appendChild(criarNomeUsuario(item));

  const detalhe = document.createElement('span');
  detalhe.className = 'item-detalhe';
  detalhe.textContent = textoAtividade(item);
  li.appendChild(detalhe);

  const tempo = document.createElement('span');
  tempo.className = 'item-tempo';
  tempo.textContent = formatarTempoRelativo(item.timestamp);
  li.appendChild(tempo);

  li.appendChild(botaoRepetirAtividade(item));

  return li;
}

// Itens novos (evento ao vivo, ou cada item do snapshot inicial processado em
// ordem cronológica) sempre entram no topo - a lista fica com o mais novo em
// cima e o mais antigo embaixo, igual outros feeds de atividade.
function prependAtividade(item) {
  const lista = document.getElementById('lista-atividades');
  lista.querySelector('.item-vazio')?.remove();
  lista.prepend(criarItemAtividade(item));
}

// Página mais antiga carregada pelo scroll infinito entra embaixo, na mesma
// ordem (mais novo do lote primeiro) - ver carregarAtividadesAntigas.
function anexarAtividadeAntiga(item) {
  const lista = document.getElementById('lista-atividades');
  lista.querySelector('.item-vazio')?.remove();
  lista.appendChild(criarItemAtividade(item));
}

function atualizarTemposRelativos() {
  for (const li of document.querySelectorAll('#lista-atividades li[data-timestamp]')) {
    const tempo = li.querySelector('.item-tempo');
    if (tempo) tempo.textContent = formatarTempoRelativo(Number(li.dataset.timestamp));
  }
}

// Estado do "carregar mais" (scroll infinito) da Atividade recente - o
// snapshot/eventos ao vivo só trazem os itens mais recentes (ver
// hub.TAMANHO_SNAPSHOT_HISTORICO no backend); o resto do histórico completo
// vem sob demanda de GET /api/atividades.
const paginacaoAtividades = { carregando: false, esgotado: false, maisAntigo: null };

async function carregarAtividadesAntigas() {
  if (paginacaoAtividades.carregando || paginacaoAtividades.esgotado) return;
  if (paginacaoAtividades.maisAntigo == null) return;

  paginacaoAtividades.carregando = true;
  try {
    const resposta = await fetch(`/api/atividades?antes=${paginacaoAtividades.maisAntigo}&limite=50`);
    if (!resposta.ok) return;
    const { itens } = await resposta.json();

    if (!itens || itens.length === 0) {
      paginacaoAtividades.esgotado = true;
      return;
    }

    for (const item of itens) anexarAtividadeAntiga(item);
    paginacaoAtividades.maisAntigo = itens[itens.length - 1].timestamp;
  } catch (erro) {
    console.error('Falha ao carregar atividades antigas:', erro);
  } finally {
    paginacaoAtividades.carregando = false;
  }
}

function aoRolarListaAtividades() {
  const lista = document.getElementById('lista-atividades');
  const distanciaDoFim = lista.scrollHeight - lista.scrollTop - lista.clientHeight;
  if (distanciaDoFim < LIMIAR_SCROLL_PX) carregarAtividadesAntigas();
}

function adicionarChat(item, { autoScroll = true } = {}) {
  const lista = document.getElementById('lista-chat');
  lista.querySelector('.item-vazio')?.remove();

  const li = document.createElement('li');
  li.appendChild(iconeMini(item.plataforma, { sub: Boolean(item.sub) }));

  const usuario = criarNomeUsuario(item);
  if (item.cor) usuario.style.color = item.cor;
  li.appendChild(usuario);

  // Mensagens que o próprio bot mandou (via /api/kick/enviar-mensagem) não
  // vêm de um espectador real - marca visualmente pra não parecer que foi
  // alguém do chat. Ver origem: "bot_local" em kakazim_panel/hub.py.
  if (item.origem === 'bot_local') {
    const badge = document.createElement('span');
    badge.className = 'badge-bot';
    badge.textContent = 'bot';
    li.appendChild(badge);
  }

  const mensagem = document.createElement('span');
  preencherMensagemComEmotes(mensagem, item.mensagem);
  li.appendChild(mensagem);

  lista.appendChild(li);
  while (lista.children.length > MAX_ITENS_TELA_CHAT) {
    lista.removeChild(lista.firstChild);
  }

  if (autoScroll) lista.scrollTop = lista.scrollHeight;
}

// Só o texto mostrado na tela - o identificador interno ("nome", usado como
// chave de estado.automacoes e em data-nome) continua sendo o mesmo que a
// API de status já usa (cs2-scene-switcher). Automação futura sem rótulo
// aqui cai no próprio "nome" cru (ver fallback abaixo).
const ROTULOS_AUTOMACAO = {
  'cs2-scene-switcher': 'CS-Auto',
};

function atualizarAutomacao(nome, dados) {
  const lista = document.getElementById('lista-automacoes');
  let chip = lista.querySelector(`[data-nome="${nome}"]`);

  if (!chip) {
    chip = document.createElement('li');
    chip.className = 'chip-automacao';
    chip.dataset.nome = nome;
    chip.innerHTML = `<span class="bolinha"></span><span class="rotulo"></span>`;
    lista.appendChild(chip);
  }

  const rotulo = ROTULOS_AUTOMACAO[nome] ?? nome;
  chip.dataset.ligado = String(Boolean(dados.ligado));
  chip.querySelector('.rotulo').textContent = `${rotulo}: ${dados.ligado ? 'ligado' : 'desligado'}`;
}

function renderizarSnapshot(estado) {
  atualizarCard('kick', estado.kick);
  atualizarCard('twitch', estado.twitch);
  atualizarDiscordIndicador(estado.discord);

  const listaAtividades = document.getElementById('lista-atividades');
  listaAtividades.innerHTML = '';
  paginacaoAtividades.carregando = false;
  paginacaoAtividades.esgotado = false;
  if (estado.atividades.length === 0) {
    listaAtividades.innerHTML = '<li class="item-vazio">Sem atividade ainda.</li>';
    paginacaoAtividades.maisAntigo = null;
  } else {
    // estado.atividades vem em ordem cronológica crescente (mais antigo
    // primeiro) - processar nessa ordem com prepend deixa o mais novo no
    // topo, igual um evento ao vivo chegando.
    for (const item of estado.atividades) prependAtividade(item);
    paginacaoAtividades.maisAntigo = estado.atividades[0].timestamp;
  }

  const listaChat = document.getElementById('lista-chat');
  listaChat.innerHTML = '';
  if (estado.chat.length === 0) {
    listaChat.innerHTML = '<li class="item-vazio">Sem mensagens ainda.</li>';
  } else {
    for (const item of estado.chat) adicionarChat(item, { autoScroll: false });
    listaChat.scrollTop = listaChat.scrollHeight;
  }

  for (const [nome, dados] of Object.entries(estado.automacoes)) atualizarAutomacao(nome, dados);
}

// Backend Python (script de OBS) usa SSE em vez de WebSocket - servidor HTTP
// so de biblioteca padrao nao tem um servidor WS pronto, e SSE (so precisa de
// uma resposta HTTP de vida longa) cobre exatamente o mesmo caso de uso de
// "servidor empurra atualizacoes pro navegador" sem precisar de handshake/
// framing proprio. O resto deste arquivo (renderizacao) nao mudou nada.
function conectar() {
  const es = new EventSource('/events');

  es.addEventListener('message', (evento) => {
    const mensagem = JSON.parse(evento.data);

    if (mensagem.tipo === 'snapshot') renderizarSnapshot(mensagem.dados);
    else if (mensagem.tipo === 'stats' && mensagem.plataforma === 'discord') atualizarDiscordIndicador(mensagem.dados);
    else if (mensagem.tipo === 'stats') atualizarCard(mensagem.plataforma, mensagem.dados);
    else if (mensagem.tipo === 'atividade') prependAtividade(mensagem.item);
    else if (mensagem.tipo === 'chat') adicionarChat(mensagem.item);
    else if (mensagem.tipo === 'automacao') atualizarAutomacao(mensagem.nome, mensagem.dados);
  });

  // EventSource já tenta reconectar sozinho, mas de forma menos previsível -
  // fechamos explicitamente e recriamos pra ter o mesmo comportamento
  // simples e previsível de antes (com WebSocket).
  es.addEventListener('error', () => {
    es.close();
    setTimeout(conectar, 3000);
  });
}

// Caixa de texto embaixo do Chat - manda pro canal do próprio streamer, na
// plataforma escolhida no seletor ao lado do cabeçalho "Chat"
// (POST /api/chat/mensagem, ver kakazim_panel/http_server.py). A mensagem
// enviada não é ecoada aqui na hora: ela chega pelo mesmo caminho de sempre
// (relay da Kick / EventSub da Twitch) alguns instantes depois, igual
// qualquer outra mensagem do chat - mandar e já mostrar na lista faria
// duplicar quando o evento de verdade chegasse.
function configurarEnvioChat() {
  const form = document.getElementById('form-chat-enviar');
  const input = document.getElementById('chat-mensagem');
  const seletor = document.getElementById('chat-plataforma');
  const status = document.getElementById('chat-enviar-status');

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    const mensagem = input.value.trim();
    if (!mensagem) return;

    input.disabled = true;
    status.dataset.erro = 'false';
    status.textContent = 'Enviando…';

    try {
      const resposta = await fetch('/api/chat/mensagem', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plataforma: seletor.value, message: mensagem }),
      });
      const corpo = await resposta.json().catch(() => ({}));
      if (!resposta.ok) throw new Error(corpo.erro || `Falha ao enviar (HTTP ${resposta.status})`);

      input.value = '';
      status.textContent = '';
    } catch (erro) {
      status.dataset.erro = 'true';
      status.textContent = erro.message || String(erro);
    } finally {
      input.disabled = false;
      input.focus();
    }
  });
}

// Divisória arrastável entre Chat e Atividade recente - a proporção muda ao
// vivo via --largura-chat (percentual, ver .painel em style.css), então um
// painel cresce EXATAMENTE na proporção que o outro encolhe (mesma faixa de
// espaço total, só a fronteira entre os dois se move). LARGURA_MINIMA_PX
// garante que nenhum lado consiga sumir - o clamp usa o percentual
// equivalente a esse mínimo em pixels na largura atual do painel, então
// continua correto mesmo se a janela/Browser Source for redimensionada
// depois. Persistido em localStorage pra sobreviver a um reload/restart do
// OBS.
function configurarDivisoriaResizavel() {
  const painel = document.querySelector('.painel');
  const divisoria = document.getElementById('divisoria-chat-feed');
  if (!painel || !divisoria) return;

  const CHAVE_LARGURA = 'kakazim-painel-largura-chat-pct';
  const LARGURA_MINIMA_PX = 240;
  const LARGURA_PADRAO_PCT = 50;

  function aplicarLarguraPct(pct) {
    painel.style.setProperty('--largura-chat', `${pct}%`);
  }

  function larguraMinimaPct(larguraPainelPx) {
    // Mínimo dos dois lados (a coluna direita também não pode sumir) -
    // 10px a mais de folga pela própria divisória entre as colunas.
    return ((LARGURA_MINIMA_PX + 10) / larguraPainelPx) * 100;
  }

  const larguraSalva = Number(localStorage.getItem(CHAVE_LARGURA));
  aplicarLarguraPct(Number.isFinite(larguraSalva) && larguraSalva > 0 ? larguraSalva : LARGURA_PADRAO_PCT);

  let larguraAtualPct = Number.isFinite(larguraSalva) && larguraSalva > 0 ? larguraSalva : LARGURA_PADRAO_PCT;

  function moverPara(clientX) {
    const retangulo = painel.getBoundingClientRect();
    const minimo = larguraMinimaPct(retangulo.width);
    let pct = ((clientX - retangulo.left) / retangulo.width) * 100;
    pct = Math.min(100 - minimo, Math.max(minimo, pct));
    larguraAtualPct = pct;
    aplicarLarguraPct(pct);
  }

  divisoria.addEventListener('pointerdown', (evento) => {
    divisoria.setPointerCapture(evento.pointerId);
    painel.dataset.arrastando = 'true';
    evento.preventDefault();
  });

  divisoria.addEventListener('pointermove', (evento) => {
    if (painel.dataset.arrastando !== 'true') return;
    moverPara(evento.clientX);
  });

  function soltar(evento) {
    if (painel.dataset.arrastando !== 'true') return;
    painel.dataset.arrastando = 'false';
    divisoria.releasePointerCapture(evento.pointerId);
    localStorage.setItem(CHAVE_LARGURA, String(larguraAtualPct));
  }

  divisoria.addEventListener('pointerup', soltar);
  divisoria.addEventListener('pointercancel', soltar);

  // Teclado (acessibilidade) - seta esquerda/direita move em passos de 2%,
  // já respeitando o mesmo mínimo do drag.
  divisoria.addEventListener('keydown', (evento) => {
    if (evento.key !== 'ArrowLeft' && evento.key !== 'ArrowRight') return;
    evento.preventDefault();
    const retangulo = painel.getBoundingClientRect();
    const minimo = larguraMinimaPct(retangulo.width);
    const passo = evento.key === 'ArrowLeft' ? -2 : 2;
    larguraAtualPct = Math.min(100 - minimo, Math.max(minimo, larguraAtualPct + passo));
    aplicarLarguraPct(larguraAtualPct);
    localStorage.setItem(CHAVE_LARGURA, String(larguraAtualPct));
  });
}

document.getElementById('lista-atividades').addEventListener('scroll', aoRolarListaAtividades);
setInterval(atualizarTemposRelativos, INTERVALO_ATUALIZACAO_TEMPO_MS);
configurarEnvioChat();
configurarDivisoriaResizavel();
conectar();
