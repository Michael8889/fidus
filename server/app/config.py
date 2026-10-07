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
# Países onde buscar endereços (códigos ISO separados por vírgula), ex. "gb,pt,br"
HOME_COUNTRIES = env("FIDUS_HOME_COUNTRIES", "gb,pt,br")

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
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
PUBLIC_BASE_URL = env("FIDUS_PUBLIC_BASE_URL", "http://localhost:8000")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

DB_PATH = env("FIDUS_DB_PATH", "fidus.db")
