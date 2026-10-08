"""Atualiza a lista I18N_KEYS do App.tsx com todos os textos t("...") do arquivo.
Rode depois de mudar textos do app:  python i18n-keys.py"""
import json
import re
import pathlib

p = pathlib.Path(__file__).with_name("App.tsx")
src = p.read_text(encoding="utf-8")
keys = []
for raw in re.findall(r'\bt\(\s*"((?:[^"\\]|\\.)*)"', src):
    k = json.loads(f'"{raw}"')
    if k not in keys:
        keys.append(k)
body = "const I18N_KEYS: string[] = [\n" + "".join(f"  {json.dumps(k, ensure_ascii=False)},\n" for k in keys) + "];"
src = re.sub(r"(// @i18n-keys-start\n).*?(\n// @i18n-keys-end)", lambda m: m.group(1) + body + m.group(2), src, flags=re.S)
p.write_text(src, encoding="utf-8")
# a mesma lista vai para o servidor: ele só traduz textos que estão nela
pathlib.Path(__file__).resolve().parent.parent.joinpath("server", "app", "i18n_keys.json").write_text(
    json.dumps(keys, ensure_ascii=False, indent=0), encoding="utf-8")
print(len(keys), "textos")
