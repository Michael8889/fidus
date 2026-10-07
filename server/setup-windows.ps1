# Fidus - preparação do servidor no Windows
# Como usar: clique com o botão direito em "setup-windows.ps1" > "Executar com o PowerShell"
# (ou, no PowerShell dentro desta pasta:  powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Need($cmd, $wingetId, $nome) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "Instalando $nome..." -ForegroundColor Yellow
        winget install --id $wingetId -e --accept-source-agreements --accept-package-agreements
        Write-Host "$nome instalado. FECHE e ABRA o PowerShell de novo e rode este script outra vez." -ForegroundColor Cyan
        exit 0
    } else { Write-Host "OK: $nome" -ForegroundColor Green }
}

Need "python" "Python.Python.3.12" "Python 3.12"
Need "ffmpeg" "Gyan.FFmpeg" "FFmpeg (para ler os áudios)"
Need "node"   "OpenJS.NodeJS.LTS" "Node.js (para o app)"

if (-not (Test-Path ".venv")) {
    Write-Host "Criando ambiente Python..." -ForegroundColor Yellow
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    # gera um token aleatório para o app
    $token = -join ((48..57) + (97..122) | Get-Random -Count 40 | ForEach-Object {[char]$_})
    (Get-Content ".env") -replace "FIDUS_APP_TOKEN=.*", "FIDUS_APP_TOKEN=$token" `
                         -replace "FIDUS_PUBLIC_BASE_URL=.*", "FIDUS_PUBLIC_BASE_URL=http://localhost:8000" |
        Set-Content ".env"
    Write-Host "Arquivo .env criado. Abra no Bloco de Notas e preencha ANTHROPIC_API_KEY, GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET." -ForegroundColor Cyan
    notepad .env
}

Write-Host ""
Write-Host "Pronto. Para ligar o servidor, rode:  .\start-windows.ps1" -ForegroundColor Green
