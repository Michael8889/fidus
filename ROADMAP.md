# Fidus — caminho até a versão vendável

Atualize marcando [x] o que ficou pronto. Quem faz: **Você** (Mike) ou **Claude**.

## Fase 0 — Agora (esta semana)
- [x] **Você**: instalar a versão nova (servidor: `deploy-hetzner.ps1`; app: `update-app.ps1`)
- [ ] **Você**: instalar a v0.9.5 (servidor + `update-app.ps1`) e gerar/instalar o APK novo (`build-apk.ps1`) para a voz
- [ ] **Você**: cadastrar o endereço `/health` do servidor num monitor grátis (UptimeRobot) para alerta se cair
- [ ] **Você**: convidar sua esposa (menu › Clientes) e usar os dois por 1–2 semanas, anotando o que der errado
- [ ] **Claude**: corrigir o que aparecer no uso real
- [x] **Claude**: painel da empresa (/admin), links em e-mails, planilhas Google e escalas do Connecteam (v0.9.4)
- [ ] **Você**: Google Cloud: ativar a Google Sheets API + escopo de planilhas; todos tocam em Reconectar Google

## Anotado para a próxima versão (juntar e rodar uma vez só)
- (vazio)

## Fase 1 — Empresa e contas (em paralelo)
- [ ] **Você**: conta bancária da empresa
- [ ] **Você**: registro no ICO (proteção de dados, taxa anual pequena)
- [x] **Você**: busca de marca no Reino Unido (08/10): nenhuma "FIDUS" viva em software (classes 9/42); atenção a
      "FEEDUS" (classes 35/42, parecida no som)
- [ ] **Você**: busca na União Europeia (TMview), pedir registro da marca FIDUS (UK, classes 9 e 42) e comprar o domínio
- [ ] **Você**: abrir a empresa com nome aceito (ex. "Fidus Labs Ltd" ou nome neutro; "FIDUS LIMITED" foi recusado
      por já existir "FIDUS UK LTD")
- [ ] **Você**: conta Google Play Console no nome da empresa (US$ 25)
- [ ] **Você**: conta Resend + verificar o domínio → liga os e-mails e a entrada por e-mail (`.env`)
- [ ] **Você**: conta RevenueCat + assinaturas na Play (passo a passo no README › Assinaturas)

## Fase 2 — Google libera o Gmail para o público
- [ ] **Claude**: política de privacidade e termos de uso no site (revisão de um advogado recomendada)
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
- [ ] iPhone (Apple Developer, US$ 99/ano) e App Store
- [ ] Outlook / Microsoft 365 (muitas empresas no Reino Unido usam)
- [ ] Página de agendamento em vários idiomas
- [ ] Lançamento aberto e anúncios

## Já feito
- [x] v0.9.5: carteiras nos gastos (moeda própria, filtro, exportar por carteira), áudio respondido em voz alta,
      voz mais rápida, letras maiores, menu traduzido por inteiro, Enter não envia, botão parar
- [x] App Android com voz, agenda, e-mail com aprovação, gastos e recibos, documentos, tarefas, atas, link de
      agendamento, contador, pesquisa na web, atividade com desfazer
- [x] Contas de clientes, planos com preço local, convide e ganhe, assinatura pela loja (código pronto)
- [x] Segurança: um aparelho por conta, entrada por Google ou código no e-mail, trava com digital
- [x] Idiomas (app, Fidus e site), site com lojas
- [x] Custo de IA medido por cliente + economia + uso justo; exportar e apagar conta; backup diário e alerta
