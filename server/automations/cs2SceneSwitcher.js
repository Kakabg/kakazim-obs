// Monitor de status do cs2-scene-switcher (Documents/SCRIPTS/cs2-scene-switcher),
// que expõe GET /status só de leitura ({ rodando, obsConectado }). Outros toggles
// futuros entram como mais um monitor desse mesmo formato em server/automations/.

const INTERVALO_MS = 5000;

async function consultarStatus() {
  try {
    const resposta = await fetch(process.env.CS2_SCENE_SWITCHER_STATUS_URL, { signal: AbortSignal.timeout(2000) });
    if (!resposta.ok) return { ligado: false };

    const corpo = await resposta.json();
    return { ligado: Boolean(corpo.rodando), obsConectado: Boolean(corpo.obsConectado) };
  } catch {
    // Sem resposta = script não está rodando (toggle.bat "desligado").
    return { ligado: false };
  }
}

function iniciar({ onAtualizar }) {
  async function checar() {
    const status = await consultarStatus();
    onAtualizar({ nome: 'cs2-scene-switcher', ...status });
  }

  checar();
  setInterval(checar, INTERVALO_MS);
}

module.exports = { iniciar };
