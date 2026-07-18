const crypto = require('node:crypto');
const store = require('../store');

const AUTORIZACAO_URL = 'https://id.twitch.tv/oauth2/authorize';
const TOKEN_URL = 'https://id.twitch.tv/oauth2/token';
const USERS_URL = 'https://api.twitch.tv/helix/users';

// Escopos pro painel: total de inscritos (subs), total e feed de seguidores, e
// leitura de chat. Como o token é sempre do próprio streamer lendo o próprio
// canal, não precisa de user:bot (isso só é exigido pra contas de bot separadas
// do broadcaster/moderador).
const ESCOPOS = 'channel:read:subscriptions moderator:read:followers user:read:chat';

// Só um fluxo de autorização por vez (uso pessoal, local) - guarda o último
// `state` gerado até o /twitch/callback confirmar.
let stateEmAndamento = null;

function redirectUri() {
  const porta = process.env.PORT || 8420;
  return `http://localhost:${porta}/twitch/callback`;
}

function construirUrlAutorizacao() {
  stateEmAndamento = crypto.randomBytes(16).toString('hex');

  const params = new URLSearchParams({
    client_id: process.env.TWITCH_CLIENT_ID,
    response_type: 'code',
    redirect_uri: redirectUri(),
    scope: ESCOPOS,
    state: stateEmAndamento,
  });

  return `${AUTORIZACAO_URL}?${params.toString()}`;
}

async function trocarCodePorToken({ code, state }) {
  if (!stateEmAndamento || state !== stateEmAndamento) {
    throw new Error('State inválido ou expirado. Acesse /twitch/login de novo.');
  }
  stateEmAndamento = null;

  const params = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    client_id: process.env.TWITCH_CLIENT_ID,
    client_secret: process.env.TWITCH_CLIENT_SECRET,
    redirect_uri: redirectUri(),
  });

  const resposta = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: params.toString(),
  });

  if (!resposta.ok) {
    throw new Error(`Falha ao trocar code por token (${resposta.status}): ${await resposta.text()}`);
  }

  const token = await resposta.json();
  const usuario = await buscarUsuarioAutenticado(token.access_token);

  store.salvarTokensTwitch({
    accessToken: token.access_token,
    refreshToken: token.refresh_token,
    expiresAt: Date.now() + token.expires_in * 1000,
    userId: usuario.id,
    login: usuario.login,
  });

  return usuario;
}

async function buscarUsuarioAutenticado(accessToken) {
  const resposta = await fetch(USERS_URL, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Client-Id': process.env.TWITCH_CLIENT_ID,
    },
  });

  if (!resposta.ok) {
    throw new Error(`Falha ao buscar usuário Twitch (${resposta.status}): ${await resposta.text()}`);
  }

  const corpo = await resposta.json();
  const usuario = corpo.data?.[0];
  if (!usuario) throw new Error('Resposta da Twitch não trouxe dados do usuário.');
  return usuario;
}

async function renovarToken(refreshToken) {
  const params = new URLSearchParams({
    grant_type: 'refresh_token',
    refresh_token: refreshToken,
    client_id: process.env.TWITCH_CLIENT_ID,
    client_secret: process.env.TWITCH_CLIENT_SECRET,
  });

  const resposta = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: params.toString(),
  });

  if (!resposta.ok) {
    throw new Error(`Falha ao renovar token da Twitch (${resposta.status}): ${await resposta.text()}`);
  }

  const token = await resposta.json();
  const tokensAtuais = store.buscarTokensTwitch();

  store.salvarTokensTwitch({
    ...tokensAtuais,
    accessToken: token.access_token,
    refreshToken: token.refresh_token || refreshToken,
    expiresAt: Date.now() + token.expires_in * 1000,
  });

  return token.access_token;
}

// Margem de 2min antes de expirar de verdade, pra nunca usar um token que vence
// no meio de uma chamada.
const MARGEM_EXPIRACAO_MS = 2 * 60 * 1000;

async function obterAccessTokenValido() {
  const tokens = store.buscarTokensTwitch();
  if (!tokens.accessToken || !tokens.refreshToken) {
    throw new Error('Twitch ainda não autorizada. Acesse /twitch/login primeiro.');
  }

  if (tokens.expiresAt && Date.now() < tokens.expiresAt - MARGEM_EXPIRACAO_MS) {
    return tokens.accessToken;
  }

  return renovarToken(tokens.refreshToken);
}

function autorizada() {
  const tokens = store.buscarTokensTwitch();
  return Boolean(tokens.accessToken && tokens.refreshToken);
}

module.exports = {
  construirUrlAutorizacao,
  trocarCodePorToken,
  obterAccessTokenValido,
  autorizada,
};
