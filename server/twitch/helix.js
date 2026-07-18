const store = require('../store');
const { obterAccessTokenValido } = require('./oauth');

async function chamarHelix(caminho, params) {
  const accessToken = await obterAccessTokenValido();

  const url = new URL(`https://api.twitch.tv/helix/${caminho}`);
  for (const [chave, valor] of Object.entries(params)) {
    url.searchParams.append(chave, valor);
  }

  const resposta = await fetch(url, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Client-Id': process.env.TWITCH_CLIENT_ID,
    },
  });

  if (!resposta.ok) {
    throw new Error(`Falha ao chamar Helix ${caminho} (${resposta.status}): ${await resposta.text()}`);
  }

  return resposta.json();
}

function broadcasterUserId() {
  const { userId } = store.buscarTokensTwitch();
  if (!userId) throw new Error('Twitch ainda não autorizada.');
  return userId;
}

async function buscarViewersAtuais() {
  const corpo = await chamarHelix('streams', { user_id: broadcasterUserId() });
  const stream = corpo.data?.[0];
  return {
    aoVivo: Boolean(stream),
    viewers: stream ? stream.viewer_count : 0,
  };
}

async function buscarTotalSeguidores() {
  const id = broadcasterUserId();
  const corpo = await chamarHelix('channels/followers', { broadcaster_id: id, moderator_id: id, first: 1 });
  return corpo.total ?? 0;
}

async function buscarTotalInscritos() {
  const corpo = await chamarHelix('subscriptions', { broadcaster_id: broadcasterUserId(), first: 1 });
  return corpo.total ?? 0;
}

module.exports = {
  broadcasterUserId,
  buscarViewersAtuais,
  buscarTotalSeguidores,
  buscarTotalInscritos,
};
