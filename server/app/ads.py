"""Meta (Facebook/Instagram) Pixel e Conversions API, só com consentimento.

- Site: o aviso de cookies aparece só se FIDUS_META_PIXEL_ID estiver configurado. Sem "Aceitar", nada da Meta carrega.
- Eventos: Lead (entrou na fila do beta), StartTrial (entrou no app e começou os dias grátis) e Subscribe (assinou).
  Vão pelo navegador (Pixel) e também pelo servidor (Conversions API, se houver FIDUS_META_CAPI_TOKEN), com o mesmo
  event_id para a Meta não contar duas vezes. O servidor só manda de quem aceitou no site.
- O que vai para a Meta: e-mail em hash (SHA-256), país, os cookies _fbp/_fbc da própria Meta e o valor da assinatura.
  Nunca conversas, agenda, e-mails ou despesas.
"""
import hashlib
import logging
import threading
import time

import requests

from . import accounts, config

log = logging.getLogger("fidus.ads")


def enabled() -> bool:
    return bool(config.META_PIXEL_ID)


def _sha(x: str | None) -> str | None:
    x = (x or "").strip().lower()
    return hashlib.sha256(x.encode()).hexdigest() if x else None


def consent_row(email: str) -> dict | None:
    """Linha da lista do site de quem aceitou os cookies de anúncios (com os cookies da Meta guardados)."""
    with accounts._db() as c:
        r = c.execute("SELECT * FROM waitlist WHERE lower(email)=lower(?) AND ads_consent=1", (email or "",)).fetchone()
    return dict(r) if r else None


def remember(email: str, consent: bool, fbp: str = "", fbc: str = "") -> None:
    with accounts._db() as c:
        c.execute("UPDATE waitlist SET ads_consent=?, fbp=COALESCE(NULLIF(?,''),fbp), fbc=COALESCE(NULLIF(?,''),fbc) "
                  "WHERE email=?", (1 if consent else 0, (fbp or "")[:200], (fbc or "")[:300], email))


def send(event: str, email: str, event_id: str, value: float | None = None, currency: str | None = None,
         url: str = "", country: str = "", wait: bool = False) -> bool:
    """Conversions API. Só para quem consentiu e só com o token configurado."""
    if not (config.META_PIXEL_ID and config.META_CAPI_TOKEN):
        return False
    row = consent_row(email)
    if not row:
        return False
    user = {"em": [_sha(email)]}
    if row.get("fbp"):
        user["fbp"] = row["fbp"]
    if row.get("fbc"):
        user["fbc"] = row["fbc"]
    if country:
        user["country"] = [_sha(country)]
    data = {"event_name": event, "event_time": int(time.time()), "event_id": event_id, "action_source": "website",
            "event_source_url": url or config.SITE_URL, "user_data": user}
    if value is not None:
        data["custom_data"] = {"value": round(float(value), 2), "currency": (currency or "EUR").upper()}
    body = {"data": [data], "access_token": config.META_CAPI_TOKEN}
    if config.META_TEST_CODE:
        body["test_event_code"] = config.META_TEST_CODE

    def go():
        try:
            r = requests.post(f"https://graph.facebook.com/{config.META_API_VERSION}/{config.META_PIXEL_ID}/events",
                              json=body, timeout=15)
            if r.status_code >= 300:
                log.warning("Meta CAPI %s: %s", r.status_code, r.text[:200])
        except Exception as e:  # noqa: BLE001
            log.warning("Meta CAPI falhou: %s", e)
    if wait:
        go()
    else:
        threading.Thread(target=go, daemon=True).start()
    return True


# ---------- aviso de cookies + Pixel (injetado no site) ----------
BANNER = r"""<script>
(function(){
var PIXEL="__PIXEL__", KEY="fidus_ads_consent";
var T={
 "pt-pt":["Usamos cookies da Meta para medir os nossos anúncios no Facebook e no Instagram. Só com a sua autorização.","Aceitar","Recusar","Privacidade"],
 "pt":["Usamos cookies da Meta para medir nossos anúncios no Facebook e no Instagram. Só com a sua autorização.","Aceitar","Recusar","Privacidade"],
 "en":["We use Meta cookies to measure our ads on Facebook and Instagram. Only if you agree.","Accept","Decline","Privacy"],
 "es":["Usamos cookies de Meta para medir nuestros anuncios en Facebook e Instagram. Solo si lo autorizas.","Aceptar","Rechazar","Privacidad"]};
function lang(){var q=/[?&]lang=([a-zA-Z-]{2,5})/.exec(location.search||"");var l=((q&&q[1])||document.documentElement.lang||navigator.language||"en").toLowerCase();
 return l.indexOf("pt-pt")===0?"pt-pt":l.indexOf("pt")===0?(/^(Europe\/Lisbon|Atlantic\/(Azores|Madeira))$/.test((Intl.DateTimeFormat().resolvedOptions().timeZone||""))&&l!=="pt-br"?"pt-pt":"pt"):l.indexOf("es")===0?"es":"en";}
function get(){try{return localStorage.getItem(KEY)}catch(e){return null}}
function set(v){try{localStorage.setItem(KEY,v)}catch(e){}}
function load(){if(window.fbq||!PIXEL)return;
 !function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};
 if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version="2.0";n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];
 s.parentNode.insertBefore(t,s)}(window,document,"script","https://connect.facebook.net/en_US/fbevents.js");
 fbq("init",PIXEL);fbq("track","PageView");}
window.fidusConsent=function(){return get()==="yes"};
window.fidusTrack=function(ev,params,id){if(get()!=="yes")return;load();try{fbq("track",ev,params||{},id?{eventID:id}:undefined)}catch(e){}};
window.fidusCookies=function(){var m=/(?:^|; )_fbp=([^;]+)/.exec(document.cookie),c=/(?:^|; )_fbc=([^;]+)/.exec(document.cookie);
 var f=/[?&]fbclid=([^&]+)/.exec(location.search);return{fbp:m?m[1]:"",fbc:c?c[1]:(f?"fb.1."+Date.now()+"."+f[1]:"")}};
if(get()==="yes"){load();return}
if(get()==="no")return;
var t=T[lang()],d=document.createElement("div");
d.setAttribute("role","dialog");d.setAttribute("aria-label",t[3]);
d.style.cssText="position:fixed;left:12px;right:12px;bottom:12px;z-index:9999;max-width:560px;margin:0 auto;background:#0E1218;color:#F2F5F7;border:1px solid #2A3341;border-radius:16px;padding:14px 16px;font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.35)";
var p=document.createElement("p");p.style.margin="0 0 10px";p.textContent=t[0]+" ";
var a=document.createElement("a");a.href="/privacy?lang="+(lang().indexOf("pt")===0?"pt":"en");a.textContent=t[3];a.style.color="#3DDC97";p.appendChild(a);
var row=document.createElement("div");row.style.cssText="display:flex;gap:8px;flex-wrap:wrap";
function b(txt,yes){var x=document.createElement("button");x.textContent=txt;x.style.cssText="flex:1 1 120px;min-height:42px;border-radius:12px;font:700 14px system-ui,sans-serif;cursor:pointer;"+(yes?"background:#3DDC97;color:#07090D;border:0":"background:transparent;color:#F2F5F7;border:1px solid #2A3341");
 x.onclick=function(){set(yes?"yes":"no");d.remove();if(yes)load()};return x}
row.appendChild(b(t[2],false));row.appendChild(b(t[1],true));d.appendChild(p);d.appendChild(row);
(document.body?document.body.appendChild(d):window.addEventListener("DOMContentLoaded",function(){document.body.appendChild(d)}));
})();
</script>"""


def banner() -> str:
    """Script do aviso de cookies (e do Pixel, depois do "Aceitar"). Vazio sem Pixel configurado."""
    if not enabled():
        return ""
    pid = "".join(ch for ch in config.META_PIXEL_ID if ch.isdigit())
    return BANNER.replace("__PIXEL__", pid)
