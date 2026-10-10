# Fidus - manda as mudancas do app direto para o celular (sem APK novo)
# Rode na pasta fidus\app:  powershell -ExecutionPolicy Bypass -File .\update-app.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$dest = Join-Path (Split-Path $PSScriptRoot -Parent) "fidus-app"
Copy-Item (Join-Path $PSScriptRoot "App.tsx") $dest -Force
Set-Location $dest
# modulos que o App.tsx usa: precisam existir aqui para o pacote ser montado
# (num celular com APK antigo, as funcoes que dependem deles so ficam desligadas)
npx expo install expo-updates expo-notifications expo-keep-awake expo-document-picker expo-speech expo-clipboard react-native-purchases expo-local-authentication expo-speech-recognition react-native-svg react-native-webrtc @config-plugins/react-native-webrtc react-native-incall-manager expo-contacts
npx --yes eas-cli@latest update --branch preview --environment preview --message "atualizacao $(Get-Date -Format 'dd/MM HH:mm')" --platform android
if ($LASTEXITCODE -ne 0) {
    Write-Host "A atualizacao FALHOU. Copie as mensagens acima e mande para o Claude." -ForegroundColor Red
    exit 1
}
Write-Host "Pronto. Feche o Fidus no celular e abra de novo (2 vezes) para receber." -ForegroundColor Green
