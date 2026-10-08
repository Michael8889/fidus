# Fidus - cria o app (Expo) e abre o QR code para testar no celular
# Rode na pasta fidus\app:  powershell -ExecutionPolicy Bypass -File .\setup-app.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$dest = Join-Path (Split-Path $PSScriptRoot -Parent) "fidus-app"

if (-not (Test-Path $dest)) {
    Write-Host "Criando o projeto do app (leva 1-3 minutos)..." -ForegroundColor Yellow
    Set-Location (Split-Path $PSScriptRoot -Parent)
    npx --yes create-expo-app@latest fidus-app --template blank-typescript --yes
    Set-Location $dest
    npx --yes expo install expo-audio expo-haptics expo-secure-store expo-file-system react-native-safe-area-context expo-image-picker expo-updates expo-notifications expo-keep-awake expo-document-picker expo-speech
} else {
    Set-Location $dest
}

Copy-Item (Join-Path $PSScriptRoot "App.tsx") (Join-Path $dest "App.tsx") -Force
Copy-Item (Join-Path $PSScriptRoot "app.json") (Join-Path $dest "app.json") -Force

Write-Host ""
Write-Host "Pronto. Abra o app Expo Go no Android e escaneie o QR code abaixo." -ForegroundColor Green
Write-Host "(celular no mesmo Wi-Fi do computador)" -ForegroundColor Green
Write-Host ""
npx expo start --lan
