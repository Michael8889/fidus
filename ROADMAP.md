# Fidus — caminho até a versão vendável

Atualize marcando [x] o que ficou pronto. Quem faz: **Você** (Mike) ou **Claude**.

## Fase 0 — Agora (esta semana)
- [ ] **Você**: instalar a versão nova (servidor: `deploy-hetzner.ps1`; app: `update-app.ps1`)
- [ ] **Você**: cadastrar o endereço `/health` do servidor num monitor grátis (UptimeRobot) para alerta se cair
- [ ] **Você**: convidar sua esposa (menu › Clientes) e usar os dois por 1–2 semanas, anotando o que der errado
- [ ] **Claude**: corrigir o que aparecer no uso real

## Fase 1 — Empresa e contas (em paralelo)
- [ ] **Você**: abrir a Ltd no Reino Unido (Companies House) e a conta bancária da empresa
- [ ] **Você**: registro no ICO (proteção de dados, taxa anual pequena)
- [ ] **Você**: confirmar o nome (busca de marca no UKIPO/EUIPO) e comprar o domínio definitivo
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
- [ ] **Você**: colocar os links das lojas no site (Tweaks) e o domínio no lugar do endereço provisório

## Fase 4 — Crescer
- [ ] iPhone (Apple Developer, US$ 99/ano) e App Store
- [ ] Outlook / Microsoft 365 (muitas empresas no Reino Unido usam)
- [ ] Página de agendamento em vários idiomas
- [ ] Lançamento aberto e anúncios

## Já feito
- [x] App Android com voz, agenda, e-mail com aprovação, gastos e recibos, documentos, tarefas, atas, link de
      agendamento, contador, pesquisa na web, atividade com desfazer
- [x] Contas de clientes, planos com preço local, convide e ganhe, assinatura pela loja (código pronto)
- [x] Segurança: um aparelho por conta, entrada por Google ou código no e-mail, trava com digital
- [x] Idiomas (app, Fidus e site), site com lojas
- [x] Custo de IA medido por cliente + economia + uso justo; exportar e apagar conta; backup diário e alerta
