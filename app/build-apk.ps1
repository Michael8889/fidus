# Fidus - gera o APK para instalar no Android (compila na nuvem da Expo)
# Rode na pasta fidus\app:  powershell -ExecutionPolicy Bypass -File .\build-apk.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$dest = Join-Path (Split-Path $PSScriptRoot -Parent) "fidus-app"
$appJsonDest = Join-Path $dest "app.json"

# guarda o projectId que a Expo gravou no primeiro build (senao ele se perde ao copiar o app.json)
$projectId = $null
if (Test-Path $appJsonDest) {
    $old = Get-Content $appJsonDest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($old.expo.extra.eas.projectId) { $projectId = $old.expo.extra.eas.projectId }
}

Copy-Item (Join-Path $PSScriptRoot "App.tsx") $dest -Force
Copy-Item (Join-Path $PSScriptRoot "eas.json") $dest -Force
New-Item -ItemType Directory -Force (Join-Path $dest "assets") | Out-Null
Copy-Item (Join-Path $PSScriptRoot "assets\*") (Join-Path $dest "assets") -Force

$cfg = Get-Content (Join-Path $PSScriptRoot "app.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($projectId) {
    $cfg.expo | Add-Member -Force -NotePropertyName extra -NotePropertyValue ([pscustomobject]@{ eas = [pscustomobject]@{ projectId = $projectId } })
    $cfg.expo | Add-Member -Force -NotePropertyName updates -NotePropertyValue ([pscustomobject]@{ url = "https://u.expo.dev/$projectId" })
}
[System.IO.File]::WriteAllText($appJsonDest, ($cfg | ConvertTo-Json -Depth 20), (New-Object System.Text.UTF8Encoding $false))

Set-Location $dest
Write-Host "1/4 Login na Expo" -ForegroundColor Yellow
npx --yes eas-cli@latest whoami 2>$null
if ($LASTEXITCODE -ne 0) { npx --yes eas-cli@latest login }
Write-Host "2/4 Instalando modulos (atualizacoes, notificacoes, tela ligada, PDF)" -ForegroundColor Yellow
npx expo install expo-updates expo-notifications expo-keep-awake expo-document-picker expo-speech expo-clipboard react-native-purchases expo-local-authentication expo-speech-recognition react-native-svg react-native-webrtc @config-plugins/react-native-webrtc react-native-incall-manager
Write-Host "3/4 Conferindo dependencias" -ForegroundColor Yellow
npx expo install --check
Write-Host "4/4 Compilando o APK na nuvem. Responda Y (sim) as perguntas." -ForegroundColor Yellow
npx --yes eas-cli@latest build -p android --profile preview
Write-Host "Pronto: abra o link acima NO CELULAR para baixar e instalar o APK." -ForegroundColor Green
