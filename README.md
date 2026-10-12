# Fidus

Produto da **Fidus Labs Limited** (Inglaterra e País de Gales, empresa nº 17510962).

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
cp -r /tmp/fidus/server/. /opt/fidus/server/ && bash /opt/fidus/server/deploy/install.sh app.heyfidus.com 'heyfidus.com www.heyfidus.com fidus.148-230-123-44.sslip.io'
```
Domínio: heyfidus.com no Cloudflare (DNS only). `app.heyfidus.com` = servidor e painel; `heyfidus.com` = página
simples da empresa (rota `/`) até o site completo; e-mails saem de `ola@heyfidus.com` (Resend, Irlanda) e
qualquer endereço @heyfidus.com chega no e-mail do Mike (Cloudflare Email Routing). O app troca sozinho o
endereço antigo salvo pelo novo assim que o novo responde.

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
- Endereço: `https://<servidor>/admin` (hoje `https://app.heyfidus.com/admin`; o endereço antigo sslip.io continua respondendo). Em inglês britânico,
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
- Áudio gravado pode ser respondido também em voz alta (desligado por padrão; Configurações › Responder áudios em voz alta; precisa do APK com
  expo-speech). No modo conversa, se demorar, o Fidus diz "um instante".
- Cumprimentos e agradecimentos vão para o modelo leve (mais rápido e barato).
- Enter na caixa de texto só pula linha; envia pelo botão. Enquanto o Fidus pensa, o botão vira "parar"
  (`POST /v1/cancel`): ele não executa mais nada daquele pedido; o que já fez fica na Atividade com Desfazer.

## Voz natural e transcrição no celular (v0.9.6)
- Modo conversa: a fala é transcrita no próprio celular enquanto a pessoa fala (expo-speech-recognition, precisa do
  APK novo). Sem o módulo ou se falhar, volta para a gravação + Whisper no servidor.
- Resposta falada na voz natural do Google Text-to-Speech, que vem junto da resposta (`speech_audio`, MP3). Frases fixas
  ("Pode falar.", "Um instante."...) em `POST /v1/tts`, guardadas em `/data/tts-cache`. Sem chave: voz do celular.
- Ligar: no Google Cloud (mesmo projeto) ativar a "Cloud Text-to-Speech API" (precisa de faturamento ativo no projeto),
  criar uma chave de API restrita a essa API e colocar em `FIDUS_GOOGLE_TTS_KEY` no `server/.env`.
  `FIDUS_TTS_TIER`: wavenet (padrão; 4 milhões de letras grátis/mês, depois US$ 4/milhão), neural2 (US$ 16) ou
  chirp3 (a mais natural, US$ 30; 1 milhão grátis). O custo entra no uso de cada cliente (painel e uso justo).
- Configurações › Voz do Fidus: feminina ou masculina.

## Boas-vindas, dicas por e-mail, parceiros, pt-PT e páginas legais (v0.10)
- **Boas-vindas:** conta nova (sem conversa) recebe 8 perguntas curtas, puláveis, por voz ou texto
  (`onboarding.py`): nome, perfil, carteiras e moedas, cidade/fuso, prioridades, estilo de resposta, horário do
  bom dia e, por último, dicas por e-mail. Textos escritos à mão em PT-BR, PT-PT, EN e ES; outros idiomas, adaptados
  pela IA uma vez. Configurações › Refazer as boas-vindas.
- **Dicas por e-mail ("Notas do Mike"):** só para quem aceitou (boas-vindas ou Configurações › Dicas por e-mail).
  Sequência em `server/app/newsletter.json` (editável: dia e texto por idioma), enviada pelo Resend, com
  descadastro em todo e-mail. O convite do diagnóstico usa `FIDUS_MENTOR_BOOKING_URL`. Painel › Leads (+ CSV).
- **Parceiros (criadores):** painel › Parceiros › criar código (ex. ANA). Seguidor entra com o código: desconto
  no 1º mês (oferta com a etiqueta `parceiro` na Play: criar em cada assinatura um plano-base com oferta de
  desconto no 1º período e etiqueta `parceiro`). Criador ganha 10% de cada cobrança paga por 12 meses (webhook
  da RevenueCat); reembolso estorna; "Marcar como pago" quando você paga.
- **Português de Portugal:** idioma próprio (`pt-pt`) no app, no Fidus e na voz.
- **Privacidade e termos:** `/privacy` e `/terms` (EN e PT), com Fidus Labs Limited nº 17510962. Preencha
  `FIDUS_COMPANY_ADDRESS` e `FIDUS_SUPPORT_EMAIL`. Use esses links na Play Console e na verificação do Google.
  Recomendado: revisão de um advogado.
- **Exportar gastos para o próprio e-mail:** Gastos › Enviar para o meu e-mail (pelo e-mail do Fidus, com anexo).
- **Velocidade da voz:** painel › Sistema mostra a mediana de transcrição · IA · voz natural.

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

## Beta só com convite (v0.16)
- Site: quem entra na lista ganha o lugar na fila e um link próprio (`heyfidus.com/?ref=L...`); cada amigo que entra
  pelo link sobe a pessoa 10 lugares. A página `/beta?t=...` mostra a posição (ou, para convidado, o download).
- Painel `/admin` › Site › Beta: "Ver quem" e "Convidar" os primeiros N da fila (só Android enquanto não há iPhone).
  O convidado recebe o e-mail com o link do APK (`FIDUS_APP_DOWNLOAD_URL`) e entra com aquele e-mail.
- Cada membro tem `FIDUS_BETA_INVITES` convites (3): quem entra pelo link dele (app › Convide e ganhe, ou o site com
  o código dele) entra na hora, sem fila. Quem entra pelo beta fica no plano `FIDUS_BETA_PLAN` (Premium).
- No fim do beta: `FIDUS_BETA_INVITES=0` volta ao programa de indicação normal.

## Premium: contador e mais 1 pessoa (v0.17)
- Configurações › Contador e mais 1 pessoa (só o titular, plano Premium ou Global). Os convites saem pelo e-mail do
  Fidus depois do toque em Enviar; a IA não tem ferramenta para isso (`app/team.py`).
- Contador: portal web só de leitura em `/contabilista` (`app/accountant_portal.py` + `accountant.html`), com código
  de 6 números por e-mail e sessão de 12 h. Vê despesas, IVA, NIF, categorias do e-Fatura, fotos dos recibos e exporta
  Excel + recibos. Não vê agenda, e-mails nem conversas. O cliente vê o último acesso e corta quando quiser.
- 2.ª pessoa: entra com o próprio login e abre o banco do titular (`member_of` em `users`), com conversas só dela.
  Bloqueado para ela: e-mails e Google do titular, envios, plano, ligações, país, definições, conta, convites
  (`main.MEMBER_DENY`, `tools.MEMBER_BLOCKED`). Se o titular sair do Premium, ela perde o acesso na hora.
- Faturação a clientes saiu do plano: em Portugal só software certificado pela AT pode emitir faturas. Se voltar,
  será ligando a um faturador certificado (InvoiceXpress, Moloni, Vendus).

## Teste grátis e assinatura pelo Stripe (v0.18)
- Conta nova do beta (ou por indicação) tem `FIDUS_TRIAL_DAYS` (7) dias grátis no plano do convite. Acabou sem
  assinar: o Fidus responde com o cartão de assinar (sem gastar IA); os dados continuam lá. Convites da equipe e o dono
  não têm teste. Estado em `plans.access()`: active / trial / expired.
- Assinar: o app abre o Stripe Checkout (`POST /v1/billing/checkout`, mensal ou anual, preço da moeda do cliente).
  Quem assina durante o teste não perde os dias que faltam (1.ª cobrança no fim do teste). Trocar cartão ou cancelar:
  `POST /v1/billing/portal`. Aviso do Stripe em `POST /billing/stripe` (assinatura conferida, aviso repetido ignorado).
- No Stripe: chave secreta e segredo do webhook no `.env`; webhook para `https://app.heyfidus.com/billing/stripe` com
  `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`;
  ativar o Customer portal. Não precisa criar produtos: os preços vêm de `plans.PRICES`.
- Beta de Portugal: os primeiros `FIDUS_BETA_AUTO` (100) do site em pt-PT com Android entram sozinhos; o resto espera
  a turma no painel.

## Assinaturas
- Lojas (Google Play, App Store) e site (Stripe) via RevenueCat. O app compra pela loja (`react-native-purchases`,
  precisa do APK novo) com o cliente identificado pelo id dele no Fidus; a RevenueCat avisa o servidor em
  `POST /billing/revenuecat` (segredo `FIDUS_BILLING_WEBHOOK_SECRET`) e o plano muda sozinho.
- Para ligar:
  1. Google Play Console: publicar o app (pode ser teste fechado) e criar 3 assinaturas com o id do plano no nome:
     `fidus_essencial`, `fidus_negocio`, `fidus_premium`, `fidus_global`, cada uma com os planos-base `mensal` e `anual` e os preços
     por país (libra, euro, dólar). Oferta de 7 dias grátis com a etiqueta `convite` (só quem veio por convite vê).
  2. RevenueCat: ligar a Play, criar a oferta "default" com os pacotes mensal e anual de cada plano, cadastrar o
     webhook acima com o segredo, copiar a chave pública do SDK (`goog_...`).
  3. No `.env` do servidor: `FIDUS_REVENUECAT_ANDROID_KEY` e `FIDUS_BILLING_WEBHOOK_SECRET`. Gerar e instalar o APK novo.
- Sem as chaves, o botão de assinar mostra "em breve" (como antes).

## Pasta no computador do Mike
- `Downloads\fidus-v0.2\fidus` (app, server, site) e, ao lado, `fidus-app` (projeto Expo com o projectId do
  EAS: nunca recriar). Extrair cada zip novo em `Downloads\fidus-v0.2\fidus` com `Expand-Archive ... -Force`.

## Roteador de IA (custo)
- `FIDUS_LLM_MODEL_CHEAP` (ex. `gemini:gemini-3.8-flash`): agenda, gasto, lembrete, tarefa e consultas curtas vão
  nele; e-mail, várias ações, foto, pesquisa, textos longos e conversa com rascunho aberto ficam no
  `FIDUS_LLM_MODEL` (Sonnet). Se o barato erra uma ferramenta, "inventa" que fez ou dá voltas, o forte assume
  no mesmo pedido. Se um modelo falha (ex. crédito acabou), o outro responde. Teste: `docker exec fidus_server
  python -m app.checkai`. Regras em `agent.route` (testes em `tests/test_router.py`).

## Conversa em tempo real (v0.11)
- APK com `react-native-webrtc` + `FIDUS_OPENAI_API_KEY`: o modo conversa liga direto com a IA de voz da OpenAI
  (`gpt-realtime-2.1-mini`, ~US$ 0,02/min). O servidor cria a chave temporária (10 min) com regras, contexto e
  ferramentas (`realtime.py`), executa as ferramentas (`/v1/realtime/tool`, mesmas regras do chat) e guarda as
  falas (`/v1/realtime/turn`) e o custo (`/v1/realtime/usage`). "Envia" falado vai para `/v1/realtime/command`
  (actions.handle_command, só rascunho na tela); a IA de voz não envia nada.
- Sem chave, APK antigo ou falha na conexão: o app usa o modo conversa normal (transcrição no celular + IA + voz).

## Site
- No ar em heyfidus.com: `python site/build_site.py` gera `server/app/static/site.html` a partir do desenho;
  o servidor serve em `/`. Lojas: `FIDUS_PLAY_STORE_URL` / `FIDUS_APP_STORE_URL` no `.env` (vazio = lista de espera,
  que grava em `waitlist` no accounts.db via `/v1/site/waitlist`).
- `site/landing.dc.html` (cópia do site no Claude Design). Idioma e moeda do visitante; botões da Google Play e da
  App Store conforme o celular (os links entram nas Tweaks do site: `playStoreUrl`, `appStoreUrl`). Loja sem link =
  lista de espera. O cadastro acontece no app.
- Backend do site (`server/app/site_forms.py`): lista de espera manda 1 e-mail de confirmação (pt/en/es) com link
  para sair (`/lista/sair`, pede um toque antes de apagar); guarda o plano clicado e o código de parceiro da URL
  (`heyfidus.com/?ref=ANA`). Página `/parceiros` (`/partners`) com formulário: o pedido vai para o painel e para o
  e-mail de suporte. Painel › Site: lista, CSV, pedidos de parceria (aprovar/recusar) e o botão "Avisar a lista que o
  app chegou na loja" (um e-mail por pessoa, só para a loja do celular dela, nunca repete).
- Streaming ("Fidus escreve"): o app mostra a resposta sendo escrita e o que o Fidus está fazendo
  (`GET /v1/partial/{request_id}`, alimentado por `llm.STREAM`).

## Outlook / Microsoft 365
- `server/app/ms_client.py`: conexão com a Microsoft (OAuth com PKCE) e adaptadores do Microsoft Graph no MESMO formato
  das bibliotecas do Google. Com o Outlook conectado, `google_client.calendar()`/`gmail()` devolvem os adaptadores e
  todas as funções (agenda, lembretes, convites, link de agendamento, e-mails) funcionam sem mudar nada nelas.
  Planilhas continuam só no Google.
- Quem usa Outlook entra com e-mail (código) e conecta em Configurações › Outlook (ou no aviso do chat).
- Gmail e Outlook podem ficar os DOIS ligados (v0.15.1): a busca de e-mail olha as duas caixas (ids do Outlook com
  prefixo `ms:`), a resposta sai da caixa que recebeu e o e-mail novo sai da principal (ou da que o cliente pedir).
  A agenda vem de uma só (`kv mail_provider`), escolhida no app (toque no Google ou no Outlook › Usar a agenda...).
  Conectar um não desliga o outro.
- Envio: igual ao Gmail, só depois da confirmação (o MIME pronto vai por `/me/sendMail`).
- Configuração: app no Microsoft Entra (contas de qualquer empresa + pessoais), redirect
  `https://app.heyfidus.com/auth/microsoft/callback`, permissões delegadas `User.Read Calendars.ReadWrite Mail.Read
  Mail.Send offline_access openid profile email`, e `FIDUS_MS_CLIENT_ID` / `FIDUS_MS_CLIENT_SECRET` no `.env`.
  Para clientes de empresa conseguirem autorizar: verificação de editor (Microsoft AI Cloud Partner Program).

## País do pacote, Portugal e Reino Unido (v0.15)
- Cada plano vale para UM país: Portugal (EUR), Reino Unido (GBP) ou Brasil (BRL). O plano Global (acima do
  Premium; €49,90 / £44,90 / $54,90) vale para os três. O dono fica no Global (`FIDUS_PLAN=global`).
- `app/countries.py`: país escolhido em Configurações › País do pacote (`POST /v1/countries`, vai para a Atividade);
  sem escolha, o país do celular. O país fica FIXO depois da primeira escolha ou da assinatura (`countries.freeze()`
  no webhook): trocar de país só mudando para o Global. No Global, o cliente escolhe à vontade entre os três. A IA só recebe as ferramentas do país (`tools.available_tools()`),
  e o `tools.run` bloqueia as outras com a oferta do Global (`multi_country`). Formas de pagamento e moedas de
  carteira seguem o país; gasto avulso em viagem noutra moeda continua livre.
- Portugal (`app/portugal.py`): NIF nas faturas, categorias do e-Fatura/IRS, calendário fiscal, MB Way e Multibanco.
- Reino Unido (`app/uk.py`): confere o VAT number dos recibos (quem é VAT registered) e cria os lembretes de Self
  Assessment, pagamentos por conta, MTD for Income Tax, VAT, Corporation Tax, Companies House e PAYE.

## Segurança dos dados dos clientes
- As conexões com Google e Microsoft (chaves de acesso) ficam criptografadas no banco de cada cliente
  (`app/crypto.py`, Fernet). A chave mestra fica em `/opt/fidus/server/deploy/keys/data.key` no servidor (criada
  sozinha no primeiro uso, só o dono lê), fora de `/data` e dos backups; o deploy nunca sobrescreve essa pasta.
- Guarde uma cópia dessa chave fora do servidor (ex. gerenciador de senhas). Sem ela, um backup restaurado funciona,
  mas os clientes precisam reconectar Google/Outlook.

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
