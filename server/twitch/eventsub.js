const WebSocket = require('ws');
const { obterAccessTokenValido } = require('./oauth');
const { broadcasterUserId } = require('./helix');

const URL_PADRAO = 'wss://eventsub.wss.twitch.tv/ws';
const SUBSCRICOES_URL = 'https://api.twitch.tv/helix/eventsub/subscriptions';
const ATRASO_RECONEXAO_MS = 5000;

function tiposDesejados(id) {
  return [
    { type: 'channel.follow', version: '2', condition: { broadcaster_user_id: id, moderator_user_id: id } },
    { type: 'channel.subscribe', version: '1', condition: { broadcaster_user_id: id } },
    { type: 'channel.chat.message', version: '1', condition: { broadcaster_user_id: id, user_id: id } },
  ];
}

async function criarInscricao({ type, version, condition, sessionId }) {
  const accessToken = await obterAccessTokenValido();

  const resposta = await fetch(SUBSCRICOES_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Client-Id': process.env.TWITCH_CLIENT_ID,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ type, version, condition, transport: { method: 'websocket', session_id: sessionId } }),
  });

  if (!resposta.ok) {
    console.error(`[Twitch EventSub] Falha ao assinar ${type} (${resposta.status}):`, await resposta.text());
  }
}

async function assinarTudo(sessionId) {
  const id = broadcasterUserId();
  for (const desejado of tiposDesejados(id)) {
    await criarInscricao({ ...desejado, sessionId });
  }
}

function iniciar({ onEvento }) {
  let socketAtual = null;

  function conectar(url) {
    const socket = new WebSocket(url);
    socketAtual = socket;

    socket.on('message', (dados) => {
      let mensagem;
      try {
        mensagem = JSON.parse(dados.toString('utf8'));
      } catch {
        return;
      }

      const tipo = mensagem.metadata?.message_type;

      if (tipo === 'session_welcome') {
        const sessionId = mensagem.payload.session.id;
        console.log(`[Twitch EventSub] Sessão conectada (${sessionId}), assinando eventos...`);
        assinarTudo(sessionId).catch((erro) => console.error('[Twitch EventSub] Erro ao assinar eventos:', erro));
        return;
      }

      if (tipo === 'session_keepalive') {
        return;
      }

      if (tipo === 'notification') {
        const subscription = mensagem.payload.subscription;
        onEvento(subscription.type, mensagem.payload.event);
        return;
      }

      if (tipo === 'session_reconnect') {
        const novaUrl = mensagem.payload.session.reconnect_url;
        console.warn('[Twitch EventSub] Twitch pediu reconexão, migrando sessão...');
        const antigo = socket;
        conectar(novaUrl);
        setTimeout(() => antigo.close(), 5000);
        return;
      }

      if (tipo === 'revocation') {
        console.warn('[Twitch EventSub] Assinatura revogada:', mensagem.payload.subscription);
      }
    });

    socket.on('close', () => {
      if (socketAtual !== socket) return; // já foi substituído por uma reconexão em andamento
      console.warn(`[Twitch EventSub] Conexão fechada. Reconectando em ${ATRASO_RECONEXAO_MS / 1000}s...`);
      setTimeout(() => conectar(URL_PADRAO), ATRASO_RECONEXAO_MS);
    });

    socket.on('error', (erro) => {
      console.error('[Twitch EventSub] Erro no WebSocket:', erro.message);
    });
  }

  conectar(URL_PADRAO);
}

module.exports = { iniciar };
