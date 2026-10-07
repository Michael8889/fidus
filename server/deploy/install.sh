#!/usr/bin/env bash
# Instala/atualiza o Fidus no servidor. Uso: bash install.sh fidus.homb.io
set -euo pipefail
DOMAIN="${1:-fidus.homb.io}"
APP=/opt/fidus/server
cd "$APP"

say() { echo -e "\n\033[1;32m==> $*\033[0m"; }
warn() { echo -e "\033[1;33m[aviso] $*\033[0m"; }

say "1/5 Dados (banco e recibos)"
mkdir -p deploy/data/receipts deploy/models
if [ -f fidus.db ] && [ ! -f deploy/data/fidus.db ]; then
  mv fidus.db deploy/data/fidus.db && echo "Banco do seu computador copiado (histórico e conexão Google)."
fi
[ -d receipts ] && cp -rn receipts/. deploy/data/receipts/ 2>/dev/null || true

say "2/5 Endereço público no .env"
if grep -q '^FIDUS_PUBLIC_BASE_URL=' .env; then
  sed -i "s#^FIDUS_PUBLIC_BASE_URL=.*#FIDUS_PUBLIC_BASE_URL=https://$DOMAIN#" .env
else
  echo "FIDUS_PUBLIC_BASE_URL=https://$DOMAIN" >> .env
fi
sed -i 's/\r$//' .env   # remove quebras de linha do Windows

say "3/5 Contêiner"
cd deploy
port_busy() { ss -Htln "sport = :$1" | grep -q .; }
if [ -f .port ]; then
  PORT=$(cat .port)
else
  PORT=""
  for p in $(seq 8095 8199); do
    if ! port_busy "$p"; then PORT=$p; break; fi
  done
  [ -z "$PORT" ] && { echo "Nenhuma porta livre entre 8095 e 8199. Abortando sem mexer em nada."; exit 1; }
  echo "$PORT" > .port
fi
# se a porta salva foi ocupada por outro serviço (e não pelo próprio Fidus), escolhe outra
if port_busy "$PORT" && ! docker ps --format '{{.Names}} {{.Ports}}' | grep -q "^fidus_server .*:$PORT->"; then
  rm -f .port; echo "Porta $PORT ocupada por outro serviço; rode o script de novo para escolher outra."; exit 1
fi
echo "Usando a porta interna $PORT (só 127.0.0.1)."
export FIDUS_PORT=$PORT
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
$DC up -d --build
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then echo "Fidus respondendo em 127.0.0.1:$PORT"; break; fi
  sleep 2; [ "$i" = 30 ] && { echo "O contêiner não respondeu. Logs:"; docker logs --tail 40 fidus_server; exit 1; }
done
cd ..

say "4/5 Nginx (site novo só para $DOMAIN)"
if [ -d /etc/nginx/sites-available ]; then
  CONF=/etc/nginx/sites-available/fidus.conf; LINK=/etc/nginx/sites-enabled/fidus.conf
else
  CONF=/etc/nginx/conf.d/fidus.conf; LINK=""
fi
if [ ! -f "$CONF" ] || grep -q "managed-by-fidus" "$CONF"; then
  # (re)escreve só se o arquivo não existe ou foi criado por este script; o certbot preserva a marca
  if grep -q "ssl_certificate" "$CONF" 2>/dev/null; then
    sed -i "s#proxy_pass http://127.0.0.1:[0-9]*;#proxy_pass http://127.0.0.1:$PORT;#" "$CONF"
    # gravações de reunião são maiores que fotos
    sed -i "s#client_max_body_size [0-9]*m;#client_max_body_size 100m;#g" "$CONF"
  else
  cat > "$CONF" <<NGINX
# managed-by-fidus
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    client_max_body_size 100m;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
NGINX
  fi
  [ -n "$LINK" ] && ln -sf "$CONF" "$LINK"
fi
if nginx -t 2>/tmp/fidus-nginx-test; then
  systemctl reload nginx && echo "Nginx recarregado. Outros sites intactos."
else
  cat /tmp/fidus-nginx-test; echo "Configuração inválida: removendo o site do Fidus e mantendo o Nginx como estava."
  rm -f "$CONF" ${LINK:+"$LINK"}; exit 1
fi

say "5/5 HTTPS (Let's Encrypt)"
MYIP=$(curl -fsS -4 https://api.ipify.org || hostname -I | awk '{print $1}')
DNSIP=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1{print $1}' || true)
if [ "$DNSIP" != "$MYIP" ]; then
  warn "O DNS de $DOMAIN ainda não aponta para $MYIP (agora: '${DNSIP:-nenhum}')."
  warn "Crie o registro A e rode de novo:  bash $APP/deploy/install.sh $DOMAIN"
  exit 0
fi
if ! command -v certbot >/dev/null; then
  apt-get update -qq && apt-get install -y -qq certbot python3-certbot-nginx
fi
if ! grep -q "ssl_certificate" "$CONF"; then
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect
fi
echo
curl -fsS "https://$DOMAIN/health" && echo -e "\n\033[1;32mFidus no ar: https://$DOMAIN\033[0m"
