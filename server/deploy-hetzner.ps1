# Fidus - envia o servidor para o Hetzner e instala.
# Uso (na pasta fidus\server):  powershell -ExecutionPolicy Bypass -File .\deploy-hetzner.ps1
param([string]$Server = "root@148.230.123.44", [string]$Domain = "app.heyfidus.com",
      [string]$Extra = "heyfidus.com www.heyfidus.com fidus.148-230-123-44.sslip.io")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$pkg = Join-Path $env:TEMP "fidus-server.tgz"
Write-Host "Empacotando (sem .venv e caches)..." -ForegroundColor Yellow
tar -czf $pkg --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=deploy/data --exclude=deploy/models -C .. server
Write-Host "Enviando para $Server (vai pedir a senha)..." -ForegroundColor Yellow
scp $pkg "${Server}:/tmp/fidus-server.tgz"
Write-Host "Instalando no servidor (vai pedir a senha de novo)..." -ForegroundColor Yellow
ssh $Server "mkdir -p /opt/fidus && tar -xzf /tmp/fidus-server.tgz -C /opt/fidus && rm /tmp/fidus-server.tgz && sed -i 's/\r$//' /opt/fidus/server/deploy/install.sh && bash /opt/fidus/server/deploy/install.sh $Domain '$Extra'"
Remove-Item $pkg
