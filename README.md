# kakazim-OBS - Painel Live

O painel que aparece como dock dentro do OBS durante a live: números da Kick e
da Twitch, chat unificado, atividade recente, aba Subs, comandos de chat,
sorteio e conquistas.

É um script **Python** que roda dentro do próprio OBS (Tools > Scripts) e liga
e desliga junto com ele. Tudo fica em [`obs-script/`](obs-script/README.md),
que tem o passo a passo de instalação e a explicação de cada parte.

- Servidor local na porta **8420**. Com o OBS aberto, essa porta é o painel
  **ao vivo** - pra testar sem mexer nele, use
  `python obs-script/testar_localmente.py` com `KAKAZIM_PORTA` numa porta
  diferente.
- Eventos da **Twitch** chegam direto (EventSub WebSocket). Os da **Kick**
  chegam pelo kakazim-bot, porque a Kick exige um endereço público pro
  webhook.

A versão antiga em Node.js (`server/`, `public/`) foi removida em 2026-10-07
e continua no histórico do git.
