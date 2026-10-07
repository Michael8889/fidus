"""Teste rápido da conexão com a IA. Rode: .\.venv\Scripts\python.exe check_ai.py"""
from app import config

key = (config.ANTHROPIC_API_KEY or "").strip()
print("Provedor:", config.LLM_PROVIDER, "| Modelo:", config.LLM_MODEL)
print("Chave preenchida:", "sim" if key else "NAO", "| começa com:", key[:10] + "..." if key else "-")
print("Workspace ID:", config.ANTHROPIC_WORKSPACE_ID or "(vazio)")

import anthropic

headers = {"anthropic-workspace-id": config.ANTHROPIC_WORKSPACE_ID} if config.ANTHROPIC_WORKSPACE_ID else None
client = anthropic.Anthropic(api_key=key, default_headers=headers)
try:
    r = client.messages.create(model=config.LLM_MODEL, max_tokens=20,
                               messages=[{"role": "user", "content": "Responda só: Fidus OK"}])
    texto = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    print("\nRESULTADO: funcionou ->", texto or "(resposta sem texto)")
except Exception as e:
    print("\nRESULTADO: erro ->", e)
