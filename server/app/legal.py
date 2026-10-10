"""Política de privacidade e termos de uso (inglês e português), servidos em /privacy e /terms.

Rascunho técnico, fiel ao que o código faz hoje. Recomendado: revisão de um advogado antes do lançamento aberto.
Campos que o dono preenche no .env: FIDUS_COMPANY_ADDRESS (registered office) e FIDUS_SUPPORT_EMAIL.
"""
import html

from . import config

COMPANY = "Fidus Labs Limited"
NUMBER = "17510962"
UPDATED = "9 October 2026"


def _vals() -> dict:
    return {"company": COMPANY, "number": NUMBER, "updated": UPDATED,
            "address": html.escape(config.COMPANY_ADDRESS or "[registered office address]"),
            "email": html.escape(config.SUPPORT_EMAIL or config.OWNER_EMAIL or "[support email]")}


PRIVACY = {
    "en": """<h1>Privacy Policy</h1><p class="small">Last updated: {updated}</p>
<p>Fidus is a personal assistant app provided by <b>{company}</b>, a company registered in England and Wales (company no. {number}), registered office {address} (“we”). We are the data controller for the personal data described here. Contact: <a href="mailto:{email}">{email}</a>.</p>
<h2>What we collect</h2>
<ul><li><b>Account:</b> your name, email address, language, country and time zone, your plan and the device you use.</li>
<li><b>What you ask Fidus:</b> your messages, voice requests (transcribed on our server or on your phone; the audio is not kept), photos and PDFs you send (for example receipts), and what Fidus records for you: expenses, wallets, tasks, documents, reminders, meeting notes.</li>
<li><b>Your Google account, only with your permission:</b> Gmail (to read, summarise and prepare replies that you approve), Google Calendar (to read and create events), Google Sheets (only sheets you share with Fidus). You can disconnect at any time in your Google account.</li>
<li><b>Welcome questions:</b> how you work, your priorities and preferences.</li>
<li><b>Usage and quality data:</b> when and which kind of request you made, whether it worked, how long it took, and the 👍/👎 and 0–10 ratings you give. This never includes the content of your messages, emails, diary or spending.</li></ul>
<h2>How we use it</h2>
<ul><li>To provide the service you asked for (contract).</li><li>To keep the service secure, measure quality and fix problems (legitimate interests).</li><li>To send account emails (sign-in codes, subscription notices).</li><li>To send tips and news by email <b>only if you ticked the box</b> (consent). You can stop at any time via the link in every email or in Settings.</li></ul>
<p>We do not sell your data, we do not show ads, and we never use the content of your emails, diary, documents or spending for marketing.</p>
<h2>Google user data</h2>
<p>Fidus's use and transfer of information received from Google APIs to any other app will adhere to the <a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data Policy</a>, including the Limited Use requirements. Google data is used only to provide the features you request in Fidus, is not used for advertising, is not sold, and is not read by people except with your permission, for security reasons, or where the law requires.</p>
<h2>Who processes data for us</h2>
<ul><li>Our server provider (Hetzner, in the European Union), where your data is stored.</li><li>Anthropic (the AI model that understands your requests). Content is processed to answer you and is not used to train models.</li><li>Google (Gemini), for simpler requests, and Google Cloud Text-to-Speech, for the natural voice (only the text of the answer being spoken). Content is not used to train models.</li><li>OpenAI, for the real-time conversation mode (your voice and the conversation, only while that mode is open). Content sent through the API is not used to train models.</li><li>Google Play / Apple App Store and RevenueCat, for subscriptions (we never see your card).</li><li>Resend, to send our emails.</li></ul>
<p>Some of these providers may process data outside the UK/EU; when they do, appropriate safeguards (such as standard contractual clauses) apply.</p>
<h2>How long we keep it</h2>
<p>While your account is active. If you delete your account (Settings › Delete account), your data is permanently destroyed within 30 days; backups roll over within 14 days. Usage and quality data is kept for up to 180 days.</p>
<h2>Your rights</h2>
<p>You can access, export (Settings › Export my data), correct or delete your data, object to or restrict some processing, and withdraw consent. Write to <a href="mailto:{email}">{email}</a>. You can also complain to the UK Information Commissioner's Office (ico.org.uk) or your local data protection authority (for example the ANPD in Brazil or the CNPD in Portugal).</p>
<h2>Children</h2><p>Fidus is for people aged 18 and over.</p>
<h2>Changes</h2><p>If we change this policy in a meaningful way, we will tell you in the app or by email.</p>""",
    "pt": """<h1>Política de Privacidade</h1><p class="small">Última atualização: {updated}</p>
<p>O Fidus é um app de assistente pessoal oferecido pela <b>{company}</b>, empresa registrada na Inglaterra e País de Gales (nº {number}), sede registrada em {address} (“nós”). Somos os responsáveis (controladores) pelos dados pessoais descritos aqui. Contato: <a href="mailto:{email}">{email}</a>.</p>
<h2>O que coletamos</h2>
<ul><li><b>Conta:</b> nome, e-mail, idioma, país e fuso horário, seu plano e o aparelho que você usa.</li>
<li><b>O que você pede ao Fidus:</b> suas mensagens, pedidos por voz (transcritos no nosso servidor ou no seu celular; o áudio não é guardado), fotos e PDFs que você manda (como recibos) e o que o Fidus registra para você: gastos, carteiras, tarefas, documentos, lembretes, atas de reunião.</li>
<li><b>Sua conta Google, só com a sua permissão:</b> Gmail (para ler, resumir e preparar respostas que você aprova), Google Agenda (para ler e criar eventos), Planilhas Google (só as que você compartilha com o Fidus). Você pode desconectar quando quiser na sua conta Google.</li>
<li><b>Perguntas de boas-vindas:</b> como você trabalha, suas prioridades e preferências.</li>
<li><b>Dados de uso e qualidade:</b> quando e que tipo de pedido você fez, se deu certo, quanto demorou e as notas 👍/👎 e de 0 a 10 que você der. Nunca inclui o conteúdo das suas mensagens, e-mails, agenda ou gastos.</li></ul>
<h2>Para que usamos</h2>
<ul><li>Para prestar o serviço que você pediu (contrato).</li><li>Para manter o serviço seguro, medir a qualidade e corrigir problemas (interesse legítimo).</li><li>Para mandar e-mails da conta (códigos de entrada, avisos de assinatura).</li><li>Para mandar dicas e novidades por e-mail <b>só se você marcou a caixa</b> (consentimento). Você pode parar quando quiser pelo link em todo e-mail ou nas Configurações.</li></ul>
<p>Não vendemos seus dados, não mostramos anúncios e nunca usamos o conteúdo dos seus e-mails, agenda, documentos ou gastos para marketing.</p>
<h2>Dados do Google</h2>
<p>O uso e a transferência, pelo Fidus, de informações recebidas das APIs do Google para qualquer outro app seguem a <a href="https://developers.google.com/terms/api-services-user-data-policy">Política de Dados do Usuário dos Serviços de API do Google</a>, incluindo os requisitos de Uso Limitado. Os dados do Google são usados só para as funções que você pede no Fidus, não são usados para publicidade, não são vendidos e não são lidos por pessoas, exceto com a sua permissão, por segurança ou quando a lei exigir.</p>
<h2>Quem processa dados para nós</h2>
<ul><li>Nosso provedor de servidores (Hetzner, na União Europeia), onde seus dados ficam guardados.</li><li>Anthropic (o modelo de IA que entende seus pedidos). O conteúdo é processado para te responder e não é usado para treinar modelos.</li><li>Google (Gemini), para os pedidos mais simples, e Google Cloud Text-to-Speech, para a voz natural (só o texto da resposta que vai ser falada). O conteúdo não é usado para treinar modelos.</li><li>OpenAI, para o modo conversa em tempo real (sua voz e a conversa, só enquanto esse modo está aberto). O conteúdo enviado pela API não é usado para treinar modelos.</li><li>Google Play / Apple App Store e RevenueCat, para as assinaturas (nunca vemos o seu cartão).</li><li>Resend, para enviar nossos e-mails.</li></ul>
<p>Alguns desses fornecedores podem processar dados fora do Reino Unido/UE; nesses casos valem as garantias adequadas (como cláusulas contratuais padrão).</p>
<h2>Por quanto tempo guardamos</h2>
<p>Enquanto sua conta estiver ativa. Se você apagar a conta (Configurações › Apagar conta), seus dados são destruídos de vez em até 30 dias; os backups se renovam em até 14 dias. Dados de uso e qualidade ficam no máximo 180 dias.</p>
<h2>Seus direitos</h2>
<p>Você pode acessar, exportar (Configurações › Exportar meus dados), corrigir ou apagar seus dados, se opor ou limitar alguns usos e retirar o consentimento. Escreva para <a href="mailto:{email}">{email}</a>. Você também pode reclamar à autoridade de proteção de dados: ICO no Reino Unido (ico.org.uk), ANPD no Brasil ou CNPD em Portugal.</p>
<h2>Menores</h2><p>O Fidus é para maiores de 18 anos.</p>
<h2>Mudanças</h2><p>Se mudarmos esta política de forma relevante, avisamos no app ou por e-mail.</p>""",
}

TERMS = {
    "en": """<h1>Terms of Use</h1><p class="small">Last updated: {updated}</p>
<p>These terms are an agreement between you and <b>{company}</b> (England and Wales, company no. {number}, registered office {address}) for the use of the Fidus app and services.</p>
<h2>The service</h2><p>Fidus is an AI personal assistant: it organises your diary, emails, expenses, tasks and documents according to your requests. It uses artificial intelligence and <b>can make mistakes</b>: check important information. Fidus never sends emails, invites or minutes in your name without your approval, and everything it does appears in Activity, where many actions can be undone.</p>
<h2>Your account</h2><p>You must be 18 or over. Each account is personal and works on one phone (and one computer, where available). Keep your devices secure. You are responsible for what you ask Fidus to do and for the content you send.</p>
<h2>Plans and payment</h2><p>Paid plans are monthly or annual subscriptions charged by Google Play or the App Store, which renew automatically until you cancel. You can cancel at any time in the store; the plan stays active until the end of the period already paid. Refunds follow the store's rules and your statutory rights. Prices may change with notice before your next renewal. Promotional codes, partner discounts and referral rewards are not cumulative unless stated.</p>
<h2>Fair use</h2><p>Plans include generous use for one person. To keep the service sustainable, we may limit clearly abusive or automated use, telling you first.</p>
<h2>Acceptable use</h2><p>Do not use Fidus to break the law, send spam, harass others, access accounts that are not yours, or attempt to disrupt or reverse-engineer the service.</p>
<h2>Your content</h2><p>Your content remains yours. You give us permission to process it only to provide the service, as described in the Privacy Policy.</p>
<h2>Liability</h2><p>We provide Fidus with reasonable care and skill. To the extent permitted by law, we are not liable for indirect losses or for decisions you make based on its answers, and our total liability is limited to the amount you paid in the 12 months before the claim. Nothing in these terms limits liability that cannot be limited by law, or your consumer rights.</p>
<h2>Changes and ending</h2><p>We may update these terms and will tell you about important changes. You can delete your account at any time in Settings. We may suspend accounts that seriously breach these terms.</p>
<h2>Law</h2><p>These terms are governed by the laws of England and Wales. If you are a consumer living elsewhere, you keep the protections of your local law and may bring claims in your local courts.</p>
<p>Contact: <a href="mailto:{email}">{email}</a></p>""",
    "pt": """<h1>Termos de Uso</h1><p class="small">Última atualização: {updated}</p>
<p>Estes termos são um acordo entre você e a <b>{company}</b> (Inglaterra e País de Gales, empresa nº {number}, sede registrada em {address}) para o uso do app e dos serviços Fidus.</p>
<h2>O serviço</h2><p>O Fidus é um assistente pessoal com inteligência artificial: organiza agenda, e-mails, gastos, tarefas e documentos conforme os seus pedidos. Ele usa IA e <b>pode errar</b>: confira informações importantes. O Fidus nunca envia e-mails, convites ou atas em seu nome sem a sua aprovação, e tudo que ele faz aparece em Atividade, onde muitas ações podem ser desfeitas.</p>
<h2>Sua conta</h2><p>Você precisa ter 18 anos ou mais. Cada conta é pessoal e funciona em um celular (e um computador, quando disponível). Mantenha seus aparelhos seguros. Você é responsável pelo que pede ao Fidus e pelo conteúdo que envia.</p>
<h2>Planos e pagamento</h2><p>Os planos pagos são assinaturas mensais ou anuais cobradas pela Google Play ou pela App Store, renovadas automaticamente até você cancelar. Você pode cancelar quando quiser na loja; o plano continua até o fim do período já pago. Reembolsos seguem as regras da loja e os seus direitos legais. Os preços podem mudar com aviso antes da próxima renovação. Códigos promocionais, descontos de parceiros e recompensas de indicação não se somam, salvo quando informado.</p>
<h2>Uso justo</h2><p>Os planos incluem uso generoso para uma pessoa. Para manter o serviço sustentável, podemos limitar usos claramente abusivos ou automatizados, avisando antes.</p>
<h2>Uso aceitável</h2><p>Não use o Fidus para violar a lei, mandar spam, assediar pessoas, acessar contas que não são suas ou tentar prejudicar ou copiar o serviço.</p>
<h2>Seu conteúdo</h2><p>Seu conteúdo continua seu. Você nos autoriza a processá-lo só para prestar o serviço, como descrito na Política de Privacidade.</p>
<h2>Responsabilidade</h2><p>Prestamos o Fidus com cuidado e competência razoáveis. Na medida permitida por lei, não respondemos por perdas indiretas nem por decisões que você tomar com base nas respostas, e nossa responsabilidade total fica limitada ao valor que você pagou nos 12 meses anteriores à reclamação. Nada nestes termos limita responsabilidades que a lei não permite limitar, nem seus direitos de consumidor.</p>
<h2>Mudanças e encerramento</h2><p>Podemos atualizar estes termos e avisaremos sobre mudanças importantes. Você pode apagar sua conta quando quiser nas Configurações. Podemos suspender contas que violem gravemente estes termos.</p>
<h2>Lei aplicável</h2><p>Estes termos seguem as leis da Inglaterra e País de Gales. Se você é consumidor e mora em outro país, continua com as proteções da lei local e pode reclamar no tribunal do seu país.</p>
<p>Contato: <a href="mailto:{email}">{email}</a></p>""",
}


def page(kind: str, lang: str) -> str:
    texts = PRIVACY if kind == "privacy" else TERMS
    lang = "pt" if (lang or "").lower().startswith("pt") else "en"
    other = "en" if lang == "pt" else "pt"
    switch = f'<p class="small"><a href="?lang={other}">{"English" if other == "en" else "Português"}</a></p>'
    return switch + texts[lang].format(**_vals())
