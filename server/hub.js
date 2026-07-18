const crypto = require('node:crypto');
const store = require('./store');

const twitchOauth = require('./twitch/oauth');
const twitchHelix = require('./twitch/helix');
const twitchEventsub = require('./twitch/eventsub');

const kickStats = require('./kick/stats');
const kickRelay = require('./kick/relayClient');

const cs2SceneSwitcher = require('./automations/cs2SceneSwitcher');

const INTERVALO_VIEWERS_MS = 15000;
const INTERVALO_TOTAIS_MS = 60000;

const estado = {
  twitch: { aoVivo: false, viewers: 0, seguidores: null, inscritos: null },
  kick: { aoVivo: false, viewers: 0, seguidores: null, inscritos: null },
  atividades: store.listarAtividades(),
  chat: store.listarChat(),
  automacoes: {},
};

const clientesWs = new Set();

function transmitir(mensagem) {
  const linha = JSON.stringify(mensagem);
  for (const ws of clientesWs) {
    if (ws.readyState === ws.OPEN) ws.send(linha);
  }
}

function registrarCliente(ws) {
  clientesWs.add(ws);
  ws.send(JSON.stringify({ tipo: 'snapshot', dados: estado }));
  ws.on('close', () => clientesWs.delete(ws));
}

function atualizarStats(plataforma, parcial) {
  Object.assign(estado[plataforma], parcial);
  transmitir({ tipo: 'stats', plataforma, dados: estado[plataforma] });
}

function registrarAtividade(item) {
  const completo = { id: crypto.randomUUID(), timestamp: Date.now(), ...item };
  store.adicionarAtividade(completo);
  estado.atividades = store.listarAtividades();
  transmitir({ tipo: 'atividade', item: completo });
}

function registrarChat(item) {
  const completo = { id: crypto.randomUUID(), timestamp: Date.now(), ...item };
  store.adicionarChat(completo);
  estado.chat = store.listarChat();
  transmitir({ tipo: 'chat', item: completo });
}

function atualizarAutomacao(nome, dados) {
  estado.automacoes[nome] = dados;
  transmitir({ tipo: 'automacao', nome, dados });
}

// --- Twitch ---

function tratarEventoTwitch(tipo, evento) {
  if (tipo === 'channel.follow') {
    registrarAtividade({ plataforma: 'twitch', tipo: 'seguidor', usuario: evento.user_name });
    if (estado.twitch.seguidores != null) atualizarStats('twitch', { seguidores: estado.twitch.seguidores + 1 });
    return;
  }

  if (tipo === 'channel.subscribe') {
    registrarAtividade({ plataforma: 'twitch', tipo: 'inscricao', usuario: evento.user_name, detalhe: evento.is_gift ? 'presenteada' : null });
    if (estado.twitch.inscritos != null) atualizarStats('twitch', { inscritos: estado.twitch.inscritos + 1 });
    return;
  }

  if (tipo === 'channel.chat.message') {
    registrarChat({
      plataforma: 'twitch',
      usuario: evento.chatter_user_name,
      mensagem: evento.message?.text ?? '',
      cor: evento.color || null,
    });
  }
}

async function iniciarTwitch() {
  if (!twitchOauth.autorizada()) {
    console.warn('[Twitch] Ainda não autorizado. Acesse http://localhost:' + (process.env.PORT || 8420) + '/twitch/login uma vez.');
    return;
  }

  async function atualizarViewers() {
    try {
      const { aoVivo, viewers } = await twitchHelix.buscarViewersAtuais();
      atualizarStats('twitch', { aoVivo, viewers });
    } catch (erro) {
      console.error('[Twitch] Erro ao buscar viewers:', erro.message);
    }
  }

  async function atualizarTotais() {
    try {
      const [seguidores, inscritos] = await Promise.all([twitchHelix.buscarTotalSeguidores(), twitchHelix.buscarTotalInscritos()]);
      atualizarStats('twitch', { seguidores, inscritos });
    } catch (erro) {
      console.error('[Twitch] Erro ao buscar totais:', erro.message);
    }
  }

  atualizarViewers();
  atualizarTotais();
  setInterval(atualizarViewers, INTERVALO_VIEWERS_MS);
  setInterval(atualizarTotais, INTERVALO_TOTAIS_MS);

  twitchEventsub.iniciar({ onEvento: tratarEventoTwitch });
}

// --- Kick ---

function tratarEventoKick({ tipo, payload }) {
  if (tipo === 'channel.subscription.new' || tipo === 'channel.subscription.renewal') {
    registrarAtividade({
      plataforma: 'kick',
      tipo: 'inscricao',
      usuario: payload.subscriber?.username,
      detalhe: tipo === 'channel.subscription.renewal' ? 'renovação' : null,
    });
    return;
  }

  if (tipo === 'channel.followed') {
    registrarAtividade({ plataforma: 'kick', tipo: 'seguidor', usuario: payload.follower?.username });
    const novoTotal = store.incrementarSeguidoresKick(1);
    if (novoTotal != null) atualizarStats('kick', { seguidores: novoTotal });
    return;
  }

  if (tipo === 'chat.message.sent') {
    registrarChat({
      plataforma: 'kick',
      usuario: payload.sender?.username,
      mensagem: payload.content ?? '',
      cor: payload.sender?.identity?.username_color || null,
    });
  }
}

async function iniciarKick() {
  const kickSalvo = store.buscarKick();
  if (kickSalvo.followerTotal != null) {
    estado.kick.seguidores = kickSalvo.followerTotal;
  }

  async function atualizarStatsKick() {
    try {
      const { aoVivo, viewers, inscritos } = await kickStats.buscarStats();
      atualizarStats('kick', { aoVivo, viewers, inscritos });
    } catch (erro) {
      console.error('[Kick] Erro ao buscar stats:', erro.message);
    }
  }

  atualizarStatsKick();
  setInterval(atualizarStatsKick, INTERVALO_VIEWERS_MS);

  if (!process.env.KICK_RELAY_URL || !process.env.KICK_RELAY_SECRET) {
    console.warn('[Kick] KICK_RELAY_URL/KICK_RELAY_SECRET não configurados - sem feed de atividade/chat da Kick.');
    return;
  }

  kickRelay.iniciar({
    onEvento: ({ tipo, payload }) => tratarEventoKick({ tipo, payload }),
  });
}

// --- Automações ---

function iniciarAutomacoes() {
  cs2SceneSwitcher.iniciar({
    onAtualizar: ({ nome, ...dados }) => atualizarAutomacao(nome, dados),
  });
}

// --- API pública do hub ---

function definirTotalSeguidoresKick(total) {
  store.definirTotalSeguidoresKick(total);
  atualizarStats('kick', { seguidores: total });
}

function obterEstado() {
  return estado;
}

async function iniciar() {
  await iniciarTwitch();
  await iniciarKick();
  iniciarAutomacoes();
}

module.exports = {
  iniciar,
  registrarCliente,
  obterEstado,
  definirTotalSeguidoresKick,
};
