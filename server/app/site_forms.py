"""Formulários do site (heyfidus.com): lista de espera e pedido de parceria.

- Lista de espera: grava no accounts.db, manda UM e-mail de confirmação (com link para sair da lista) e, quando o app
  chega na loja, o painel avisa todo mundo de uma vez (só o celular de cada um: Android → Google Play, iPhone → App Store).
- Parceria: página /parceiros (/partners em inglês) com formulário; o pedido vai para o painel e para o e-mail de suporte.
Nada aqui fala em nome de um cliente: são e-mails da própria empresa para quem pediu.
"""
import html
import logging
import re
import time

from . import accounts, config, mailer, partners

log = logging.getLogger("fidus.site")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PLANS = {"essencial": "Essencial", "negocio": "Negócio", "premium": "Premium"}
_HITS: dict[str, list[float]] = {}


def limited(bucket: str, ip: str, n: int, window: float = 3600) -> bool:
    """True se este IP já passou do limite (proteção contra robô enchendo a lista)."""
    key, now = f"{bucket}:{ip}", time.time()
    hits = [t for t in _HITS.get(key, []) if now - t < window]
    if len(hits) >= n:
        _HITS[key] = hits
        return True
    _HITS[key] = hits + [now]
    return False


def _lang(lang: str | None) -> str:
    raw = (lang or "").lower().replace("_", "-")
    if raw.startswith("pt-pt"):
        return "pt-pt"
    lang = raw.split("-")[0]
    return lang if lang in ("pt", "en", "es") else "en"


def _base() -> str:
    return (config.PUBLIC_BASE_URL or "https://heyfidus.com").rstrip("/")


def _footer(leave_link: str, lang: str) -> str:
    leave = {"pt": "Não quer mais receber? <a href='{u}'>Sair da lista</a>.",
             "pt-pt": "Não quer receber mais? <a href='{u}'>Sair da lista</a>.",
             "en": "Don't want these emails? <a href='{u}'>Leave the list</a>.",
             "es": "¿No quieres recibir más? <a href='{u}'>Salir de la lista</a>."}[lang].format(u=html.escape(leave_link))
    return (f"<p style='margin-top:24px;color:#8A8F98;font-size:12px'>{leave}<br>"
            f"Fidus Labs Limited · {html.escape(config.COMPANY_ADDRESS)}</p>")


# ---------------- lista de espera ----------------
WAIT_MAIL = {
    "pt": ("Você está na lista do Fidus",
           "<p>Oi! Obrigado pelo interesse no Fidus.</p>"
           "<p>Você entrou na próxima turma de testes. Assim que o app estiver disponível para o seu celular, "
           "avisamos por este e-mail com o link direto da loja.</p>{plan}"
           "<p>Enquanto isso: imagine falar <i>“marca o contador sexta às 10 e me lembra uma hora antes”</i> "
           "e pronto. É isso que o Fidus faz.</p><p>Alguma dúvida? É só responder este e-mail.</p>",
           "<p>Plano que chamou sua atenção: <b>{p}</b>.</p>"),
    "pt-pt": ("Está na lista do Fidus",
              "<p>Olá! Obrigado pelo interesse no Fidus.</p>"
              "<p>Entrou na próxima turma de testes. Assim que a app estiver disponível para o seu telemóvel, "
              "avisamos por este e-mail com o link direto da loja.</p>{plan}"
              "<p>Entretanto, imagine dizer <i>“marca o contabilista sexta às 10 e lembra-me uma hora antes”</i> "
              "e está feito. É isso que o Fidus faz.</p><p>Alguma dúvida? Basta responder a este e-mail.</p>",
              "<p>Plano que lhe chamou a atenção: <b>{p}</b>.</p>"),
    "en": ("You're on the Fidus list",
           "<p>Hi! Thanks for your interest in Fidus.</p>"
           "<p>You're in the next test group. As soon as the app is available for your phone, we'll email you "
           "the direct store link.</p>{plan}"
           "<p>Meanwhile, picture saying <i>“book the accountant Friday at 10 and remind me an hour before”</i> "
           "and it's done. That's Fidus.</p><p>Any questions? Just reply to this email.</p>",
           "<p>The plan you picked: <b>{p}</b>.</p>"),
    "es": ("Estás en la lista de Fidus",
           "<p>¡Hola! Gracias por tu interés en Fidus.</p>"
           "<p>Entraste en el próximo grupo de pruebas. En cuanto la app esté disponible para tu móvil, te "
           "avisamos por este correo con el enlace directo de la tienda.</p>{plan}"
           "<p>Mientras tanto, imagina decir <i>“agenda al contador el viernes a las 10 y recuérdamelo una hora antes”</i> "
           "y listo. Eso es Fidus.</p><p>¿Dudas? Solo responde a este correo.</p>",
           "<p>El plan que elegiste: <b>{p}</b>.</p>"),
}


def join(email: str, lang: str = "", platform: str = "", plan: str = "", ref: str = "") -> dict:
    email = (email or "").strip().lower()[:200]
    if not EMAIL_RE.fullmatch(email):
        return {"error": "invalid_email"}
    plan = plan if plan in PLANS else ""
    platform = platform if platform in ("android", "ios", "desktop") else ""
    ref = partners.norm(ref)[:24] if ref else ""
    r = accounts.add_waitlist(email, (lang or "")[:8], platform, plan, ref)
    if r["new"]:
        lg = _lang(lang)
        subject, body, plan_line = WAIT_MAIL[lg]
        body = body.format(plan=plan_line.format(p=PLANS[plan]) if plan else "")
        leave = f"{_base()}/lista/sair?t={r['token']}&lang={lg}"
        mailer.send_raw(email, subject, body, wait=False, footer=_footer(leave, lg),
                        headers={"List-Unsubscribe": f"<{leave}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
    return {"ok": True, "new": r["new"]}


STORE_MAIL = {
    "pt": ("O Fidus chegou no seu celular", "<p>Chegou! O Fidus já está na loja do seu celular.</p>"
           "<p><a href='{u}' style='display:inline-block;background:#07090D;color:#fff;padding:12px 20px;border-radius:12px;"
           "text-decoration:none;font-weight:700'>Baixar o Fidus</a></p><p>Abra, entre com o Google e diga o que precisa.</p>"),
    "pt-pt": ("O Fidus chegou ao seu telemóvel", "<p>Chegou! O Fidus já está na loja do seu telemóvel.</p>"
              "<p><a href='{u}' style='display:inline-block;background:#07090D;color:#fff;padding:12px 20px;border-radius:12px;"
              "text-decoration:none;font-weight:700'>Descarregar o Fidus</a></p><p>Abra, entre com o Google e diga do que precisa.</p>"),
    "en": ("Fidus is ready for your phone", "<p>It's here! Fidus is now in your phone's store.</p>"
           "<p><a href='{u}' style='display:inline-block;background:#07090D;color:#fff;padding:12px 20px;border-radius:12px;"
           "text-decoration:none;font-weight:700'>Get Fidus</a></p><p>Open it, sign in with Google and just say what you need.</p>"),
    "es": ("Fidus ya está en tu móvil", "<p>¡Ya llegó! Fidus está en la tienda de tu móvil.</p>"
           "<p><a href='{u}' style='display:inline-block;background:#07090D;color:#fff;padding:12px 20px;border-radius:12px;"
           "text-decoration:none;font-weight:700'>Descargar Fidus</a></p><p>Ábrela, entra con Google y di lo que necesitas.</p>"),
}


def notify_store_ready() -> dict:
    """Avisa (uma vez) quem está na lista e cuja loja já tem o link. Chamado pelo painel, com confirmação."""
    play, apple = config.PLAY_STORE_URL, config.APP_STORE_URL
    sent = skipped = 0
    for w in accounts.waitlist():
        if w.get("notified_at"):
            continue
        plat = w.get("platform") or ""
        url = apple if plat == "ios" else play if plat == "android" else (play or apple)
        if not url:
            skipped += 1
            continue
        lg = _lang(w.get("lang"))
        subject, body = STORE_MAIL[lg]
        leave = f"{_base()}/lista/sair?t={w.get('token') or ''}&lang={lg}"
        try:
            mailer.send_raw(w["email"], subject, body.format(u=html.escape(url)), wait=True, footer=_footer(leave, lg))
        except Exception as e:  # noqa: BLE001
            log.warning("aviso da loja para %s falhou: %s", w["email"], e)
            continue
        accounts.mark_waitlist_notified(w["email"])
        sent += 1
    return {"ok": True, "sent": sent, "waiting_store": skipped}


LEAVE_TEXT = {"pt": ("Pronto, você saiu da lista.", "Não vamos mais mandar e-mails sobre o lançamento.",
                     "Sair da lista do Fidus?", "Você não vai receber o aviso de quando o app chegar na loja.", "Sair da lista"),
              "pt-pt": ("Pronto, saiu da lista.", "Não lhe enviaremos mais e-mails sobre o lançamento.",
                        "Sair da lista do Fidus?", "Não vai receber o aviso de quando a app chegar à loja.", "Sair da lista"),
              "en": ("Done, you've left the list.", "We won't email you about the launch again.",
                     "Leave the Fidus list?", "You won't get the email when the app reaches the store.", "Leave the list"),
              "es": ("Listo, saliste de la lista.", "No te enviaremos más correos sobre el lanzamiento.",
                     "¿Salir de la lista de Fidus?", "No recibirás el aviso cuando la app llegue a la tienda.", "Salir de la lista")}


# ---------------- parceria ----------------
PARTNER = {
    "pt": {
        "title": "Seja parceiro do Fidus",
        "lead": "Indique o Fidus para quem vive entre empresas, países e moedas, e ganhe com cada cliente que ficar.",
        "points": ["Seu código próprio: quem entra com ele ganha {d}% de desconto no primeiro mês.",
                   "Você recebe {p}% de cada mensalidade paga por esse cliente, durante {m} meses.",
                   "Tudo registrado: cadastros e pagamentos acompanhados, acerto todo mês.",
                   "Para criadores de conteúdo, contadores, consultores e comunidades de empreendedores."],
        "form": "Conte um pouco sobre você", "name": "Nome", "email": "E-mail", "kind": "Você é",
        "kinds": [("criador", "Criador de conteúdo"), ("contador", "Contador ou consultor"),
                  ("comunidade", "Comunidade ou empresa"), ("outro", "Outro")],
        "link": "Onde você publica (Instagram, YouTube, site)", "audience": "Tamanho do público",
        "auds": ["até 5 mil", "5 a 50 mil", "50 a 500 mil", "mais de 500 mil", "não se aplica"],
        "country": "País", "message": "Como você pensa divulgar o Fidus? (opcional)",
        "consent": "Concordo que o Fidus guarde estes dados para responder ao meu pedido.",
        "send": "Quero ser parceiro", "sending": "Enviando…",
        "ok": "Recebemos seu pedido! Respondemos por e-mail em até 3 dias úteis.",
        "err": "Não deu para enviar. Confira os campos e tente de novo.", "back": "← Voltar ao site",
        "priv": "Privacidade", "subject": "Recebemos seu pedido de parceria",
        "mail": "<p>Oi, {n}! Recebemos seu pedido para ser parceiro do Fidus.</p><p>Nossa equipe responde em até 3 dias "
                "úteis com seu código e os próximos passos. Se quiser acrescentar algo, é só responder este e-mail.</p>",
    },
    "en": {
        "title": "Become a Fidus partner",
        "lead": "Recommend Fidus to people who run more than one business, country or currency, and earn from every customer who stays.",
        "points": ["Your own code: people who join with it get {d}% off their first month.",
                   "You earn {p}% of every monthly payment from that customer for {m} months.",
                   "Everything tracked: sign-ups and payments recorded, settled monthly.",
                   "For content creators, accountants, consultants and founder communities."],
        "form": "Tell us about you", "name": "Name", "email": "Email", "kind": "You are",
        "kinds": [("criador", "Content creator"), ("contador", "Accountant or consultant"),
                  ("comunidade", "Community or company"), ("outro", "Other")],
        "link": "Where you publish (Instagram, YouTube, website)", "audience": "Audience size",
        "auds": ["up to 5k", "5k to 50k", "50k to 500k", "over 500k", "not applicable"],
        "country": "Country", "message": "How would you promote Fidus? (optional)",
        "consent": "I agree that Fidus keeps this data to reply to my request.",
        "send": "Apply to partner", "sending": "Sending…",
        "ok": "Got it! We'll reply by email within 3 business days.",
        "err": "Couldn't send. Check the fields and try again.", "back": "← Back to the site",
        "priv": "Privacy", "subject": "We received your partner application",
        "mail": "<p>Hi {n}! We received your application to become a Fidus partner.</p><p>Our team will reply within 3 "
                "business days with your code and next steps. To add anything, just reply to this email.</p>",
    },
    "es": {
        "title": "Hazte socio de Fidus",
        "lead": "Recomienda Fidus a quien vive entre empresas, países y monedas, y gana con cada cliente que se quede.",
        "points": ["Tu propio código: quien entra con él tiene {d}% de descuento el primer mes.",
                   "Recibes el {p}% de cada mensualidad pagada por ese cliente durante {m} meses.",
                   "Todo registrado: altas y pagos controlados, liquidación mensual.",
                   "Para creadores de contenido, contadores, consultores y comunidades de emprendedores."],
        "form": "Cuéntanos sobre ti", "name": "Nombre", "email": "Correo", "kind": "Eres",
        "kinds": [("criador", "Creador de contenido"), ("contador", "Contador o consultor"),
                  ("comunidade", "Comunidad o empresa"), ("outro", "Otro")],
        "link": "Dónde publicas (Instagram, YouTube, web)", "audience": "Tamaño de la audiencia",
        "auds": ["hasta 5 mil", "5 a 50 mil", "50 a 500 mil", "más de 500 mil", "no aplica"],
        "country": "País", "message": "¿Cómo darías a conocer Fidus? (opcional)",
        "consent": "Acepto que Fidus guarde estos datos para responder a mi solicitud.",
        "send": "Quiero ser socio", "sending": "Enviando…",
        "ok": "¡Recibido! Respondemos por correo en un máximo de 3 días hábiles.",
        "err": "No se pudo enviar. Revisa los campos e inténtalo de nuevo.", "back": "← Volver al sitio",
        "priv": "Privacidad", "subject": "Recibimos tu solicitud de socio",
        "mail": "<p>¡Hola, {n}! Recibimos tu solicitud para ser socio de Fidus.</p><p>Nuestro equipo responde en un máximo "
                "de 3 días hábiles con tu código y los próximos pasos. Si quieres añadir algo, responde a este correo.</p>",
    },
}

PARTNER["pt-pt"] = {**PARTNER["pt"],
    "lead": "Recomende o Fidus a quem vive entre empresas, países e moedas, e ganhe com cada cliente que ficar.",
    "points": ["O seu código próprio: quem entra com ele ganha {d}% de desconto no primeiro mês.",
               "Recebe {p}% de cada mensalidade paga por esse cliente, durante {m} meses.",
               "Tudo registado: registos e pagamentos acompanhados, acerto todos os meses.",
               "Para criadores de conteúdo, contabilistas, consultores e comunidades de empreendedores."],
    "form": "Fale-nos um pouco de si", "kind": "É", "kinds": [("criador", "Criador de conteúdo"),
        ("contador", "Contabilista ou consultor"), ("comunidade", "Comunidade ou empresa"), ("outro", "Outro")],
    "link": "Onde publica (Instagram, YouTube, site)", "message": "Como pensa divulgar o Fidus? (opcional)",
    "consent": "Concordo que o Fidus guarde estes dados para responder ao meu pedido.",
    "ok": "Recebemos o seu pedido! Respondemos por e-mail em até 3 dias úteis.",
    "err": "Não foi possível enviar. Confirme os campos e tente de novo.",
    "subject": "Recebemos o seu pedido de parceria",
    "mail": "<p>Olá, {n}! Recebemos o seu pedido para ser parceiro do Fidus.</p><p>A nossa equipa responde em até 3 dias "
            "úteis com o seu código e os próximos passos. Se quiser acrescentar algo, basta responder a este e-mail.</p>",
}

_CSS = """*{box-sizing:border-box}body{margin:0;background:#07090D;color:#F2F5F7;font-family:Figtree,system-ui,sans-serif;line-height:1.55}
main{max-width:1080px;margin:0 auto;padding:28px 20px 72px}a{color:#3DDC97}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:40px}
.logo{display:flex;align-items:center;gap:10px;font-weight:800;font-size:20px;color:#F2F5F7;text-decoration:none}
.logo span{width:32px;height:32px;border-radius:10px;background:#3DDC97;color:#07090D;display:flex;align-items:center;justify-content:center}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:40px;align-items:start}
h1{font-family:'Bricolage Grotesque',Figtree,sans-serif;font-weight:800;font-size:clamp(34px,5vw,56px);line-height:1.03;letter-spacing:-.03em;margin:0 0 16px}
.lead{color:#B7C0CC;font-size:19px;margin:0 0 26px}ul{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:14px}
li{display:flex;gap:12px;font-size:16px;color:#E2E7ED}li b{color:#3DDC97}
form{background:#0E1218;border:1px solid #1E2530;border-radius:22px;padding:24px;display:flex;flex-direction:column;gap:14px}
form h2{margin:0 0 4px;font-size:20px}label{font-size:14px;color:#B7C0CC;display:flex;flex-direction:column;gap:6px}
input,select,textarea{font:inherit;font-size:16px;color:#F2F5F7;background:#07090D;border:1px solid #2A3341;border-radius:12px;padding:13px 14px;width:100%}
textarea{min-height:90px;resize:vertical}.check{flex-direction:row;align-items:flex-start;gap:10px}.check input{width:auto;margin-top:4px}
button{font:inherit;font-weight:800;font-size:16px;border:0;border-radius:14px;padding:16px;background:#3DDC97;color:#07090D;cursor:pointer}
button[disabled]{opacity:.6;cursor:default}.msg{margin:0;font-weight:600}.ok{color:#3DDC97}.err{color:#FF8A8A}
.hp{position:absolute;left:-9999px}footer{margin-top:56px;color:#8D98A8;font-size:14px}"""


def partner_page(lang: str) -> str:
    lg = _lang(lang)
    T = PARTNER[lg]
    e = html.escape
    pts = "".join(f"<li><b>✓</b><span>{e(p.format(d=partners.DEFAULT_DISCOUNT, p=partners.DEFAULT_PERCENT, m=partners.DEFAULT_MONTHS))}</span></li>"
                  for p in T["points"])
    kinds = "".join(f'<option value="{k}">{e(v)}</option>' for k, v in T["kinds"])
    auds = "".join(f'<option>{e(a)}</option>' for a in T["auds"])
    js_t = {"sending": T["sending"], "send": T["send"], "ok": T["ok"], "err": T["err"]}
    import json
    return f"""<!doctype html><html lang="{'pt-PT' if lg == 'pt-pt' else lg}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(T['title'])} · Fidus</title>
<meta name="description" content="{e(T['lead'])}"><meta name="theme-color" content="#07090D">
<link rel="icon" href="/favicon.ico" sizes="any"><link rel="icon" type="image/png" href="/favicon-32.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,800&family=Figtree:wght@400;600;800&display=swap" rel="stylesheet">
<style>{_CSS}</style></head><body><main>
<div class="top"><a class="logo" href="/"><span>F</span>Fidus</a><a href="/">{e(T['back'])}</a></div>
<div class="grid"><div><h1>{e(T['title'])}</h1><p class="lead">{e(T['lead'])}</p><ul>{pts}</ul></div>
<form id="pf" novalidate><h2>{e(T['form'])}</h2>
<label>{e(T['name'])}<input name="name" required maxlength="120" autocomplete="name"></label>
<label>{e(T['email'])}<input name="email" type="email" required maxlength="200" autocomplete="email"></label>
<label>{e(T['kind'])}<select name="kind">{kinds}</select></label>
<label>{e(T['link'])}<input name="link" maxlength="300" placeholder="https://"></label>
<label>{e(T['audience'])}<select name="audience">{auds}</select></label>
<label>{e(T['country'])}<input name="country" maxlength="60" autocomplete="country-name"></label>
<label>{e(T['message'])}<textarea name="message" maxlength="2000"></textarea></label>
<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
<label class="check"><input type="checkbox" name="consent" required><span>{e(T['consent'])} <a href="/privacy?lang={lg}">{e(T['priv'])}</a></span></label>
<button type="submit">{e(T['send'])}</button><p class="msg" id="pm" role="status" aria-live="polite"></p></form></div>
<footer>Fidus Labs Limited · {e(config.COMPANY_ADDRESS)} · <a href="mailto:{e(config.SUPPORT_EMAIL)}">{e(config.SUPPORT_EMAIL)}</a></footer>
</main><script>
var T={json.dumps(js_t, ensure_ascii=False)};
document.getElementById("pf").addEventListener("submit",function(ev){{
  ev.preventDefault();var f=ev.target,b=f.querySelector("button"),m=document.getElementById("pm");
  if(!f.checkValidity()){{m.className="msg err";m.textContent=T.err;f.reportValidity&&f.reportValidity();return;}}
  var d={{lang:"{lg}"}};["name","email","kind","link","audience","country","message","website"].forEach(function(k){{d[k]=f.elements[k].value;}});
  b.disabled=true;b.textContent=T.sending;m.textContent="";
  fetch("/v1/site/partner",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(d)}})
   .then(function(r){{if(!r.ok)throw 0;m.className="msg ok";m.textContent=T.ok;f.reset();b.textContent=T.send;}})
   .catch(function(){{m.className="msg err";m.textContent=T.err;b.disabled=false;b.textContent=T.send;}});
}});
</script></body></html>"""


def apply(d: dict) -> dict:
    if (d.get("website") or "").strip():  # campo escondido: só robô preenche
        return {"ok": True}
    name = (d.get("name") or "").strip()[:120]
    email = (d.get("email") or "").strip().lower()[:200]
    if not name or not EMAIL_RE.fullmatch(email):
        return {"error": "invalid"}
    lg = _lang(d.get("lang"))
    rec = {"name": name, "email": email, "lang": lg,
           "kind": (d.get("kind") or "")[:20], "link": (d.get("link") or "").strip()[:300],
           "audience": (d.get("audience") or "")[:40], "country": (d.get("country") or "").strip()[:60],
           "message": (d.get("message") or "").strip()[:2000]}
    app_id = accounts.add_partner_application(rec)
    T = PARTNER[lg]
    e = html.escape
    mailer.send_raw(email, T["subject"], T["mail"].format(n=e(name.split()[0])), wait=False)
    rows = "".join(f"<p><b>{k}</b>: {e(str(v) or '—')}</p>" for k, v in rec.items())
    mailer.send_raw(config.SUPPORT_EMAIL, f"Novo pedido de parceria #{app_id}: {name}",
                    rows + "<p>Veja no painel: /admin › Site.</p>", wait=False)
    return {"ok": True, "id": app_id}
