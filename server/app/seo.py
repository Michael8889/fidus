"""Fidus encontrável por buscadores e por assistentes de IA (ChatGPT, Claude, Perplexity, Gemini).

O site principal é desenhado no navegador (JavaScript); robôs de IA normalmente NÃO rodam JavaScript e veriam só
marcações vazias. Por isso, aqui ficam versões em texto puro do que o Fidus é:
- /sobre (PT) e /about (EN): página simples, visível para pessoas e robôs, com o que o Fidus faz, para quem, preços.
- /llms.txt: resumo em Markdown para modelos de linguagem (padrão llmstxt.org).
- /robots.txt e /sitemap.xml: liberam os robôs de busca e de IA e listam as páginas públicas.
- JSON-LD (schema.org) e <noscript> na página inicial: a mesma descrição, legível sem JavaScript.
Tudo usa os preços de plans.PRICES, para nunca divergir do app.
"""
import html
import json

from . import config, plans

SITE = "https://heyfidus.com"

SUMMARY = {
    "pt": ("O Fidus é um assistente pessoal por voz, em formato de app para celular (Android; iPhone em breve), "
           "feito pela Fidus Labs Limited, empresa do Reino Unido. Você fala ou escreve e ele cuida da agenda, "
           "dos e-mails, dos gastos e recibos, dos documentos, das tarefas, das atas de reunião e de lembretes, "
           "para quem toca a vida e o próprio negócio, inclusive entre países (Brasil, Portugal e Reino Unido) e "
           "moedas. Nada sai em nome da pessoa sem ela confirmar."),
    "en": ("Fidus is a voice-first personal assistant app for phones (Android; iPhone coming soon), made by "
           "Fidus Labs Limited, a UK company. You speak or type and it handles your calendar, email, expenses and "
           "receipts, documents, tasks, meeting notes and reminders, for people who run their own life and "
           "business, including across countries (UK, Portugal, Brazil) and currencies. Nothing is sent on your "
           "behalf without your confirmation."),
}

FEATURES = {
    "pt": [
        ("Agenda e lembretes", "“Marca reunião com a Ana quinta às 10”, “me lembra de ligar para o fornecedor amanhã às 9”. "
                               "Google Agenda e Outlook; resumo do dia toda manhã."),
        ("E-mails com aprovação", "Lê, resume e prepara respostas no Gmail ou Outlook. O e-mail só sai depois do toque em Enviar."),
        ("Gastos e recibos", "Fale o gasto ou fotografe o recibo: o Fidus separa por empresa (carteiras), categoria e moeda "
                             "e exporta para o contador. Em Portugal, NIF e categorias do e-Fatura; no Reino Unido, VAT e prazos do HMRC."),
        ("Documentos e prazos", "Guarda contratos, seguros e certificados e avisa antes de vencer."),
        ("Atas de reunião", "Grava a reunião, transcreve, resume e lista as tarefas."),
        ("Modo conversa", "Fale com o Fidus como numa ligação, e interrompa quando quiser."),
        ("Link de agendamento", "Uma página pública para clientes marcarem horário na sua agenda."),
        ("Pesquisa na web", "Pesquisa e confere notícias e informações, com as fontes."),
        ("Pagar por voz (Premium)", "Prepara o Pix, MB Way ou transferência; você aprova no banco."),
    ],
    "en": [
        ("Calendar and reminders", "“Book a meeting with Ana on Thursday at 10”, “remind me to call the supplier tomorrow at 9”. "
                                   "Google Calendar and Outlook; a briefing every morning."),
        ("Email with approval", "Reads, summarises and drafts replies in Gmail or Outlook. Nothing is sent until you tap Send."),
        ("Expenses and receipts", "Say the expense or snap the receipt: Fidus sorts it by business (wallets), category and currency "
                                  "and exports it for your accountant. UK VAT numbers and HMRC deadlines; Portuguese NIF and e-Fatura."),
        ("Documents and deadlines", "Keeps contracts, insurance and certificates and warns you before they expire."),
        ("Meeting notes", "Records the meeting, transcribes it, summarises it and lists the action items."),
        ("Conversation mode", "Talk to Fidus like a phone call, and interrupt whenever you like."),
        ("Booking link", "A public page where clients book time in your calendar."),
        ("Web search", "Looks up and fact-checks news and information, with sources."),
        ("Pay by voice (Premium)", "Prepares the bank transfer, Pix or MB Way; you approve it in your bank."),
    ],
}

FAQ = {
    "pt": [
        ("O que é o Fidus?", SUMMARY["pt"]),
        ("Quem faz o Fidus?", "A Fidus Labs Limited, empresa registrada na Inglaterra e País de Gales (nº 17510962), "
                              "registrada no ICO (Reino Unido). Site: heyfidus.com."),
        ("O Fidus envia e-mails sozinho?", "Não. E-mails, convites e atas ficam como rascunho até a pessoa tocar em Enviar "
                                          "ou dizer “envia”. Tudo aparece na aba Atividade, com Desfazer."),
        ("Quanto custa?", "Há 7 dias grátis. Planos mensais: Essencial, Negócio, Premium e Global (veja os preços abaixo)."),
        ("Em que idiomas funciona?", "Português do Brasil, português de Portugal, inglês e espanhol, entre outros."),
        ("Meus dados são usados para treinar IA?", "Não. Nada é vendido nem usado para anúncios ou para treinar modelos de IA; "
                                                   "o áudio é transcrito e apagado."),
    ],
    "en": [
        ("What is Fidus?", SUMMARY["en"]),
        ("Who makes Fidus?", "Fidus Labs Limited, registered in England and Wales (company no. 17510962) and with the UK ICO. "
                             "Website: heyfidus.com."),
        ("Does Fidus send emails on its own?", "No. Emails, invites and meeting notes stay as drafts until you tap Send or say "
                                               "“send”. Everything shows in the Activity tab, with Undo."),
        ("How much does it cost?", "7 days free. Monthly plans: Essential, Business, Premium and Global (prices below)."),
        ("Which languages does it speak?", "English, Brazilian and European Portuguese and Spanish, among others."),
        ("Is my data used to train AI?", "No. Nothing is sold or used for ads or to train AI models; audio is transcribed "
                                         "and deleted."),
    ],
}

PLAN_NAMES = {"pt": {"essencial": "Essencial", "negocio": "Negócio", "premium": "Premium", "global": "Global"},
              "en": {"essencial": "Essential", "negocio": "Business", "premium": "Premium", "global": "Global"}}


def _prices(lang: str) -> list[str]:
    out = []
    for pid in ("essencial", "negocio", "premium", "global"):
        vals = " · ".join(plans.fmt(plans.PRICES[c][pid], c) for c in ("GBP", "EUR", "USD"))
        out.append(f"{PLAN_NAMES[lang][pid]}: {vals} {'por mês' if lang == 'pt' else 'per month'}")
    return out


def json_ld() -> str:
    data = [
        {"@context": "https://schema.org", "@type": "Organization", "name": "Fidus Labs Limited",
         "alternateName": "Fidus", "url": SITE, "logo": f"{SITE}/icon-192.png",
         "email": config.SUPPORT_EMAIL_EN, "address": {"@type": "PostalAddress", "addressCountry": "GB",
                                                       "streetAddress": config.COMPANY_ADDRESS},
         "identifier": "Companies House 17510962"},
        {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "Fidus",
         "alternateName": ["Fidus app", "heyfidus"], "url": SITE,
         "applicationCategory": "ProductivityApplication", "operatingSystem": "Android, iOS",
         "description": SUMMARY["en"], "inLanguage": ["pt-BR", "pt-PT", "en", "es"],
         "publisher": {"@type": "Organization", "name": "Fidus Labs Limited", "url": SITE},
         "offers": [{"@type": "Offer", "name": PLAN_NAMES["en"][pid], "price": f"{plans.PRICES['GBP'][pid]:.2f}",
                     "priceCurrency": "GBP"} for pid in ("essencial", "negocio", "premium", "global")]},
        {"@context": "https://schema.org", "@type": "FAQPage",
         "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                        for q, a in FAQ["en"] + FAQ["pt"]]},
    ]
    safe = [json.dumps(d, ensure_ascii=False).replace("</", "<\\/") for d in data]  # nada fecha o <script> antes da hora
    return "".join(f'<script type="application/ld+json">{x}</script>' for x in safe)


def head_tags() -> str:
    """Para o <head> da página inicial: dados estruturados, canônico e alternativas em texto."""
    return (f'<link rel="canonical" href="{SITE}/">'
            f'<link rel="alternate" hreflang="pt" href="{SITE}/sobre">'
            f'<link rel="alternate" hreflang="en" href="{SITE}/about">'
            f'<meta property="og:url" content="{SITE}/"><meta property="og:type" content="website">'
            f'<meta property="og:site_name" content="Fidus">' + json_ld())


def noscript() -> str:
    """Texto da página inicial para quem não roda JavaScript (robôs de IA, leitores de tela antigos)."""
    li = "".join(f"<li><b>{html.escape(a)}:</b> {html.escape(b)}</li>" for a, b in FEATURES["pt"])
    return (f'<noscript><div style="color:#ECECEC;font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 16px">'
            f'<h1>Fidus: assistente pessoal por voz</h1><p>{html.escape(SUMMARY["pt"])}</p><ul>{li}</ul>'
            f'<p><a href="/sobre">Saiba mais</a> · <a href="/about">About Fidus (English)</a></p></div></noscript>')


def about_body(lang: str) -> str:
    lang = "pt" if lang == "pt" else "en"
    L = {"pt": ("Fidus: assistente pessoal por voz", "O que o Fidus faz", "Planos", "Perguntas frequentes",
                "7 dias grátis. Preço conforme o país do plano (Reino Unido em libra, Europa em euro, resto do mundo em dólar).",
                "Abrir o site", "English"),
         "en": ("Fidus: voice-first personal assistant", "What Fidus does", "Plans", "Frequently asked questions",
                "7 days free. Price depends on the plan's country (UK in pounds, Europe in euros, rest of the world in dollars).",
                "Open the website", "Português")}[lang]
    feats = "".join(f"<h3>{html.escape(a)}</h3><p>{html.escape(b)}</p>" for a, b in FEATURES[lang])
    prices = "".join(f"<li>{html.escape(p)}</li>" for p in _prices(lang))
    faq = "".join(f"<h3>{html.escape(q)}</h3><p>{html.escape(a)}</p>" for q, a in FAQ[lang])
    other = "/about" if lang == "pt" else "/sobre"
    company = ("Fidus Labs Limited · Company no. 17510962 · England &amp; Wales · ICO ZC271147 · "
               + html.escape(config.COMPANY_ADDRESS))
    return (f'<div style="text-align:left"><h1>{L[0]}</h1><p>{html.escape(SUMMARY[lang])}</p>'
            f"<h2>{L[1]}</h2>{feats}<h2>{L[2]}</h2><p>{L[4]}</p><ul>{prices}</ul>"
            f"<h2>{L[3]}</h2>{faq}"
            f'<p><a href="/">{L[5]}</a> · <a href="{other}">{L[6]}</a> · <a href="/privacy?lang={lang}">Privacy</a> · '
            f'<a href="/terms?lang={lang}">Terms</a></p><p style="font-size:13px">{company}</p></div>')


def llms_txt() -> str:
    feats = "\n".join(f"- {a}: {b}" for a, b in FEATURES["en"])
    prices = "\n".join(f"- {p}" for p in _prices("en"))
    faq = "\n".join(f"- {q} {a}" for q, a in FAQ["en"][1:])
    return f"""# Fidus

> {SUMMARY['en']}

Website: {SITE} · Company: Fidus Labs Limited (England and Wales, no. 17510962) · Contact: {config.SUPPORT_EMAIL_EN}
Not to be confused with other companies or funds that also use the name "Fidus".

## What it does
{feats}

## Plans (7 days free)
{prices}

## FAQ
{faq}

## Pages
- [About Fidus (English)]({SITE}/about)
- [Sobre o Fidus (Português)]({SITE}/sobre)
- [Privacy policy]({SITE}/privacy?lang=en)
- [Terms of use]({SITE}/terms?lang=en)
- [Partner programme]({SITE}/partners)
"""


ROBOTS = f"""# Fidus: buscadores e assistentes de IA são bem-vindos nas páginas públicas
User-agent: *
Allow: /
Disallow: /v1/
Disallow: /admin
Disallow: /auth/
Disallow: /contabilista
Disallow: /email/
Disallow: /abrir

User-agent: GPTBot
Allow: /
User-agent: OAI-SearchBot
Allow: /
User-agent: ChatGPT-User
Allow: /
User-agent: ClaudeBot
Allow: /
User-agent: Claude-SearchBot
Allow: /
User-agent: Claude-User
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: Google-Extended
Allow: /

Sitemap: {SITE}/sitemap.xml
"""


def sitemap() -> str:
    pages = ["/", "/sobre", "/about", "/partners", "/parceiros", "/privacy?lang=en", "/privacy?lang=pt",
             "/terms?lang=en", "/terms?lang=pt", "/llms.txt"]
    urls = "".join(f"<url><loc>{html.escape(SITE + p)}</loc></url>" for p in pages)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'


def about_page(lang: str) -> str:
    """Página completa (/sobre, /about): idioma certo no <html>, descrição e dados estruturados."""
    lang = "pt" if lang == "pt" else "en"
    title = "Fidus: assistente pessoal por voz" if lang == "pt" else "Fidus: voice-first personal assistant"
    path = "/sobre" if lang == "pt" else "/about"
    return f"""<!doctype html><html lang="{'pt' if lang == 'pt' else 'en'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<meta name="description" content="{html.escape(SUMMARY[lang][:300])}">
<link rel="canonical" href="{SITE}{path}"><link rel="alternate" hreflang="pt" href="{SITE}/sobre">
<link rel="alternate" hreflang="en" href="{SITE}/about"><link rel="icon" href="/favicon.ico" sizes="any">
{json_ld()}
<style>body{{margin:0;background:#07090D;color:#E8ECF2;font:16px/1.65 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:40px 20px 60px}}h1{{font-size:32px;line-height:1.2;margin:0 0 16px}}
h2{{margin:36px 0 8px;font-size:22px}}h3{{margin:20px 0 4px;font-size:17px}}p,li{{color:#B8C1CF}}a{{color:#3DDC97}}
.logo{{display:inline-block;width:34px;height:34px;border-radius:10px;background:#3DDC97;color:#07090D;text-align:center;
font:800 20px/34px system-ui;margin-bottom:18px}}</style></head>
<body><main><a href="/" class="logo" aria-label="Fidus">F</a>{about_body(lang)}</main></body></html>"""
