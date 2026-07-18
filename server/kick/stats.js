const TOKEN_URL = 'https://id.kick.com/oauth/token';
const CANAIS_URL = 'https://api.kick.com/public/v1/channels';

let appAccessToken = null;
let expiraEm = 0;
let broadcasterUserIdCache = null;

async function obterAppAccessToken() {
  if (appAccessToken && Date.now() < expiraEm) return appAccessToken;

  const params = new URLSearchParams({
    grant_type: 'client_credentials',
    client_id: process.env.KICK_CLIENT_ID,
    client_secret: process.env.KICK_CLIENT_SECRET,
  });

  const resposta = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: params.toString(),
  });

  if (!resposta.ok) {
    throw new Error(`Falha ao obter app access token da Kick (${resposta.status}): ${await resposta.text()}`);
  }

  const corpo = await resposta.json();
  appAccessToken = corpo.access_token;
  // Margem de 1min antes de expirar de verdade.
  expiraEm = Date.now() + (corpo.expires_in - 60) * 1000;
  return appAccessToken;
}

async function buscarCanal(params) {
  const accessToken = await obterAppAccessToken();
  const url = new URL(CANAIS_URL);
  for (const [chave, valor] of Object.entries(params)) {
    url.searchParams.append(chave, valor);
  }

  const resposta = await fetch(url, { headers: { Authorization: `Bearer ${accessToken}` } });
  if (!resposta.ok) {
    throw new Error(`Falha ao buscar canal Kick (${resposta.status}): ${await resposta.text()}`);
  }

  const corpo = await resposta.json();
  return corpo.data?.[0];
}

async function broadcasterUserId() {
  if (broadcasterUserIdCache) return broadcasterUserIdCache;

  const canal = await buscarCanal({ slug: process.env.KICK_BROADCASTER_SLUG });
  if (!canal?.broadcaster_user_id) {
    throw new Error(`Não encontrei o canal Kick "${process.env.KICK_BROADCASTER_SLUG}".`);
  }

  broadcasterUserIdCache = canal.broadcaster_user_id;
  return broadcasterUserIdCache;
}

async function buscarStats() {
  const id = await broadcasterUserId();
  const canal = await buscarCanal({ broadcaster_user_id: id });

  return {
    aoVivo: Boolean(canal?.stream?.is_live),
    viewers: canal?.stream?.viewer_count ?? 0,
    inscritos: canal?.active_subscribers_count ?? 0,
  };
}

module.exports = { broadcasterUserId, buscarStats };
