const MAX_ITENS_TELA_CHAT = 60;
const LIMIAR_SCROLL_PX = 80;
const INTERVALO_ATUALIZACAO_TEMPO_MS = 30000;

function formatarNumero(valor) {
  return valor == null ? '—' : Number(valor).toLocaleString('pt-BR');
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

function iconeMini(plataforma) {
  const span = document.createElement('span');
  span.className = `icone-plataforma-mini ${plataforma}`;
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
  li.appendChild(iconeMini(item.plataforma));

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
  mensagem.textContent = item.mensagem || '';
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

document.getElementById('lista-atividades').addEventListener('scroll', aoRolarListaAtividades);
setInterval(atualizarTemposRelativos, INTERVALO_ATUALIZACAO_TEMPO_MS);
configurarEnvioChat();
conectar();
