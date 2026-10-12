"""Conexão OAuth com a conta Google do usuário e clientes do Calendar e Gmail."""
import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from . import config, store

REDIRECT_PATH = "/auth/google/callback"

# Teste local: o Google aceita http://localhost como retorno, mas a biblioteca exige
# liberar explicitamente. Em produção (https) isto não é ativado.
if config.PUBLIC_BASE_URL.startswith("http://localhost") or config.PUBLIC_BASE_URL.startswith("http://127.0.0.1"):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
# O Google pode devolver os escopos em outra ordem; isso não é erro.
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"


def _flow(state: str | None = None) -> Flow:
    client_config = {"web": {
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }}
    flow = Flow.from_client_config(client_config, scopes=config.GOOGLE_SCOPES, state=state)
    flow.redirect_uri = config.PUBLIC_BASE_URL.strip().rstrip("/") + REDIRECT_PATH
    return flow


def auth_url() -> tuple[str, str, str | None]:
    """(endereço do Google, state, verificador PKCE). Quem chama guarda state+verificador para o retorno."""
    flow = _flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    return url, state, getattr(flow, "code_verifier", None)


def exchange(full_url: str, state: str, verifier: str | None) -> tuple[Credentials, dict]:
    """Troca o código do Google por credenciais e devolve também quem é (e-mail e nome)."""
    flow = _flow(state=state)
    if verifier:
        flow.code_verifier = verifier
    flow.fetch_token(authorization_response=full_url)
    creds = flow.credentials
    return creds, identity(creds)


def identity(creds: Credentials) -> dict:
    from google.oauth2 import id_token as gid
    tok = getattr(creds, "id_token", None)
    if tok:
        info = gid.verify_oauth2_token(tok, Request(), config.GOOGLE_CLIENT_ID)
        return {"email": info.get("email"), "name": info.get("name"), "sub": info.get("sub"),
                "verified": info.get("email_verified", False)}
    raise RuntimeError("o Google não informou o e-mail da conta")


REQUIRED = {"https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send"}


def has_required_scopes(creds: Credentials) -> bool:
    granted = set(getattr(creds, "granted_scopes", None) or getattr(creds, "scopes", None) or [])
    return REQUIRED.issubset(granted)


def save_credentials(creds: Credentials, email: str | None = None, make_default: bool = True) -> None:
    """Guarda no banco do cliente atual (e de qual conta Google elas são). Conectar o Google faz dele a agenda/e-mail."""
    store.kv_set("google_creds", creds.to_json())
    if make_default:
        store.kv_set("mail_provider", "google")
    if email:
        store.kv_set("google_email", email.lower())


def credentials() -> Credentials:
    raw = store.kv_get("google_creds")
    if not raw:
        raise RuntimeError("Agenda e e-mail ainda não conectados. No app: menu ⋯ › Configurações › Google ou Outlook.")
    # usa os escopos que o cliente autorizou (pedir outros no refresh dá erro)
    creds = Credentials.from_authorized_user_info(json.loads(raw))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        store.kv_set("google_creds", creds.to_json())
    return creds


def google_connected() -> bool:
    return store.kv_get("google_creds") is not None


def provider() -> str | None:
    """De onde vêm a agenda e o e-mail do cliente: 'google', 'microsoft' (Outlook) ou None (nada conectado).
    Vale o último conectado; se só um estiver conectado, é ele."""
    from . import ms_client
    ms, g = ms_client.is_connected(), google_connected()
    if ms and (store.kv_get("mail_provider") == "microsoft" or not g):
        return "microsoft"
    return "google" if g else None


def is_connected() -> bool:
    """Agenda e e-mail conectados (Google ou Outlook)."""
    return provider() is not None


def calendar():
    if provider() == "microsoft":
        from . import ms_client
        return ms_client.Calendar()
    return build("calendar", "v3", credentials=credentials(), cache_discovery=False)


def mail_accounts() -> list[str]:
    """Todas as caixas de e-mail conectadas (Gmail e Outlook juntos), a principal primeiro."""
    from . import ms_client
    have = [p for p, ok in (("google", google_connected()), ("microsoft", ms_client.is_connected())) if ok]
    first = provider()
    return sorted(have, key=lambda p: p != first)


def set_primary(which: str) -> str:
    """Escolhe de onde vem a AGENDA (e a caixa principal de e-mail); a outra caixa continua sendo lida."""
    if which not in mail_accounts():
        raise ValueError("essa conta não está conectada")
    store.kv_set("mail_provider", which)
    return which


def gmail(which: str | None = None):
    if (which or provider()) == "microsoft":
        from . import ms_client
        return ms_client.Mail()
    return build("gmail", "v1", credentials=credentials(), cache_discovery=False)


def sheets():
    return build("sheets", "v4", credentials=credentials(), cache_discovery=False)
