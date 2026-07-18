# Painel da live - script nativo do OBS (Python)

Versão do painel (estatísticas de Kick/Twitch, feed de atividade, chat
unificado, status de automações) que roda **dentro do próprio OBS**, via
`Tools > Scripts`, em vez de um processo Node.js separado que precisa de
terminal. Liga e desliga sozinho junto com o OBS.

Esta pasta é auto-contida: `kakazim_obs.py` é o arquivo que você adiciona no
OBS; tudo o resto (`kakazim_panel/`) é a lógica em Python puro, sem nenhuma
dependência do OBS, portada 1:1 do backend Node original (`../server/`).

## O que preserva do backend Node original

- **Twitch**: conexão direta (sem depender do kakazim-bot/Railway) via
  EventSub WebSocket (`channel.follow`, `channel.subscribe`,
  `channel.chat.message`) + polling REST (Helix) pra viewers/seguidores/
  inscritos.
- **Kick**: polling da API pública oficial (viewers + total de inscritos,
  via `client_credentials`, sem OAuth de usuário) + um cliente SSE que
  recebe, em tempo real, os eventos que só a Kick manda por webhook (novo
  seguidor, nova assinatura, chat), retransmitidos pelo **kakazim-bot**
  (Railway) através do endpoint `GET /painel/eventos` (ver
  `../../kakazim-bot/server.js`).
- **Seguidores da Kick**: não existe endpoint oficial com o total acumulado,
  então o número é cadastrado manualmente uma vez (agora direto no campo de
  configuração do script, dentro do OBS) e incrementado ao vivo a cada
  `channel.followed` recebido.
- **Automação do CS2**: hoje ela roda dentro do plugin de Stream Deck
  "Kakazim.Live" (`../../kakazim-live`), não mais no script Node standalone
  antigo. Adicionamos um `GET /status` nesse plugin especificamente pra esse
  painel conseguir checar se está ligada - ver seção *"Sobre o status do CS2"*
  abaixo, é importante.

## Por que essa arquitetura (decisões tomadas sem te perguntar)

- **SSE em vez de WebSocket entre o backend e o navegador**: a biblioteca
  padrão do Python não tem servidor WebSocket pronto, e implementar o
  handshake/framing do WebSocket na mão é arriscado de acertar sem poder
  testar ao vivo. SSE (Server-Sent Events) resolve o mesmo problema (backend
  empurra atualizações pro navegador) usando só uma resposta HTTP de vida
  longa - `http.server` da biblioteca padrão já dá conta disso. Só a função
  `conectar()` do `app.js` mudou; todo o resto do frontend é idêntico.
- **`websocket-client` como única dependência externa**: diferente do lado
  servidor, aqui o painel precisa ser um **cliente** WebSocket de verdade
  (conexão de saída pra `wss://eventsub.wss.twitch.tv/ws`), e implementar um
  cliente WebSocket correto (handshake TLS, framing, ping/pong) na mão é bem
  mais arriscado de acertar sem testes ao vivo do que usar uma biblioteca
  matura e amplamente usada. É a única exceção à regra de "só biblioteca
  padrão".
- **Threads de verdade (`threading.Thread`), não `obs.timer_add`**: scripts
  do OBS rodam na thread principal da interface - qualquer chamada de rede
  feita diretamente ali trava o OBS inteiro. Toda chamada de rede (servidor
  HTTP, WebSocket da Twitch, SSE da Kick, polling) roda em threads de
  background dedicadas, nunca na thread principal.
- **Kick: reaproveita o mesmo app (client_id/secret) do kakazim-bot.** Como a
  Kick só entrega webhook (sem WebSocket público), o retransmissor no Railway
  é obrigatório de qualquer forma - não tem custo adicional reaproveitar as
  mesmas credenciais só de leitura (`client_credentials`) pra também buscar
  viewers/inscritos direto daqui.
- **Twitch: app dedicado, separado do kakazim-bot** (mesma decisão já tomada
  na versão Node do painel) - evita qualquer conflito de assinaturas
  duplicadas do EventSub e mantém as responsabilidades separadas.

## Sobre o status do CS2 (leia isso)

Você mencionou que o status "hoje é checado via HTTP no plugin do Stream
Deck" - conferindo o código do `kakazim-live`, isso **ainda não existia**: o
plugin só tinha o servidor de GSI (`POST /gsi`, porta padrão 3211), sem
nenhuma rota de status. Fiz a alteração pra isso passar a existir:

- `kakazim-live/src/actions/cs2-scene-switcher/gsi-server.ts`: o mesmo
  servidor HTTP que já recebia o GSI do CS2 agora também responde
  `GET /status` com `{"rodando": true/false, "obsConectado": true/false}`.
- `kakazim-live/src/actions/cs2-scene-switcher/automation-controller.ts`:
  passa o status real (`this._status === "running"` + `obsClient.isConnected()`)
  pro servidor.
- Já rodei `npm run build` no projeto `kakazim-live` pra confirmar que
  compila (compilou sem erro) - **mas você precisa reiniciar o plugin** pro
  `bin/plugin.js` novo entrar em uso (feche e abra o Stream Deck, ou
  clique com o botão direito no ícone do app na bandeja > Reiniciar, se
  houver essa opção).

**Limitação que continua existindo**: esse servidor de status só fica de pé
enquanto a automação estiver "ligada" (a tecla do Stream Deck ativada) - é
assim que o servidor de GSI sempre funcionou, então mantivemos o mesmo
comportamento pro `/status`. Isso significa que "conexão recusada" quer
dizer tanto "automação desligada" quanto "Stream Deck fechado" - pro efeito
prático do painel (mostrar ligado/desligado), os dois casos são "desligado"
mesmo, então não muda nada pra você, só documentando a nuance.

A porta de GSI é configurável por tecla no Stream Deck (campo "GSI Port" na
Property Inspector, default `3211`) - se você mudou esse valor lá, ajuste
também o campo "Automação CS2: URL de status" nas configurações deste
script pra apontar pra mesma porta.

## Passos manuais (faça nessa ordem)

### 1. Instalar Python (se ainda não tiver)

O **OBS 32.x só suporta Python 3.6 a 3.12** na sua integração de scripting -
versões mais novas (ex: 3.13, 3.14) não são reconhecidas pelo campo "Python
Install Path" do OBS. Baixe a **3.12** em
https://www.python.org/downloads/release/python-3120/ (ou qualquer 3.9-3.12).
Na instalação, marque a opção "Add python.exe to PATH".

Se você já tem alguma versão mais nova instalada (ex: 3.14) pra outros usos,
sem problema - o instalador do python.org não sobrescreve, cada versão fica
na sua própria pasta (ex: `AppData\Local\Programs\Python\Python312` e
`Python314` lado a lado). Só que, com duas versões no PC, o comando genérico
`python` no PATH pode resolver pra qualquer uma das duas (geralmente a mais
recente) - por isso, a partir daqui, os comandos usam o **caminho completo**
do `python.exe` da 3.12, pra garantir que é sempre essa versão sendo chamada,
não a mais nova. Ajuste o caminho abaixo se a sua instalação ficou em outro
lugar (confira em `AppData\Local\Programs\Python\`).

```powershell
$py312 = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
```

### 2. Instalar a dependência (`websocket-client`) nesse Python

Depois de instalado, abra um terminal (PowerShell) e rode (reaproveitando a
variável `$py312` do passo 1):

```powershell
& $py312 -m pip install websocket-client
```

Isso garante que a dependência vai pro Python 3.12, não pra outra versão que
esteja no PATH.

### 3. Apontar o OBS pro Python instalado

No OBS: `Tools > Scripts` > aba **Python Settings** > em "Python Install
Path", aponte pra pasta da 3.12 (ex:
`C:\Users\Luiz Carlos\AppData\Local\Programs\Python\Python312`) - a pasta,
não o `python.exe` diretamente.

### 4. Testar fora do OBS primeiro (recomendado, mais fácil de debugar)

Antes de confiar direto no OBS, dá pra rodar esse mesmo código isolado, num
terminal comum, pra conferir que sobe sem erro. Use o **mesmo** `python.exe`
da 3.12 (é onde o `websocket-client` do passo 2 foi instalado - rodar com
outra versão do Python aqui vai dar `ModuleNotFoundError`):

```powershell
cd "C:\Users\Luiz Carlos\kakazim-OBS\obs-script"
& $py312 testar_localmente.py
```

Abra `http://localhost:8420` no navegador - devia aparecer o painel (sem
dados reais ainda, se não preencheu variáveis de ambiente - ver comentário no
topo do `testar_localmente.py` pra testar com credenciais reais por lá
também). `Ctrl+C` pra parar.

**Isso eu não consegui testar por aqui**: não achei nenhum Python instalado
neste PC pra rodar de verdade (só o código foi escrito e revisado com
cuidado, sem interpretador disponível pra executar). Esse passo 4 é a sua
primeira verificação real de que o código funciona antes de colocar no OBS.

### 5. Adicionar o script no OBS

`Tools > Scripts` > `+` (Add Scripts) > selecione
`C:\Users\Luiz Carlos\kakazim-OBS\obs-script\kakazim_obs.py`.

### 6. Preencher as configurações

Com o script selecionado na lista, os campos aparecem à direita:

- **Porta do painel local**: `8420` (padrão, pode deixar).
- **Twitch: Client ID / Client Secret**: de um app dedicado - ver seção
  abaixo se ainda não tiver.
- **Twitch: login do canal**: seu username na Twitch (ex: `kakazim`).
- **Kick: Client ID / Client Secret**: pode reaproveitar os mesmos do
  `kakazim-bot` (estão no `.env` de lá).
- **Kick: slug do canal**: seu username na Kick (ex: `kakazim`).
- **Kick: URL do relay**: `https://kakazim-bot-production.up.railway.app/painel/eventos`
  (já vem preenchido por padrão).
- **Kick: segredo do relay**: o mesmo valor de `PAINEL_RELAY_SECRET` que
  você configurar no Railway (ver seção do `kakazim-bot` abaixo) -
  `2c1d5ba4a3cc89d9c357d82f85819418892870b32d8cf607` (gerado hoje mais cedo,
  nesta mesma sessão, pra versão Node do painel - reaproveite o mesmo valor
  aqui pra não precisar reconfigurar o Railway de novo).
- **Kick: definir/resetar total de seguidores**: digite o número atual de
  seguidores da sua Kick (você mesmo confere isso na página do seu canal) e
  clique fora do campo/aplique - só precisa fazer isso uma vez.
- **Automação CS2: URL de status**: `http://127.0.0.1:3211/status` (padrão,
  só mude se você configurou uma porta de GSI diferente no Stream Deck).

Depois de preencher tudo, clique em **"🔗 Autorizar Twitch (abre no
navegador)"** uma vez (ver próxima seção sobre criar o app da Twitch antes
disso) - essa é a sua conta principal, só usada pra leitura/estatísticas
(viewers, seguidores, inscritos, feed de chat).

Em seguida clique também em **"🤖 Autorizar Twitch (bot, abre no
navegador)"** - essa é a conta separada (ex: `kakazimbot`, já cadastrada como
Moderadora/Editora do seu canal) que efetivamente manda a mensagem quando
você aperta "Enviar Mensagem" no Stream Deck. **Antes de clicar nesse
segundo botão, entre no navegador com a conta bot** (aba anônima ou outro
perfil do navegador) - quem decide qual conta autoriza é a sessão logada no
navegador na hora do consentimento da Twitch, não o botão em si.

Depois de autorizar os dois, clique em **"🔄 Reiniciar conexões"** pra
ativar de fato o chat/feed da Twitch (a conexão só é aberta na primeira vez
que o script carrega ou quando esse botão é clicado).

Clique em **"🖥️ Abrir o painel no navegador"** pra conferir que está tudo
funcionando antes de adicionar como Browser Source.

### 7. Criar o app dedicado da Twitch (se ainda não tiver, da tarefa anterior)

Em https://dev.twitch.tv/console/apps > "Registrar seu aplicativo":
- **Nome**: qualquer um (ex: "Kakazim Painel").
- **OAuth Redirect URLs**: `http://localhost:8420/twitch/callback` (mesma
  porta configurada no passo 6 - se mudar a porta lá, mude aqui também e
  reautorize).
- **Categoria**: "Application Integration" ou similar.

Depois de criado, copie o **Client ID** e gere um **Client Secret** - cole
os dois nos campos do passo 6.

### 8. Adicionar como Browser Source no OBS

`Sources` > `+` > `Browser` > URL `http://localhost:8420` (ou a porta que
você configurou).

### 9. No kakazim-bot (Railway) - já feito nesta sessão, só falta você aplicar

O endpoint `GET /painel/eventos` e a assinatura dos eventos
`channel.followed`/`chat.message.sent` da Kick já foram adicionados ao
código do `kakazim-bot` mais cedo (numa tarefa anterior desta mesma sessão).
Confirme que:

1. Fez o **redeploy** do `kakazim-bot` no Railway com essas mudanças.
2. Configurou `PAINEL_RELAY_SECRET=2c1d5ba4a3cc89d9c357d82f85819418892870b32d8cf607`
   nas variáveis de ambiente do projeto **no Railway** (não só no `.env`
   local).
3. Acessou `https://kakazim-bot-production.up.railway.app/kick/inscrever-webhook?key=<seu KICK_SETUP_SECRET>`
   uma vez, pra Kick passar a mandar os eventos novos.

Se esses 3 pontos já estavam pendentes de antes, seguem pendentes agora
também - não mudei nada a mais no kakazim-bot nesta tarefa além do
heartbeat descrito abaixo.

**Adicionado nesta tarefa**: um heartbeat (`: ping`) a cada 20s na conexão
SSE do `/painel/eventos`, pra evitar que o cliente Python derrube a conexão
por timeout em períodos sem nenhum evento da Kick. Isso também precisa do
redeploy do passo 1 pra valer.

## Testes que consegui fazer sem OBS/Python disponíveis

- Revisão manual cuidadosa de cada arquivo (sem conseguir executar,
  documentado acima).
- `npm run build` do `kakazim-live` (mudança do `/status`) - compilou sem
  erro.
- Pesquisa da API oficial de scripting do OBS (`script_load`,
  `script_properties`, tipos de campo, botões, threading) pra validar as
  escolhas de arquitetura antes de escrever o código.

## Estrutura

```
obs-script/
  kakazim_obs.py              # arquivo que voce adiciona no OBS (Tools > Scripts)
  testar_localmente.py         # roda o mesmo codigo fora do OBS, num terminal
  requirements.txt              # so "websocket-client"
  kakazim_panel/                 # logica pura em Python, sem obspython
    config.py                      # config em memoria (equivalente ao .env)
    store.py                        # persistencia JSON local (obs-script/data/store.json)
    http_util.py                     # helpers de requisicao HTTP (urllib)
    http_server.py                    # servidor HTTP local + SSE (so biblioteca padrao)
    hub.py                             # estado central + fan-out pros clientes SSE
    twitch/
      oauth.py                          # fluxo OAuth local
      helix.py                           # polling REST (viewers/seguidores/inscritos)
      eventsub.py                         # cliente WebSocket (websocket-client)
    kick/
      stats.py                            # polling REST publico (client_credentials)
      relay_client.py                      # cliente SSE do relay no kakazim-bot
    automations/
      cs2_scene_switcher.py                 # polling do /status do plugin Kakazim.Live
  public/                                    # copia do frontend original, só com
                                              # app.js ajustado pra SSE em vez de WS
```

O backend Node original (`../server/`) continua intacto e funcional, caso
precise dele de novo por algum motivo - essa pasta é um substituto
independente, não uma alteração nele.
