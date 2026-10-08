# Fidus - manda as mudancas do app direto para o celular (sem APK novo)
# Rode na pasta fidus\app:  powershell -ExecutionPolicy Bypass -File .\update-app.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$dest = Join-Path (Split-Path $PSScriptRoot -Parent) "fidus-app"
Copy-Item (Join-Path $PSScriptRoot "App.tsx") $dest -Force
Set-Location $dest
npx --yes eas-cli@latest update --branch preview --environment preview --message "atualizacao $(Get-Date -Format 'dd/MM HH:mm')" --platform android
Write-Host "Pronto. Feche o Fidus no celular e abra de novo (2 vezes) para receber." -ForegroundColor Green
