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
│   │   ├── account_data.py exportar e apagar a conta do cliente
│   │   ├── backup.py      backup diário (bancos + arquivos) e idade do último backup
│   │   ├── mailer.py      e-mails do Fidus aos clientes (código de entrada, boas-vindas, assinatura, convite) via Resend
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

## Entrada e segurança
- Entrar com o **Google** ou com **e-mail + código de 6 números** (como no Claude). O código por e-mail só vale para
  contas que não são do Google; conta do Google e a do dono entram só pelo Google (o e-mail avisa isso).
  Máx. 10 erros por e-mail por dia; até 3 códigos válidos ao mesmo tempo; o código só funciona no app que pediu.
- **Um aparelho por conta**: entrar num celular desconecta o anterior ("sua conta foi aberta em outro aparelho").
  A aba Clientes mostra trocas de aparelho e IPs diferentes no mês (sinal de conta dividida).
  Configurações › "Sair de todos os aparelhos".
- **Trava com digital ou rosto** (opcional, APK com `expo-local-authentication`): pede a digital ao abrir e ao
  voltar depois de 30 s fora. Se a digital for removida do celular, a trava desliga sozinha.
- E-mails automáticos pelo Resend (`FIDUS_RESEND_API_KEY`, `FIDUS_EMAIL_FROM` com domínio verificado): código de
  entrada, boas-vindas (só conta nova), assinatura (ativa, renovada, falha, cancelada, terminou) e convite aceito.

## Custo de IA e uso justo
- Cada chamada à IA grava tokens e custo no banco do cliente (`store.add_usage`, preços em `llm.PRICES`).
  O dono vê o custo do mês por cliente na aba Clientes e em `GET /v1/admin/costs`.
- Economia: as regras e as ferramentas ficam em cache na Anthropic (custam 10% nas chamadas seguintes; a data e
  o perfil vão depois do cache), e telas/textos fixos são traduzidos pelo modelo barato (`FIDUS_LLM_MODEL_LIGHT`).
- Uso justo: cliente que passa de `FIDUS_FAIR_USE_DAILY_USD` (padrão US$ 5) num dia recebe um aviso educado e
  volta no dia seguinte. O dono não tem limite.

## Dados do cliente
- Configurações › **Exportar meus dados**: .zip com tudo em JSON + recibos e documentos (sem as chaves do Google).
- Configurações › **Apagar minha conta** (digitar APAGAR): encerra acessos, desconecta o Google, desliga o link
  público, tira e-mail e nome da conta e move a pasta para `/data/deleted`, destruída de vez após 30 dias.
  Manda e-mail lembrando de cancelar a assinatura na loja.

## Backup e monitoramento
- Backup automático todo dia às 03:30 UTC em `deploy/data/backups` (últimos 14), com cópia segura dos bancos.
  Na mão: `docker exec fidus_server python -m app.backup` ou `POST /v1/admin/backup`. Falhou: e-mail para o dono.
- **Cópia fora do servidor** (recomendado antes de vender): sincronizar `deploy/data/backups` com um armazenamento
  externo (ex. Hetzner Storage Box com rclone).
- `GET /health` responde 503 se o backup estiver atrasado (+36 h), se falhou ou se o disco tiver menos de 2 GB.
  Cadastre esse endereço num monitor grátis (ex. UptimeRobot) para receber alerta se o Fidus cair.

## Painel da empresa (/admin)
- Endereço: `https://<servidor>/admin` (hoje `https://fidus.148-230-123-44.sslip.io/admin`). Em inglês britânico,
  com botão para português.
- Entrada: no app, menu › Painel da empresa › gerar código (8 letras, vale 5 min, uma vez). Sessão de 12 h no
  navegador. Só aparece para o dono (`FIDUS_OWNER_EMAIL`) e para a equipe cadastrada.
- Telas: Sistema (saúde, erros, backup, disco), HEART (satisfação 👍/👎 e nota 0–10, uso, adoção, retenção, sucesso
  das tarefas), Negócio (receita mensal, planos, custo de IA), Clientes (trocar plano, pausar) e Equipe.
- Papéis: owner (tudo), admin (tudo menos mexer em outros admins), support (sistema, HEART, clientes sem valores),
  finance (negócio e clientes com valores). Ninguém da equipe vê conversas, e-mails ou gastos dos clientes; toda
  ação fica registrada.
- Medições em `metrics.db` (só ids, tempos e resultados; apagadas após 180 dias).

## Links, planilhas e escalas (Connecteam)
- O Fidus abre links que vierem no pedido, num e-mail que ele leu ou salvos com nome (ex. "agenda dos turnos").
  Só endereços públicos da internet; páginas de login não funcionam (ele nunca usa senha).
- Planilhas Google: ler, adicionar linhas e alterar células, só em planilhas cujo link a pessoa mandou ou salvou
  ("salva essa planilha como Tarefas"). Cada mudança aparece na Atividade com Desfazer.
- Para ligar: no Google Cloud, ativar a **Google Sheets API** e incluir o escopo
  `https://www.googleapis.com/auth/spreadsheets` em Acesso a dados; depois cada pessoa toca em Reconectar Google.
- Connecteam: usar o link de calendário (iCal) das escalas; o Fidus lê turnos e notas e pode lançar na planilha.

## Carteiras, voz e botão parar (v0.9.5)
- Carteiras: cada empresa/conta tem nome e moeda (ex. "Pessoal BR" em BRL). Tela de gastos com filtro por carteira,
  totais na moeda de cada uma e exportação para o contador por carteira. Criar: no app (+ Carteira) ou pedindo ao
  Fidus. Tocar e segurar remove (os gastos antigos ficam guardados). Mais de uma carteira: plano Negócio.
- Áudio gravado é respondido também em voz alta (Configurações › Responder áudios em voz alta; precisa do APK com
  expo-speech). No modo conversa, se demorar, o Fidus diz "um instante".
- Cumprimentos e agradecimentos vão para o modelo leve (mais rápido e barato).
- Enter na caixa de texto só pula linha; envia pelo botão. Enquanto o Fidus pensa, o botão vira "parar"
  (`POST /v1/cancel`): ele não executa mais nada daquele pedido; o que já fez fica na Atividade com Desfazer.

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
- Lojas (Google Play, App Store) e site (Stripe) via RevenueCat. O app compra pela loja (`react-native-purchases`,
  precisa do APK novo) com o cliente identificado pelo id dele no Fidus; a RevenueCat avisa o servidor em
  `POST /billing/revenuecat` (segredo `FIDUS_BILLING_WEBHOOK_SECRET`) e o plano muda sozinho.
- Para ligar:
  1. Google Play Console: publicar o app (pode ser teste fechado) e criar 3 assinaturas com o id do plano no nome:
     `fidus_essencial`, `fidus_negocio`, `fidus_premium`, cada uma com os planos-base `mensal` e `anual` e os preços
     por país (libra, euro, dólar). Oferta de 7 dias grátis com a etiqueta `convite` (só quem veio por convite vê).
  2. RevenueCat: ligar a Play, criar a oferta "default" com os pacotes mensal e anual de cada plano, cadastrar o
     webhook acima com o segredo, copiar a chave pública do SDK (`goog_...`).
  3. No `.env` do servidor: `FIDUS_REVENUECAT_ANDROID_KEY` e `FIDUS_BILLING_WEBHOOK_SECRET`. Gerar e instalar o APK novo.
- Sem as chaves, o botão de assinar mostra "em breve" (como antes).

## Site
- `site/landing.dc.html` (cópia do site no Claude Design). Idioma e moeda do visitante; botões da Google Play e da
  App Store conforme o celular (os links entram nas Tweaks do site: `playStoreUrl`, `appStoreUrl`). Loja sem link =
  lista de espera. O cadastro acontece no app.

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
