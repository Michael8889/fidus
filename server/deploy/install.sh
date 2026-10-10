#!/usr/bin/env bash
# Instala/atualiza o Fidus no servidor.
# Uso: bash install.sh app.heyfidus.com "heyfidus.com www.heyfidus.com fidus.148-230-123-44.sslip.io"
# O primeiro é o endereço principal (vai para o .env); os outros também respondem (endereços antigos e o site).
set -euo pipefail
DOMAIN="${1:-app.heyfidus.com}"
EXTRA="${2:-}"
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
MYIP=$(curl -fsS -4 https://api.ipify.org || hostname -I | awk '{print $1}')
points_here() { [ "$(getent ahostsv4 "$1" | awk 'NR==1{print $1}' || true)" = "$MYIP" ]; }
if points_here "$DOMAIN"; then
  if grep -q '^FIDUS_PUBLIC_BASE_URL=' .env; then
    sed -i "s#^FIDUS_PUBLIC_BASE_URL=.*#FIDUS_PUBLIC_BASE_URL=https://$DOMAIN#" .env
  else
    echo "FIDUS_PUBLIC_BASE_URL=https://$DOMAIN" >> .env
  fi
else
  warn "$DOMAIN ainda não aponta para $MYIP: o endereço público continua o anterior."
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

say "4/5 Nginx (só o site do Fidus; os outros sites não são tocados)"
if [ -d /etc/nginx/sites-available ]; then
  CONF=/etc/nginx/sites-available/fidus.conf; LINK=/etc/nginx/sites-enabled/fidus.conf
else
  CONF=/etc/nginx/conf.d/fidus.conf; LINK=""
fi
# nomes que o Fidus atende: os pedidos agora que já apontam para este servidor + os que ele já atendia
NAMES=""
for n in $DOMAIN $EXTRA; do
  if points_here "$n"; then NAMES="$NAMES $n"; else warn "$n ainda não aponta para $MYIP: fica para a próxima vez."; fi
done
if [ -f "$CONF" ]; then
  for n in $(grep -hoP '^\s*server_name\s+\K[^;]+' "$CONF" | tr ' ' '\n' | sort -u); do
    case " $NAMES " in *" $n "*) ;; *) NAMES="$NAMES $n";; esac
  done
fi
NAMES=$(echo $NAMES | tr ' ' '\n' | awk 'NF && !seen[$0]++' | tr '\n' ' ' | sed 's/ $//')
[ -z "$NAMES" ] && NAMES="$DOMAIN"
echo "Endereços do Fidus: $NAMES"
if [ -f "$CONF" ] && ! grep -q "managed-by-fidus" "$CONF"; then
  warn "$CONF não foi criado por este script: não mexo nele."; exit 1
fi
CURRENT=$( [ -f "$CONF" ] && grep -hoP '^\s*server_name\s+\K[^;]+' "$CONF" | tr ' ' '\n' | sort -u | tr '\n' ' ' || true)
WANTED=$(echo $NAMES | tr ' ' '\n' | sort -u | tr '\n' ' ')
write_conf() {
  cat > "$CONF" <<NGINX
# managed-by-fidus
server {
    listen 80;
    listen [::]:80;
    server_name $NAMES;
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
  [ -n "$LINK" ] && ln -sf "$CONF" "$LINK"
}
BACKUP=""
if [ -f "$CONF" ] && grep -q "ssl_certificate" "$CONF" && [ "$CURRENT" = "$WANTED" ]; then
  # mesmos endereços: só atualiza a porta e o tamanho máximo
  sed -i "s#proxy_pass http://127.0.0.1:[0-9]*;#proxy_pass http://127.0.0.1:$PORT;#" "$CONF"
  sed -i "s#client_max_body_size [0-9]*m;#client_max_body_size 100m;#g" "$CONF"
  NEED_CERT=0
else
  if [ -f "$CONF" ]; then
    mkdir -p /opt/fidus/backup; BACKUP=/opt/fidus/backup/fidus.conf.$(date +%Y%m%d%H%M%S)
    cp "$CONF" "$BACKUP"; echo "Cópia da configuração anterior: $BACKUP"
  fi
  write_conf; NEED_CERT=1
fi
restore() {
  if [ -n "$BACKUP" ]; then cp "$BACKUP" "$CONF"; else rm -f "$CONF" ${LINK:+"$LINK"}; fi
  nginx -t >/dev/null 2>&1 && systemctl reload nginx
}
if nginx -t 2>/tmp/fidus-nginx-test; then
  systemctl reload nginx && echo "Nginx recarregado. Outros sites intactos."
else
  cat /tmp/fidus-nginx-test; echo "Configuração inválida: voltando a anterior."; restore; exit 1
fi

say "5/5 HTTPS (Let's Encrypt)"
if [ "$NEED_CERT" = 1 ]; then
  if ! command -v certbot >/dev/null; then
    apt-get update -qq && apt-get install -y -qq certbot python3-certbot-nginx
  fi
  ARGS=""; for n in $NAMES; do ARGS="$ARGS -d $n"; done
  if ! certbot --nginx $ARGS --expand --non-interactive --agree-tos --register-unsafely-without-email --redirect; then
    warn "O certificado não saiu: voltando a configuração anterior (o Fidus continua no ar como estava)."
    restore
    OLD=$( [ -n "$BACKUP" ] && grep -m1 -oP '^\s*server_name\s+\K[^ ;]+' "$BACKUP" || true)
    if [ -n "$OLD" ]; then OLD_URL="https://$OLD"; fi
    if [ -n "${OLD_URL:-}" ]; then
      sed -i "s#^FIDUS_PUBLIC_BASE_URL=.*#FIDUS_PUBLIC_BASE_URL=$OLD_URL#" .env && (cd deploy && FIDUS_PORT=$PORT $DC up -d >/dev/null)
    fi
    exit 1
  fi
fi
echo
for n in $NAMES; do
  curl -fsS "https://$n/health" >/dev/null 2>&1 && echo -e "\033[1;32mFidus no ar: https://$n\033[0m" || warn "https://$n ainda não respondeu"
done
