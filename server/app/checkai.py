"""Testa os modelos de IA configurados (principal e barato), com uma ferramenta de verdade.

No servidor:  ssh root@148.230.123.44 "docker exec fidus_server python -m app.checkai"
"""
import time

from . import config, llm

TOOL = {"name": "add_expense", "description": "Registra um gasto.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "number"}, "currency": {"type": "string"},
            "category": {"type": "string", "enum": config.CATEGORIES}, "merchant": {"type": "string"}},
            "required": ["amount", "currency", "category"]}}
SYSTEM = "Você é o Fidus, assistente pessoal. Use as ferramentas para registrar o que o usuário pede."


def check(label: str, spec: str | None) -> None:
    if not spec:
        print(f"{label}: (não configurado)")
        return
    if not llm.available(spec):
        print(f"{label}: {spec} -> SEM CHAVE no .env")
        return
    t0 = time.time()
    try:
        out = llm._call(spec, SYSTEM, [{"role": "user", "content": "paguei 45 euros de gasolina na Galp"}], [TOOL], False)
        ms = int((time.time() - t0) * 1000)
        tc = out.get("tool_calls") or []
        if tc:
            print(f"{label}: {spec} -> OK em {ms} ms, chamou {tc[0]['name']} {tc[0]['input']}")
        else:
            print(f"{label}: {spec} -> respondeu sem usar a ferramenta ({ms} ms): {out.get('text', '')[:120]}")
        print(f"   custo desta chamada: US$ {llm.cost_usd(out.get('usage') or {}):.5f}")
    except Exception as e:  # noqa: BLE001
        print(f"{label}: {spec} -> ERRO: {str(e)[:300]}")


if __name__ == "__main__":
    print("Roteador:", "LIGADO" if config.LLM_MODEL_CHEAP else "desligado (tudo no principal)")
    check("Principal", config.LLM_MODEL)
    check("Barato   ", config.LLM_MODEL_CHEAP)
