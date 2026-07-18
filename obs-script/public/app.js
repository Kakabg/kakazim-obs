const MAX_ITENS_TELA = 60;

function formatarNumero(valor) {
  return valor == null ? '—' : Number(valor).toLocaleString('pt-BR');
}

function iconeMini(plataforma) {
  const span = document.createElement('span');
  span.className = `icone-plataforma-mini ${plataforma}`;
  span.textContent = plataforma === 'kick' ? 'K' : 'T';
  return span;
}

function textoAtividade(item) {
  if (item.tipo === 'seguidor') return 'seguiu o canal';
  if (item.tipo === 'inscricao') return item.detalhe ? `se inscreveu (${item.detalhe})` : 'se inscreveu';
  if (item.tipo === 'raid') return item.detalhe ? `fez raid com ${item.detalhe} viewers` : 'fez raid';
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

function limitarItens(lista, max = MAX_ITENS_TELA) {
  while (lista.children.length > max) {
    lista.removeChild(lista.lastChild);
  }
}

function prependAtividade(item) {
  const lista = document.getElementById('lista-atividades');
  lista.querySelector('.item-vazio')?.remove();

  const li = document.createElement('li');
  li.appendChild(iconeMini(item.plataforma));

  const usuario = document.createElement('span');
  usuario.className = 'item-usuario';
  usuario.textContent = item.usuario || '(anônimo)';
  li.appendChild(usuario);

  const detalhe = document.createElement('span');
  detalhe.className = 'item-detalhe';
  detalhe.textContent = textoAtividade(item);
  li.appendChild(detalhe);

  lista.prepend(li);
  limitarItens(lista);
}

function adicionarChat(item, { autoScroll = true } = {}) {
  const lista = document.getElementById('lista-chat');
  lista.querySelector('.item-vazio')?.remove();

  const li = document.createElement('li');
  li.appendChild(iconeMini(item.plataforma));

  const usuario = document.createElement('span');
  usuario.className = 'item-usuario';
  usuario.textContent = item.usuario || '(anônimo)';
  if (item.cor) usuario.style.color = item.cor;
  li.appendChild(usuario);

  const mensagem = document.createElement('span');
  mensagem.textContent = item.mensagem || '';
  li.appendChild(mensagem);

  lista.appendChild(li);
  while (lista.children.length > MAX_ITENS_TELA) {
    lista.removeChild(lista.firstChild);
  }

  if (autoScroll) lista.scrollTop = lista.scrollHeight;
}

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

  chip.dataset.ligado = String(Boolean(dados.ligado));
  chip.querySelector('.rotulo').textContent = `${nome}: ${dados.ligado ? 'ligado' : 'desligado'}`;
}

function renderizarSnapshot(estado) {
  atualizarCard('kick', estado.kick);
  atualizarCard('twitch', estado.twitch);

  const listaAtividades = document.getElementById('lista-atividades');
  listaAtividades.innerHTML = '';
  const atividadesRecentes = [...estado.atividades].reverse();
  if (atividadesRecentes.length === 0) {
    listaAtividades.innerHTML = '<li class="item-vazio">Sem atividade ainda.</li>';
  } else {
    for (const item of atividadesRecentes.slice(0, MAX_ITENS_TELA)) prependAtividade(item);
  }

  const listaChat = document.getElementById('lista-chat');
  listaChat.innerHTML = '';
  if (estado.chat.length === 0) {
    listaChat.innerHTML = '<li class="item-vazio">Sem mensagens ainda.</li>';
  } else {
    for (const item of estado.chat.slice(-MAX_ITENS_TELA)) adicionarChat(item, { autoScroll: false });
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

conectar();
