# Fidus

Assistente pessoal por voz: agenda, e-mail, gastos, recibos, documentos, tarefas, atas de reunião e link de
agendamento. O usuário fala ou digita no app; o servidor transcreve (Whisper local), a IA decide e usa
ferramentas (Google Agenda, Gmail, banco de dados próprio). Nada sai em nome do usuário sem o toque dele.

```
fidus/
├── server/            API (Python, FastAPI) — roda em Docker no servidor
│   ├── app/
│   │   ├── main.py        endpoints HTTP (app, link público de agendamento, OAuth do Google)
│   │   ├── agent.py       "cérebro": prompt, laço de ferramentas, registro na aba Atividade
│   │   ├── tools.py       ferramentas de agenda, gastos e e-mail + roteamento + bloqueio por plano
│   │   ├── features.py    lembretes, tarefas, documentos, contas fixas, bom dia, semana, contador, assinaturas
│   │   ├── meetings.py    ata de reunião (transcrição em segundo plano + resumo + tarefas)
│   │   ├── booking.py     página pública de agendamento
│   │   ├── plans.py       planos Essencial / Negócio / Premium e oferta de upgrade
│   │   ├── llm.py         adaptador de IA (Anthropic ou qualquer API compatível com OpenAI)
│   │   ├── transcribe.py  Whisper local via FFmpeg
│   │   ├── google_client.py, store.py (SQLite), config.py (.env)
│   ├── tests/             pytest — rodar antes de qualquer publicação
│   ├── deploy/            docker-compose.yml + install.sh (Nginx + HTTPS, sem mexer nos outros sites)
│   └── deploy-hetzner.ps1 publica do Windows para o servidor
└── app/               App Android/iOS (Expo / React Native, SDK 57) — um arquivo: App.tsx
    ├── build-apk.ps1      gera o APK na nuvem da Expo (só quando muda módulo nativo)
    └── update-app.ps1     manda mudanças de App.tsx direto para os celulares (sem APK novo)
```

## Rodar os testes
```bash
cd server
pip install -r requirements.txt pytest httpx
python -m pytest -q
```

## Publicar o servidor
Do Windows (pasta `server`): `powershell -ExecutionPolicy Bypass -File .\deploy-hetzner.ps1`

Ou direto no servidor, com o código em `/tmp/fidus`:
```bash
cp -r /tmp/fidus/server/. /opt/fidus/server/ && bash /opt/fidus/server/deploy/install.sh fidus.148-230-123-44.sslip.io
```
O `install.sh` escolhe uma porta livre, sobe o contêiner, cria só o site do Fidus no Nginx (testa com
`nginx -t` e desfaz se falhar) e pede o HTTPS. O `.env`, o banco e os modelos em `deploy/data` e
`deploy/models` não são tocados.

## Publicar o app
- Mudou só `App.tsx`: pasta `app`, `update-app.ps1`. Os celulares recebem ao abrir o app duas vezes.
- Mudou `app.json` ou entrou módulo nativo novo: `build-apk.ps1` e instalar o APK novo.

## Configuração
Tudo no `server/.env` (modelo em `server/.env.example`). Trocar de IA = mudar `FIDUS_LLM_PROVIDER`.
Reconectar o Google: no app, menu ⋯ › Reconectar Google.

## Regras que não podem quebrar
- **Nada sai em nome do usuário sem confirmação.** E-mails, atas e convites viram ação pendente; o envio
  só acontece em `/v1/actions/{id}/confirm`, com trava atômica (um toque = um envio).
- **A página pública de agendamento não envia e-mails** da conta do usuário (evita spam pela página).
- **OAuth do Google só por link assinado** gerado pelo app.
- Áudio de comandos e de reuniões é apagado depois da transcrição.
- `.env`, `*.db`, recibos e dados nunca entram no Git.
- No servidor da HomB rodam outros agentes: nunca parar contêineres alheios nem editar sites do Nginx que
  não sejam o `fidus.conf`.
