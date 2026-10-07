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


def auth_url() -> str:
    flow = _flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    store.kv_set("google_oauth_state", state)
    # código de segurança (PKCE) precisa ser o mesmo no retorno
    verifier = getattr(flow, "code_verifier", None)
    if verifier:
        store.kv_set("google_code_verifier", verifier)
    return url


def handle_callback(full_url: str) -> None:
    flow = _flow(state=store.kv_get("google_oauth_state"))
    verifier = store.kv_get("google_code_verifier")
    if verifier:
        flow.code_verifier = verifier
    flow.fetch_token(authorization_response=full_url)
    store.kv_set("google_creds", flow.credentials.to_json())


def credentials() -> Credentials:
    raw = store.kv_get("google_creds")
    if not raw:
        raise RuntimeError("Conta Google ainda não conectada. Abra /auth/google/start.")
    creds = Credentials.from_authorized_user_info(json.loads(raw), config.GOOGLE_SCOPES)
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
