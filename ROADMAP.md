# Fidus — caminho até a versão vendável

Atualize marcando [x] o que ficou pronto. Quem faz: **Você** (Mike) ou **Claude**.

## Fase 0 — Agora (esta semana)
- [x] **Você**: instalar a versão nova (servidor: `deploy-hetzner.ps1`; app: `update-app.ps1`)
- [ ] **Você**: cadastrar o endereço `/health` do servidor num monitor grátis (UptimeRobot) para alerta se cair
- [ ] **Você**: convidar sua esposa (menu › Clientes) e usar os dois por 1–2 semanas, anotando o que der errado
- [ ] **Claude**: corrigir o que aparecer no uso real
- [x] **Claude**: painel da empresa (/admin), links em e-mails, planilhas Google e escalas do Connecteam (v0.9.4)
- [ ] **Você**: Google Cloud: ativar a Google Sheets API + escopo de planilhas; todos tocam em Reconectar Google

## Anotado para a próxima versão (juntar e rodar uma vez só)
- Áudio gravado (botão do microfone) também responde em voz alta, com opção de ligar/desligar em Configurações
- Letras maiores como no app do Claude (mensagens 17, entre linhas 26; caixa de texto e cartões maiores); segue o tamanho de letra do
  celular (sem opção própria no app)
- Carteiras nos gastos: cada carteira com nome + moeda (ex. HomB UK £, Pessoal UK £, Pessoal BR R$, Pessoal PT €,
  Business BR R$, Business PT €); filtro por carteira na tela de gastos, totais de cada uma na moeda dela, exportar
  por carteira para o contador; o Fidus escolhe a carteira pelo contexto e pergunta quando houver dúvida
- Menu misturando PT e EN: tradução em blocos menores (blocos grandes falham e ficam sem traduzir) e refazer as que
  faltam
- Voz mais rápida: falar um "deixa eu ver..." enquanto pensa e usar o modelo leve nos pedidos simples

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
- [ ] **Você**: colocar os links das lojas no site (Tweaks) e o domínio no lugar do endereço provisório

## Fase 4 — Crescer
- [ ] iPhone (Apple Developer, US$ 99/ano) e App Store
- [ ] Fidus no computador (Windows e Mac) pelo navegador, instalável como app, mesmo código do celular; liga pelo
      celular com QR code, como o WhatsApp Web (regra: 1 celular + 1 computador por conta)
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
