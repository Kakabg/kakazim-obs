const fs = require('node:fs');
const path = require('node:path');

const DATA_DIR = path.join(__dirname, 'data');
const ARQUIVO = path.join(DATA_DIR, 'store.json');

const CAP_ATIVIDADES = 200;
const CAP_CHAT = 200;

const ESTADO_PADRAO = {
  twitch: {
    accessToken: null,
    refreshToken: null,
    expiresAt: null,
    userId: null,
    login: null,
  },
  kick: {
    followerTotal: null,
    followerSeedEm: null,
  },
  atividades: [],
  chat: [],
};

function carregar() {
  try {
    const bruto = fs.readFileSync(ARQUIVO, 'utf8');
    return { ...structuredClone(ESTADO_PADRAO), ...JSON.parse(bruto) };
  } catch {
    return structuredClone(ESTADO_PADRAO);
  }
}

let estado = carregar();

// Escrita atômica (escreve em arquivo temporário e renomeia) pra não corromper o
// store.json se o processo morrer no meio de uma gravação.
function salvar() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  const tmp = `${ARQUIVO}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(estado, null, 2));
  fs.renameSync(tmp, ARQUIVO);
}

function salvarTokensTwitch({ accessToken, refreshToken, expiresAt, userId, login }) {
  estado.twitch = { accessToken, refreshToken, expiresAt, userId, login };
  salvar();
}

function buscarTokensTwitch() {
  return estado.twitch;
}

function definirTotalSeguidoresKick(total) {
  estado.kick.followerTotal = total;
  estado.kick.followerSeedEm = Date.now();
  salvar();
}

function incrementarSeguidoresKick(delta = 1) {
  if (estado.kick.followerTotal == null) return null;
  estado.kick.followerTotal += delta;
  salvar();
  return estado.kick.followerTotal;
}

function buscarKick() {
  return estado.kick;
}

function adicionarAtividade(item) {
  estado.atividades.push(item);
  if (estado.atividades.length > CAP_ATIVIDADES) {
    estado.atividades = estado.atividades.slice(-CAP_ATIVIDADES);
  }
  salvar();
}

function listarAtividades() {
  return estado.atividades;
}

function adicionarChat(item) {
  estado.chat.push(item);
  if (estado.chat.length > CAP_CHAT) {
    estado.chat = estado.chat.slice(-CAP_CHAT);
  }
  salvar();
}

function listarChat() {
  return estado.chat;
}

module.exports = {
  salvarTokensTwitch,
  buscarTokensTwitch,
  definirTotalSeguidoresKick,
  incrementarSeguidoresKick,
  buscarKick,
  adicionarAtividade,
  listarAtividades,
  adicionarChat,
  listarChat,
};
