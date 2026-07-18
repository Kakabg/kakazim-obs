require('dotenv').config();
const path = require('node:path');
const http = require('node:http');
const express = require('express');
const { WebSocketServer } = require('ws');

const hub = require('./hub');
const twitchOauth = require('./twitch/oauth');

const PORTA = Number(process.env.PORT) || 8420;

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'public')));

app.get('/twitch/login', (req, res) => {
  res.redirect(twitchOauth.construirUrlAutorizacao());
});

app.get('/twitch/callback', async (req, res) => {
  const { code, state, error } = req.query;

  if (error) return res.status(400).send(`Autorização negada pela Twitch: ${error}`);
  if (!code || !state) return res.status(400).send('Faltam os parâmetros code/state no callback.');

  try {
    const usuario = await twitchOauth.trocarCodePorToken({ code, state });
    res.send(`Twitch autorizada: ${usuario.display_name}. Pode fechar essa aba - reinicie o painel (npm start) pra ativar o chat/feed em tempo real.`);
  } catch (erro) {
    console.error('Erro no /twitch/callback:', erro);
    res.status(500).send(`Falha ao concluir a autorização com a Twitch: ${erro.message}`);
  }
});

app.get('/api/state', (req, res) => {
  res.json(hub.obterEstado());
});

// Cadastro manual (1x) do total atual de seguidores da Kick - não existe endpoint
// oficial que devolva esse total, então esse número entra na mão e o hub
// incrementa sozinho a partir daí (server/kick/stats.js + server/hub.js).
app.post('/api/kick/seguidores', (req, res) => {
  const total = Number(req.body?.total);
  if (!Number.isFinite(total) || total < 0) {
    return res.status(400).json({ erro: 'Envie { "total": <número> }.' });
  }

  hub.definirTotalSeguidoresKick(total);
  res.json({ ok: true, total });
});

const servidor = http.createServer(app);
const wss = new WebSocketServer({ server: servidor });
wss.on('connection', (ws) => hub.registrarCliente(ws));

servidor.listen(PORTA, '127.0.0.1', () => {
  console.log(`✅ Painel local escutando em http://localhost:${PORTA}`);
  console.log(`   Adicione essa URL como Browser Source no OBS.`);
  if (!twitchOauth.autorizada()) {
    console.log(`   Twitch ainda não autorizada: acesse http://localhost:${PORTA}/twitch/login uma vez.`);
  }
});

hub.iniciar().catch((erro) => console.error('Erro ao iniciar o hub:', erro));
