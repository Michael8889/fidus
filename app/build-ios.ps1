# Fidus - gera o app do iPhone na nuvem da Expo e manda para o TestFlight (nao precisa de Mac)
# Rode na pasta fidus\app:  powershell -ExecutionPolicy Bypass -File .\build-ios.ps1
# Antes: conta Apple Developer da empresa aprovada (developer.apple.com). Na 1a vez a Expo pede o login da Apple
# e cria sozinha os certificados, o identificador do app e o app no App Store Connect.
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
New-Item -ItemType Directory -Force (Join-Path $dest "locales") | Out-Null
Copy-Item (Join-Path $PSScriptRoot "locales\*") (Join-Path $dest "locales") -Force

$cfg = Get-Content (Join-Path $PSScriptRoot "app.json") -Raw -Encoding UTF8 | ConvertFrom-Json
# numero do build sempre maior que o anterior (a Apple recusa repetido): data e hora
$cfg.expo.ios | Add-Member -Force -NotePropertyName buildNumber -NotePropertyValue (Get-Date -Format "yyMMdd.HHmm")
if ($projectId) {
    $cfg.expo | Add-Member -Force -NotePropertyName extra -NotePropertyValue ([pscustomobject]@{ eas = [pscustomobject]@{ projectId = $projectId } })
    $cfg.expo | Add-Member -Force -NotePropertyName updates -NotePropertyValue ([pscustomobject]@{ url = "https://u.expo.dev/$projectId" })
}
[System.IO.File]::WriteAllText($appJsonDest, ($cfg | ConvertTo-Json -Depth 20), (New-Object System.Text.UTF8Encoding $false))

Set-Location $dest
Write-Host "1/4 Login na Expo" -ForegroundColor Yellow
npx --yes eas-cli@latest whoami 2>$null
if ($LASTEXITCODE -ne 0) { npx --yes eas-cli@latest login }
Write-Host "2/4 Instalando modulos" -ForegroundColor Yellow
npx expo install expo-updates expo-notifications expo-keep-awake expo-document-picker expo-speech expo-clipboard react-native-purchases expo-local-authentication expo-speech-recognition react-native-svg react-native-webrtc @config-plugins/react-native-webrtc react-native-incall-manager expo-contacts expo-apple-authentication
Write-Host "3/4 Conferindo dependencias" -ForegroundColor Yellow
npx expo install --check
Write-Host "4/4 Compilando para iPhone e enviando ao TestFlight. Entre com o Apple ID da empresa e responda Y (sim)." -ForegroundColor Yellow
npx --yes eas-cli@latest build -p ios --profile production --auto-submit
if ($LASTEXITCODE -ne 0) {
    Write-Host "O build do iPhone FALHOU. Copie as mensagens acima e mande para o Claude." -ForegroundColor Red
    exit 1
}
Write-Host "Pronto. Em 10-30 min o app aparece no TestFlight (App Store Connect > TestFlight)." -ForegroundColor Green
