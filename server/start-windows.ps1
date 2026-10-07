# Fidus - liga o servidor no Windows
Set-Location $PSScriptRoot
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like "192.168.*" -or $_.IPAddress -like "10.*" } | Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "Servidor do Fidus ligando..." -ForegroundColor Green
Write-Host "1) Conectar o Google (uma vez):  http://localhost:8000/auth/google/start"
Write-Host "2) Ver se está tudo ok:           http://localhost:8000/health"
Write-Host "3) No app do celular, use:        http://$($ip):8000"
Write-Host "   (celular e computador no mesmo Wi-Fi; se o Windows perguntar sobre o firewall, clique em Permitir)"
Write-Host ""
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
