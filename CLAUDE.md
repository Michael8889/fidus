# Instruções para quem trabalhar neste código (pessoas ou IA)

- Leia o README.md primeiro: estrutura, testes, publicação e as regras que não podem quebrar.
- Idioma do produto e dos textos ao usuário: português (Brasil), com suporte a inglês. Respostas do
  Fidus em texto simples, sem markdown.
- Antes de entregar qualquer mudança no servidor: `cd server && python -m pytest -q` precisa passar.
- Mudança em `app/App.tsx`: checar sintaxe (ex. `npx esbuild App.tsx --loader:.tsx=tsx --outfile=/dev/null`).
  Módulos nativos novos devem ser carregados com `require` dentro de try/catch, porque celulares com APK
  antigo recebem o JS novo pelo update-app.
- Toda ação que fala pelo usuário (e-mail, convite, ata) vira pendência confirmada no app. Nunca criar
  ferramenta que envie direto.
- Ações que mudam dados devem aparecer na aba Atividade (`agent._record`) e, quando possível, ter Desfazer
  (`main.UNDO`).
- Recursos pagos: declarar o plano mínimo em `plans.FEATURE_MIN`; o bloqueio e a oferta de upgrade já
  acontecem em `tools.run`.
- Servidor de produção é compartilhado com outros agentes da HomB: não parar contêineres de terceiros,
  não editar outros sites do Nginx, testar `nginx -t` antes de recarregar, mover arquivos para backup em vez
  de apagar.
- Nunca pedir, ler ou commitar segredos. O dono cola chaves direto no `.env` do servidor.
