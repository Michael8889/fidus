"""Configuração do Fidus, lida de variáveis de ambiente (.env)."""
import os
from dotenv import load_dotenv

load_dotenv()


def env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


# Token simples para o app falar com o servidor (MVP de um usuário)
APP_TOKEN = env("FIDUS_APP_TOKEN", "troque-este-token")

# Fuso e idioma padrão do usuário
USER_TIMEZONE = env("FIDUS_TIMEZONE", "Europe/London")
USER_NAME = env("FIDUS_USER_NAME", "Mike")
# Idioma e país do dono (os clientes recebem o do celular)
OWNER_LANGUAGE = env("FIDUS_LANGUAGE", "pt")
# Países onde buscar endereços (códigos ISO separados por vírgula), ex. "gb,pt,br"
HOME_COUNTRIES = env("FIDUS_HOME_COUNTRIES", "gb,pt,br")
OWNER_COUNTRY = (env("FIDUS_COUNTRY") or HOME_COUNTRIES.split(",")[0]).strip().upper()

# Finanças: empresas/carteiras do usuário e moeda padrão
BUSINESSES = [b.strip() for b in env("FIDUS_BUSINESSES", "Pessoal,HomB,Harvest Coffee,Imóveis Portugal").split(",") if b.strip()]
DEFAULT_CURRENCY = env("FIDUS_DEFAULT_CURRENCY", "GBP")
CATEGORIES = ["combustível", "alimentação", "transporte", "materiais", "ferramentas", "manutenção",
              "escritório", "software", "telefone e internet", "impostos e taxas", "moradia", "saúde",
              "lazer", "viagem", "salários e prestadores", "outros"]
RECEIPTS_DIR = env("FIDUS_RECEIPTS_DIR", "receipts")
# pasta-mãe dos dados (reuniões, exportações); no servidor fica em /data
DATA_DIR = env("FIDUS_DATA_DIR") or os.path.dirname(os.path.abspath(RECEIPTS_DIR))

# Provedor de IA: "anthropic" ou "openai_compat" (OpenAI, Mistral, vLLM, Ollama...)
LLM_PROVIDER = env("FIDUS_LLM_PROVIDER", "anthropic")
LLM_MODEL = env("FIDUS_LLM_MODEL", "claude-sonnet-5-5")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
# Modelo mais barato para tarefas simples (tradução de telas, textos fixos)
LLM_MODEL_LIGHT = env("FIDUS_LLM_MODEL_LIGHT", "claude-haiku-4-5-20251001" if env("FIDUS_LLM_PROVIDER", "anthropic") == "anthropic" else "") or None
# Preço de um modelo fora da lista do llm.py: "entrada,saída,gravar_cache,ler_cache" em US$ por milhão de tokens
CUSTOM_PRICES = tuple(float(x) for x in (env("FIDUS_LLM_PRICES", "") or "").split(",") if x.strip()) or None
# Uso justo: gasto de IA por cliente por dia (US$). Passou, o Fidus pede para continuar amanhã. 0 = sem limite.
FAIR_USE_DAILY_USD = float(env("FIDUS_FAIR_USE_DAILY_USD", "5") or 0)
# Necessário só para chaves que valem para vários workspaces (começa com wrkspc_)
ANTHROPIC_WORKSPACE_ID = (env("ANTHROPIC_WORKSPACE_ID") or "").strip() or None
OPENAI_COMPAT_BASE_URL = env("OPENAI_COMPAT_BASE_URL", "https://api.openai.com/v1")
OPENAI_COMPAT_API_KEY = env("OPENAI_COMPAT_API_KEY")

# Busca na web (só com Anthropic). Desligue com FIDUS_WEB_SEARCH=0
WEB_SEARCH = (env("FIDUS_WEB_SEARCH", "1") or "1").strip() not in ("0", "false", "no") and LLM_PROVIDER == "anthropic"
WEB_SEARCH_COUNTRY = env("FIDUS_WEB_SEARCH_COUNTRY", "GB")

# Planos: o plano deste servidor (até o pagamento existir) e a página para fazer upgrade
DEFAULT_PLAN = env("FIDUS_PLAN", "premium")
UPGRADE_URL = env("FIDUS_UPGRADE_URL", "")  # página de planos/checkout; vazio até o pagamento existir

# Transcrição local (faster-whisper): tiny, base, small, medium, large-v3
WHISPER_MODEL = env("FIDUS_WHISPER_MODEL", "small")

# Google OAuth
# Voz natural (Google Text-to-Speech). Sem a chave, o app usa a voz do celular.
GOOGLE_TTS_KEY = env("FIDUS_GOOGLE_TTS_KEY", "")
TTS_TIER = env("FIDUS_TTS_TIER", "wavenet")  # wavenet (mais barata) | neural2 | chirp3 (mais natural)
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
PUBLIC_BASE_URL = env("FIDUS_PUBLIC_BASE_URL", "http://localhost:8000")
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",  # planilhas: opcional (quem conectou antes reconecta para ganhar)
]

DB_PATH = env("FIDUS_DB_PATH", "fidus.db")  # banco do dono (Mike); clientes têm um banco cada

# Contas de clientes
ACCOUNTS_DB = env("FIDUS_ACCOUNTS_DB") or os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "accounts.db")
OWNER_EMAIL = (env("FIDUS_OWNER_EMAIL", "") or "").strip().lower()  # e-mail Google do dono (vira admin)
SIGNUP_OPEN = (env("FIDUS_SIGNUP_OPEN", "0") or "0").strip() in ("1", "true", "yes")  # 0 = só convidados
NEW_USER_PLAN = env("FIDUS_NEW_USER_PLAN", "essencial")
APP_SCHEME = env("FIDUS_APP_SCHEME", "fidus")  # link que reabre o app depois do login

# Convites: com 1, um código de indicação válido vale como convite mesmo com o cadastro fechado (até 10 contas
# novas por código por dia). Padrão 0 enquanto o acesso for só por convite.
REFERRAL_SIGNUP = (env("FIDUS_REFERRAL_SIGNUP", "0") or "0").strip() in ("1", "true", "yes")
REFERRAL_TRIAL_DAYS = int(env("FIDUS_REFERRAL_TRIAL_DAYS", "7") or 7)
REFERRAL_PERCENT = int(env("FIDUS_REFERRAL_PERCENT", "10") or 10)
APP_DOWNLOAD_URL = env("FIDUS_APP_DOWNLOAD_URL", "")  # página/loja para baixar o app (link de convite)
BILLING_WEBHOOK_SECRET = (env("FIDUS_BILLING_WEBHOOK_SECRET", "") or "").strip()  # segredo do aviso da RevenueCat
# Chaves PÚBLICAS do SDK da RevenueCat (começam com goog_ / appl_). Ficam no app de qualquer jeito; não são segredo.
REVENUECAT_ANDROID_KEY = (env("FIDUS_REVENUECAT_ANDROID_KEY", "") or "").strip()
REVENUECAT_IOS_KEY = (env("FIDUS_REVENUECAT_IOS_KEY", "") or "").strip()
# E-mails do Fidus para os clientes (código de entrada, boas-vindas, assinatura, convite). Serviço: Resend.
RESEND_API_KEY = (env("FIDUS_RESEND_API_KEY", "") or "").strip()
# dados da empresa nas páginas de privacidade e termos (/privacy, /terms)
COMPANY_ADDRESS = (env("FIDUS_COMPANY_ADDRESS", "") or "").strip()
SUPPORT_EMAIL = (env("FIDUS_SUPPORT_EMAIL", "") or "").strip()
# link do diagnóstico gratuito de 30 min (vai nos e-mails de dicas); sem ele, os convites não saem
MENTOR_BOOKING_URL = (env("FIDUS_MENTOR_BOOKING_URL", "") or "").strip()
EMAIL_FROM = (env("FIDUS_EMAIL_FROM", "") or "").strip()  # ex. "Fidus <ola@seudominio.com>"
