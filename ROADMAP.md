# Fidus — caminho até a versão vendável

Atualize marcando [x] o que ficou pronto. Quem faz: **Você** (Mike) ou **Claude**.

## Fase 0 — Agora (esta semana)
- [x] **Você**: instalar a versão nova (servidor: `deploy-hetzner.ps1`; app: `update-app.ps1`)
- [ ] **Você**: instalar a v0.10 (servidor + `update-app.ps1`) e gerar/instalar o APK novo (`build-apk.ps1`)
- [ ] **Você**: no `server\.env`: `FIDUS_COMPANY_ADDRESS`, `FIDUS_SUPPORT_EMAIL`, `FIDUS_MENTOR_BOOKING_URL`
- [ ] **Você**: Google Cloud: ativar a Cloud Text-to-Speech API, criar chave restrita e pôr `FIDUS_GOOGLE_TTS_KEY` no `server\.env`
- [ ] **Você**: cadastrar o endereço `/health` do servidor num monitor grátis (UptimeRobot) para alerta se cair
- [ ] **Você**: convidar sua esposa (menu › Clientes) e usar os dois por 1–2 semanas, anotando o que der errado
- [ ] **Claude**: corrigir o que aparecer no uso real
- [x] **Claude**: painel da empresa (/admin), links em e-mails, planilhas Google e escalas do Connecteam (v0.9.4)
- [ ] **Você**: Google Cloud: ativar a Google Sheets API + escopo de planilhas; todos tocam em Reconectar Google

## Anotado para a próxima versão (juntar e rodar uma vez só)
- Site: página "Membro fundador" (lista de espera com código aplicado) e página "Seja parceiro" (candidatura)
- Voz ainda mais rápida conforme a medição do painel (começar a falar antes de terminar, etc.)
- Chamar o Fidus com a tela bloqueada, para anotação rápida com confirmação por voz:
  - link direto que abre já no modo conversa (fidus://falar) + atalho de tela inicial
  - Android: bloco nas Configurações rápidas (desce a barra, toca "Fidus", fala) e botão na notificação; no
    Samsung, botão lateral (2 toques) abrindo o Fidus direto no modo conversa
  - iPhone: atalho da Siri ("E aí Siri, anota no Fidus …") que funciona com a tela bloqueada, mais botão de Ação
    (iPhone 15 Pro+) e controle na Central de Controle
  - modo "anotação rápida" na tela bloqueada: só CRIA (lembrete, tarefa, gasto, nota) e confirma falando; para LER
    agenda, e-mails ou gastos, pede para desbloquear (privacidade)
  - "Ei Fidus" sempre ouvindo: no iPhone a Apple não permite; no Android dá, mas gasta bateria e exige licença
    paga do detector de palavra; deixar para depois

## Funil Fidus → mentoria (HARVEST Framework) — discreto, por e-mail (nada de mentoria dentro do app)
- [ ] **Você**: conteúdo com a sua imagem (@michael.gbd) mostrando o Fidus; CTA para baixar com o código MIKE
- [x] **Claude**: nas boas-vindas, UMA pergunta opcional: "Quero receber dicas de gestão e novidades do Fidus por e-mail"
      (LGPD/GDPR/PECR); tudo sai pelo Fidus, sem citar a HARVEST; a lista fica na Fidus Labs; link de descadastro
- [x] **Claude**: newsletter "Notas do Mike" pelo Resend: boas-vindas + sequência automática (dica de gestão +
      dica de uso do Fidus; a cada 3–4 e-mails, convite para o diagnóstico da mentoria); só para quem marcou a caixa;
      nunca usar e-mails, agenda ou gastos do cliente para segmentar
- [x] **Claude**: painel › aba Leads (interna) + CSV
- [ ] **Você**: revisar os textos em `server/app/newsletter.json` com a sua voz
- [x] **Você**: oferta de entrada = diagnóstico gratuito de 30 min; a mentoria é oferecida pelo Fidus (sem citar a HARVEST)

## Boas-vindas do Fidus (setup em conversa, primeiro uso)
- [x] **Claude**: perguntas automáticas no 1º uso (puláveis, por voz ou texto): nome, perfil (autônomo/empresa/
      ambos), carteiras e moedas, cidade/fuso, prioridades, estilo de resposta, horário do "bom dia"; depois
      expectativas (o que faz, aprovação antes de enviar, Desfazer, privacidade) e uma primeira tarefa real;
      última pergunta: dicas por e-mail (opt-in). Respostas viram perfil e carteiras automaticamente
- [x] **Claude**: as perguntas ADAPTADAS a cada idioma, não traduzidas ao pé da letra: exemplos locais (UK: "£30 of
      petrol", "HomB in pounds"; PT-PT: "telemóvel", "combustível", euros; BR: reais, "gasolina"), moeda e cidade do
      país do celular como sugestão, tratamento certo (você / tu / you); revisar EN, PT-BR, PT-PT e ES à mão

## Parceiros (criadores)
- [x] **Claude**: códigos de criador, desconto no 1º mês, 10% por 12 meses, aba Parceiros no painel (v0.10)
- [ ] **Você**: na Play, oferta de desconto no 1º mês com a etiqueta `parceiro` em cada assinatura
- [ ] **Você**: listar 5 a 10 criadores (PT, BR no Reino Unido/Portugal); Claude prepara abordagem e contrato simples

## Fase 1 — Empresa e contas (em paralelo)
- [ ] **Você**: conta bancária da empresa
- [ ] **Você**: registro no ICO (proteção de dados, taxa anual pequena)
- [x] **Você**: busca de marca no Reino Unido (08/10): nenhuma "FIDUS" viva em software (classes 9/42); atenção a
      "FEEDUS" (classes 35/42, parecida no som)
- [ ] **Você**: busca na União Europeia (TMview), pedir registro da marca FIDUS (UK, classes 9 e 42) e comprar o domínio
- [x] **Você**: abrir a empresa: **Fidus Labs Limited** (número 17510962, registrada na Companies House em 09/10/2026)
- [ ] **Você**: conta Google Play Console no nome da empresa (US$ 25)
- [ ] **Você**: conta Resend + verificar o domínio → liga os e-mails e a entrada por e-mail (`.env`)
- [ ] **Você**: conta RevenueCat + assinaturas na Play (passo a passo no README › Assinaturas)

## iPhone (em paralelo com a Play)
- [ ] **Você**: Apple Developer Program como empresa (US$ 99/ano; usa o MESMO D-U-N-S da Play; leva de dias a ~2 semanas)
- [ ] **Claude**: ajustes de iPhone: entrar com a Apple (exigido pela Apple quando há entrar com Google), gravação
      de reunião com a tela apagada, permissões e textos, chave da RevenueCat para iOS, build pela nuvem da Expo
      (não precisa de Mac)
- [ ] **Você**: App Store Connect: criar o app e as 3 assinaturas (mesmos ids da Play), TestFlight para testar
- [ ] **Você + Claude**: revisão da Apple (1–3 dias; costuma pedir conta de teste e vídeo das funções)

## Fase 2 — Google libera o Gmail para o público
- [x] **Claude**: política de privacidade e termos de uso (`/privacy`, `/terms`, EN e PT; revisão de advogado recomendada)
- [ ] **Você**: no Google Cloud, mudar o app para "Externo", preencher a verificação e contratar a avaliação de
      segurança CASA (exigida para Gmail; leva semanas — começar assim que a empresa existir)
- [ ] **Você + Claude**: enquanto isso, beta pago fechado com até 100 usuários de teste

## Fase 3 — Produção
- [ ] **Claude + Você**: servidor próprio do Fidus (separado da HomB) e backup fora do servidor (Storage Box)
- [ ] **Você**: gerar o APK final (`build-apk.ps1`) e publicar na Play (teste fechado → produção)
- [ ] **Claude**: medir o custo de IA por cliente por 2–4 semanas e ajustar preço/limite de uso justo
- [ ] **Claude**: versão web para o lançamento (Windows e Mac pelo navegador, instalável como app, mesmo código do
      celular), entrada com QR code lido pelo celular como o WhatsApp Web; só planos Negócio e Premium
      (`plans.FEATURE_MIN`); regra de aparelhos vira 1 celular + 1 computador por conta
- [ ] **Você**: colocar os links das lojas no site (Tweaks) e o domínio no lugar do endereço provisório

## Fase 4 — Crescer
- [ ] Outlook / Microsoft 365 (muitas empresas no Reino Unido usam)
- [ ] Página de agendamento em vários idiomas
- [ ] Lançamento aberto e anúncios

## Já feito
- [x] v0.10: boas-vindas em conversa, dicas por e-mail + Leads, parceiros, português de Portugal, privacidade e termos,
      exportar gastos para o próprio e-mail, medição da voz, cartão de e-mail com o visual de antes
- [x] v0.9.9: visual limpo (neutros, preto como cor de ação, ícones de linha, resposta sem balão, modo escuro grafite)
- [x] v0.9.6: transcrição no celular (modo conversa mais rápido) e voz natural do Google (feminina/masculina)
- [x] v0.9.5: carteiras nos gastos (moeda própria, filtro, exportar por carteira), áudio respondido em voz alta,
      voz mais rápida, letras maiores, menu traduzido por inteiro, Enter não envia, botão parar
- [x] App Android com voz, agenda, e-mail com aprovação, gastos e recibos, documentos, tarefas, atas, link de
      agendamento, contador, pesquisa na web, atividade com desfazer
- [x] Contas de clientes, planos com preço local, convide e ganhe, assinatura pela loja (código pronto)
- [x] Segurança: um aparelho por conta, entrada por Google ou código no e-mail, trava com digital
- [x] Idiomas (app, Fidus e site), site com lojas
- [x] Custo de IA medido por cliente + economia + uso justo; exportar e apagar conta; backup diário e alerta
