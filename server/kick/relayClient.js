// Cliente SSE do relay exposto pelo kakazim-bot (server.js: GET /painel/eventos).
// A Kick só entrega webhook (não tem WebSocket público como a Twitch), então só
// o kakazim-bot no Railway pode receber esses eventos - esse cliente conecta
// nele de fora pra dentro (o painel local puxa, o Railway não precisa saber que
// o PC existe).

const ATRASO_RECONEXAO_MS = 5000;

function aguardar(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function processarBloco(bloco, onEvento) {
  for (const linha of bloco.split('\n')) {
    if (!linha.startsWith('data:')) continue;
    const json = linha.slice(5).trim();
    try {
      onEvento(JSON.parse(json));
    } catch (erro) {
      console.error('[Kick relay] Payload SSE inválido:', erro.message);
    }
  }
}

async function conectarUmaVez(onEvento) {
  const url = new URL(process.env.KICK_RELAY_URL);
  url.searchParams.set('key', process.env.KICK_RELAY_SECRET);

  const resposta = await fetch(url, { headers: { Accept: 'text/event-stream' } });
  if (!resposta.ok || !resposta.body) {
    throw new Error(`Falha ao conectar no relay da Kick (${resposta.status})`);
  }

  console.log('[Kick relay] Conectado ao kakazim-bot.');
  const leitor = resposta.body.getReader();
  const decoder = new TextDecoder('utf8');
  let buffer = '';

  while (true) {
    const { done, value } = await leitor.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let indice;
    while ((indice = buffer.indexOf('\n\n')) !== -1) {
      const bloco = buffer.slice(0, indice);
      buffer = buffer.slice(indice + 2);
      processarBloco(bloco, onEvento);
    }
  }

  console.warn('[Kick relay] Conexão encerrada pelo servidor.');
}

async function iniciar({ onEvento }) {
  while (true) {
    try {
      await conectarUmaVez(onEvento);
    } catch (erro) {
      console.error('[Kick relay] Erro de conexão:', erro.message);
    }
    await aguardar(ATRASO_RECONEXAO_MS);
  }
}

module.exports = { iniciar };
