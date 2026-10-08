"""E-mails do próprio Fidus para os clientes (código de entrada, boas-vindas, assinatura, convite aceito).

Saem pelo Resend (https://resend.com), de um endereço do domínio do Fidus. Não usam o Gmail do cliente.
Sem FIDUS_RESEND_API_KEY e FIDUS_EMAIL_FROM, nada é enviado (e a entrada por e-mail fica escondida no app).
"""
import html
import logging
import threading

from . import config

log = logging.getLogger("fidus.mailer")


def enabled() -> bool:
    return bool(config.RESEND_API_KEY and config.EMAIL_FROM)


def _deliver(to: str, subject: str, html_body: str, text: str) -> None:
    import requests
    r = requests.post("https://api.resend.com/emails", timeout=15,
                      headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
                      json={"from": config.EMAIL_FROM, "to": [to], "subject": subject, "html": html_body, "text": text})
    if r.status_code >= 300:
        raise RuntimeError(f"Resend {r.status_code}: {r.text[:200]}")


def send(to: str, kind: str, lang: str = "pt", wait: bool = False, **v) -> bool:
    """Monta e manda o e-mail. wait=False: em segundo plano (não atrasa a resposta)."""
    if not enabled() or not to:
        return False
    subject, body = render(kind, lang, **v)
    page = _layout(body)
    text = body.replace("<br>", "\n")
    for tag in ("<b>", "</b>", "<p>", "</p>"):
        text = text.replace(tag, "\n" if tag == "</p>" else "")
    if wait:
        _deliver(to, subject, page, text)
        return True

    def run():
        try:
            _deliver(to, subject, page, text)
        except Exception as e:  # noqa: BLE001
            log.warning("e-mail %s para %s falhou: %s", kind, to, e)
    threading.Thread(target=run, daemon=True).start()
    return True


def _layout(body: str) -> str:
    return ('<div style="background:#F4F6F8;padding:32px 12px;font-family:Arial,Helvetica,sans-serif">'
            '<div style="max-width:520px;margin:0 auto;background:#fff;border-radius:16px;padding:28px;color:#07090D;'
            'font-size:15px;line-height:1.55"><div style="font-weight:800;font-size:22px;margin-bottom:16px">'
            '<span style="display:inline-block;width:30px;height:30px;line-height:30px;text-align:center;border-radius:9px;'
            'background:#3DDC97;color:#07090D;margin-right:8px">F</span>Fidus</div>' + body + '</div></div>')


_T = {
    "login_code": {
        "pt": ("Seu código do Fidus: {code}", "<p>Seu código para entrar no Fidus:</p><p style='font-size:32px;font-weight:800;letter-spacing:6px'>{code}</p><p>Vale por 10 minutos. Se não foi você, ignore este e-mail: ninguém entra sem o código.</p>"),
        "en": ("Your Fidus code: {code}", "<p>Your code to sign in to Fidus:</p><p style='font-size:32px;font-weight:800;letter-spacing:6px'>{code}</p><p>It is valid for 10 minutes. If this wasn't you, ignore this email: no one gets in without the code.</p>"),
        "es": ("Tu código de Fidus: {code}", "<p>Tu código para entrar en Fidus:</p><p style='font-size:32px;font-weight:800;letter-spacing:6px'>{code}</p><p>Vale 10 minutos. Si no fuiste tú, ignora este correo: nadie entra sin el código.</p>"),
    },
    "use_google": {
        "pt": ("Entre no Fidus com o Google", "<p>Alguém pediu um código para entrar no Fidus com este e-mail.</p><p>A sua conta entra com o <b>Google</b>: no app, toque em <b>Entrar com o Google</b>. Se não foi você, ignore este e-mail.</p>"),
        "en": ("Sign in to Fidus with Google", "<p>Someone asked for a code to sign in to Fidus with this email.</p><p>Your account signs in with <b>Google</b>: in the app, tap <b>Sign in with Google</b>. If this wasn't you, ignore this email.</p>"),
        "es": ("Entra en Fidus con Google", "<p>Alguien pidió un código para entrar en Fidus con este correo.</p><p>Tu cuenta entra con <b>Google</b>: en la app, toca <b>Entrar con Google</b>. Si no fuiste tú, ignora este correo.</p>"),
    },
    "welcome": {
        "pt": ("Bem-vindo ao Fidus, {name}", "<p>Olá, {name}!</p><p>Seu assessor já está pronto. Para começar:</p><p>• Toque no microfone e fale: <b>“marca almoço com o contador sexta à uma”</b><br>• Mande a foto de um recibo e ele lança o gasto<br>• Pergunte <b>“o que eu tenho hoje?”</b> todo dia de manhã</p><p>Nada sai em seu nome sem você mandar. Qualquer dúvida, é só responder este e-mail.</p>"),
        "en": ("Welcome to Fidus, {name}", "<p>Hi {name}!</p><p>Your assistant is ready. To get started:</p><p>• Tap the mic and say: <b>“lunch with the accountant Friday at 1”</b><br>• Send a photo of a receipt and it logs the expense<br>• Ask <b>“what have I got today?”</b> every morning</p><p>Nothing goes out in your name unless you say so. Any questions, just reply to this email.</p>"),
        "es": ("Bienvenido a Fidus, {name}", "<p>¡Hola, {name}!</p><p>Tu asistente ya está listo. Para empezar:</p><p>• Toca el micrófono y di: <b>“comida con el contable el viernes a la una”</b><br>• Envía la foto de un recibo y anota el gasto<br>• Pregunta <b>“¿qué tengo hoy?”</b> cada mañana</p><p>Nada sale en tu nombre sin tu orden. Si tienes dudas, responde a este correo.</p>"),
    },
    "sub_started": {
        "pt": ("Seu plano {plan} está ativo", "<p>Pronto, {name}: o plano <b>{plan}</b> está ativo.</p><p>O recibo do pagamento vem da loja onde você assinou. Para trocar de plano ou cancelar, use o app: menu › Configurações.</p>"),
        "en": ("Your {plan} plan is active", "<p>Done, {name}: your <b>{plan}</b> plan is active.</p><p>The payment receipt comes from the store where you subscribed. To change plan or cancel, use the app: menu › Settings.</p>"),
        "es": ("Tu plan {plan} está activo", "<p>Listo, {name}: el plan <b>{plan}</b> está activo.</p><p>El recibo del pago llega de la tienda donde te suscribiste. Para cambiar de plan o cancelar, usa la app: menú › Configuración.</p>"),
    },
    "sub_renewed": {
        "pt": ("Plano {plan} renovado", "<p>{name}, seu plano <b>{plan}</b> foi renovado. Obrigado por continuar com o Fidus.</p>"),
        "en": ("{plan} plan renewed", "<p>{name}, your <b>{plan}</b> plan has been renewed. Thanks for staying with Fidus.</p>"),
        "es": ("Plan {plan} renovado", "<p>{name}, tu plan <b>{plan}</b> se ha renovado. Gracias por seguir con Fidus.</p>"),
    },
    "sub_billing_issue": {
        "pt": ("Não conseguimos cobrar a sua assinatura", "<p>{name}, a loja não conseguiu cobrar o plano <b>{plan}</b>. Confira a forma de pagamento na Google Play ou na App Store para não perder o acesso.</p>"),
        "en": ("We couldn't charge your subscription", "<p>{name}, the store couldn't charge your <b>{plan}</b> plan. Check your payment method in Google Play or the App Store so you don't lose access.</p>"),
        "es": ("No pudimos cobrar tu suscripción", "<p>{name}, la tienda no pudo cobrar el plan <b>{plan}</b>. Revisa la forma de pago en Google Play o App Store para no perder el acceso.</p>"),
    },
    "sub_cancelled": {
        "pt": ("Assinatura cancelada", "<p>{name}, sua assinatura do plano <b>{plan}</b> foi cancelada. Você continua com acesso até o fim do período já pago. Se mudar de ideia, é só assinar de novo pelo app.</p>"),
        "en": ("Subscription cancelled", "<p>{name}, your <b>{plan}</b> subscription has been cancelled. You keep access until the end of the period you've paid for. If you change your mind, just subscribe again in the app.</p>"),
        "es": ("Suscripción cancelada", "<p>{name}, tu suscripción al plan <b>{plan}</b> se ha cancelado. Mantienes el acceso hasta el final del periodo pagado. Si cambias de idea, suscríbete de nuevo en la app.</p>"),
    },
    "sub_expired": {
        "pt": ("Seu plano terminou", "<p>{name}, o período pago do plano <b>{plan}</b> terminou. Seus dados continuam guardados. Para voltar, assine de novo pelo app.</p>"),
        "en": ("Your plan has ended", "<p>{name}, the paid period of your <b>{plan}</b> plan has ended. Your data is still saved. To come back, subscribe again in the app.</p>"),
        "es": ("Tu plan ha terminado", "<p>{name}, el periodo pagado del plan <b>{plan}</b> ha terminado. Tus datos siguen guardados. Para volver, suscríbete de nuevo en la app.</p>"),
    },
    "referral_paid": {
        "pt": ("Você ganhou {percent}% de desconto 🎁", "<p>{name}, {friend} assinou o Fidus com o seu convite.</p><p>Você ganhou <b>{percent}% de desconto</b> numa próxima cobrança. Os descontos não somam: vale um por cobrança, e os que sobram ficam para as seguintes.</p>"),
        "en": ("You earned {percent}% off 🎁", "<p>{name}, {friend} subscribed to Fidus with your invite.</p><p>You earned <b>{percent}% off</b> an upcoming bill. Discounts don't stack: one per bill, and any extra carry over to the next ones.</p>"),
        "es": ("Ganaste un {percent}% de descuento 🎁", "<p>{name}, {friend} se suscribió a Fidus con tu invitación.</p><p>Ganaste un <b>{percent}% de descuento</b> en un próximo cobro. Los descuentos no se suman: uno por cobro, y los que sobran pasan a los siguientes.</p>"),
    },
}
_FALLBACK = {"name": {"pt": "tudo bem", "en": "there", "es": "hola"}, "friend": {"pt": "Um amigo", "en": "A friend", "es": "Un amigo"}}


def render(kind: str, lang: str = "pt", **v) -> tuple[str, str]:
    lang = (lang or "pt").split("-")[0].lower()
    lang = lang if lang in ("pt", "en", "es") else "en"
    subject, body = _T[kind][lang]
    vals = {k: html.escape(str(x)) for k, x in v.items() if x is not None and x != ""}
    for k, d in _FALLBACK.items():
        vals.setdefault(k, d[lang])
    return subject.format(**{k: html.unescape(x) for k, x in vals.items()}), body.format(**vals)
