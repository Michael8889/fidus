# Fidus

Assistente pessoal por voz: agenda, e-mail, gastos, recibos, documentos, tarefas, atas de reunião e link de
agendamento. O usuário fala ou digita no app; o servidor transcreve (Whisper local), a IA decide e usa
ferramentas (Google Agenda, Gmail, banco de dados próprio). Nada sai em nome do usuário sem o toque dele.

```
fidus/
├── server/            API (Python, FastAPI) — roda em Docker no servidor
│   ├── app/
│   │   ├── main.py        endpoints HTTP (app, link público de agendamento, OAuth do Google, convites, assinatura)
│   │   ├── actions.py     envio de e-mails/convites só com autorização (toque em Enviar ou "envia" na conversa)
│   │   ├── i18n.py        tradução dos textos do app (feita uma vez pela IA e guardada) e textos fixos
│   │   ├── agent.py       "cérebro": prompt, laço de ferramentas, registro na aba Atividade
│   │   ├── tools.py       ferramentas de agenda, gastos e e-mail + roteamento + bloqueio por plano
│   │   ├── features.py    lembretes, tarefas, documentos, contas fixas, bom dia, semana, contador, assinaturas
│   │   ├── meetings.py    ata de reunião (transcrição em segundo plano + resumo + tarefas)
│   │   ├── booking.py     página pública de agendamento
│   │   ├── plans.py       planos Essencial / Negócio / Premium e oferta de upgrade
│   │   ├── accounts.py    contas de clientes, login pelo Google, convites, tokens
│   │   ├── llm.py         adaptador de IA (Anthropic ou qualquer API compatível com OpenAI)
│   │   ├── transcribe.py  Whisper local via FFmpeg
│   │   ├── google_client.py, store.py (SQLite), config.py (.env)
│   ├── tests/             pytest — rodar antes de qualquer publicação
│   ├── deploy/            docker-compose.yml + install.sh (Nginx + HTTPS, sem mexer nos outros sites)
│   └── deploy-hetzner.ps1 publica do Windows para o servidor
└── app/               App Android/iOS (Expo / React Native, SDK 57) — um arquivo: App.tsx
    ├── i18n-keys.py       atualiza a lista de textos para tradução (rodar depois de mudar textos do app)
    ├── build-apk.ps1      gera o APK na nuvem da Expo (só quando muda módulo nativo)
    └── update-app.ps1     manda mudanças de App.tsx direto para os celulares (sem APK novo)
```

## Rodar os testes
```bash
cd server
pip install -r requirements.txt pytest httpx
python -m pytest -q
```

## Publicar o servidor
Do Windows (pasta `server`): `powershell -ExecutionPolicy Bypass -File .\deploy-hetzner.ps1`

Ou direto no servidor, com o código em `/tmp/fidus`:
```bash
cp -r /tmp/fidus/server/. /opt/fidus/server/ && bash /opt/fidus/server/deploy/install.sh fidus.148-230-123-44.sslip.io
```
O `install.sh` escolhe uma porta livre, sobe o contêiner, cria só o site do Fidus no Nginx (testa com
`nginx -t` e desfaz se falhar) e pede o HTTPS. O `.env`, o banco e os modelos em `deploy/data` e
`deploy/models` não são tocados.

## Publicar o app
- Mudou só `App.tsx`: pasta `app`, `update-app.ps1`. Os celulares recebem ao abrir o app duas vezes.
- Mudou textos do app: rode `python app/i18n-keys.py` antes. Ele atualiza a lista `I18N_KEYS` do App.tsx e
  `server/app/i18n_keys.json` (o servidor só traduz textos dessa lista), então publique o servidor também.
- Mudou `app.json` ou entrou módulo nativo novo: `build-apk.ps1` e instalar o APK novo.

## Contas de clientes
- Cada cliente entra com o **Google** no app. Sem cadastro aberto (`FIDUS_SIGNUP_OPEN=0`), só entra quem foi
  convidado na aba **Clientes** do app do dono.
- Cada cliente tem **o próprio banco** (`/data/users/<id>/fidus.db`) e a própria pasta de arquivos. O dono usa
  o banco de sempre (`FIDUS_DB_PATH`). Contas, tokens (só o hash), convites e links públicos ficam em `accounts.db`.
- O app recebe um token próprio por cliente; o `FIDUS_APP_TOKEN` continua valendo só para o dono.
- Enquanto o app do Google estiver como "Interno", só contas do domínio da empresa conseguem entrar. Para
  testadores de fora: mudar para "Externo" em modo de teste e adicionar os e-mails deles como usuários de teste.

## Idiomas e moedas
- O app abre no idioma do celular (dá para trocar em Configurações). O servidor traduz os textos uma vez por idioma
  e guarda em `/data/i18n/<idioma>.json`; o app guarda uma cópia. O Fidus responde no idioma em que a pessoa fala.
- Preço dos planos pelo país do perfil: Reino Unido em libra, Europa em euro, resto do mundo em dólar
  (`plans.PRICES`). A cobrança de verdade segue o país do cartão.

## Convide e ganhe
- Cada cliente tem um código (menu › Convide e ganhe). Quem entra com o código ganha 7 dias grátis; quem convidou
  ganha 10% na próxima cobrança quando o amigo paga o 1º mês. Os descontos não somam: um por cobrança.
- `accounts.mark_paid` (1º pagamento), `consume_discount` (a cada cobrança) e `REFERRAL_TRIAL_DAYS` são os pontos que
  a cobrança precisa usar quando entrar no ar.
- `FIDUS_REFERRAL_SIGNUP=1` faz o código valer como convite com o cadastro fechado (máx. 10 contas/código/dia).

## Assinaturas
- Lojas (Google Play, App Store) e site (Stripe) via RevenueCat. O aviso dela vai para `POST /billing/revenuecat`
  com o segredo `FIDUS_BILLING_WEBHOOK_SECRET`. O produto precisa ter o id do plano no nome (ex. `fidus_negocio_monthly`)
  e o app identifica o cliente na loja pelo id dele no Fidus.

## Configuração
Tudo no `server/.env` (modelo em `server/.env.example`). Trocar de IA = mudar `FIDUS_LLM_PROVIDER`.
Reconectar o Google: no app, menu ⋯ › Reconectar Google.

## Regras que não podem quebrar
- **Nada sai em nome do usuário sem confirmação.** E-mails, atas e convites viram ação pendente; o envio
  só acontece em `actions.send_pending`, com trava atômica (um pedido = um envio), por dois caminhos do próprio
  usuário: o toque em Enviar (`/v1/actions/{id}/confirm`) ou a ordem "envia" na conversa, que só vale para
  rascunhos que o app diz estarem na tela e fora de edição. A IA não tem nenhuma ferramenta que envie.
- **A página pública de agendamento não envia e-mails** da conta do usuário (evita spam pela página).
- **OAuth do Google só por link assinado** gerado pelo app.
- Áudio de comandos e de reuniões é apagado depois da transcrição.
- `.env`, `*.db`, recibos e dados nunca entram no Git.
- No servidor da HomB rodam outros agentes: nunca parar contêineres alheios nem editar sites do Nginx que
  não sejam o `fidus.conf`.
