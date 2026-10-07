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
    flow.redirect_uri = config.PUBLIC_BASE_URL + REDIRECT_PATH
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


def save_credentials(creds: Credentials, email: str | None = None) -> None:
    """Guarda no banco do cliente atual (e de qual conta Google elas são)."""
    store.kv_set("google_creds", creds.to_json())
    if email:
        store.kv_set("google_email", email.lower())


def credentials() -> Credentials:
    raw = store.kv_get("google_creds")
    if not raw:
        raise RuntimeError("Conta Google ainda não conectada. No app: menu ⋯ › Reconectar Google.")
    # usa os escopos que o cliente autorizou (pedir outros no refresh dá erro)
    creds = Credentials.from_authorized_user_info(json.loads(raw))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        store.kv_set("google_creds", creds.to_json())
    return creds


def is_connected() -> bool:
    return store.kv_get("google_creds") is not None


def calendar():
    return build("calendar", "v3", credentials=credentials(), cache_discovery=False)


def gmail():
    return build("gmail", "v1", credentials=credentials(), cache_discovery=False)
