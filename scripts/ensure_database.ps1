# Make sure the local Supabase database (running in Docker) is up before the server starts.
# Called by 啟動行銷系統.bat. Exit 0 = database reachable on 54322, 1 = gave up.
$env:Path = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:USERPROFILE\scoop\shims;$env:Path"

function Test-Port($port) {
    $client = New-Object Net.Sockets.TcpClient
    try { $client.Connect('127.0.0.1', $port); return $true } catch { return $false } finally { $client.Close() }
}
function Test-Docker { docker info *> $null; return $LASTEXITCODE -eq 0 }
function Wait-For($check, $seconds) {
    $end = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $end) { if (& $check) { return $true }; Start-Sleep -Seconds 3 }
    return $false
}

if (Test-Port 54322) { exit 0 }

$desktop = "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe"
$running = Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue
if (-not (Test-Docker) -and $running) {
    Write-Host 'Docker 正在啟動，等它一下...'
    [void](Wait-For { Test-Docker } 60)
}
if (-not (Test-Docker)) {
    Write-Host '資料庫的底座 Docker 沒在跑，正在重新啟動（約 1～2 分鐘）...'
    # A crashed Docker Desktop leaves socket files that its next start cannot delete
    # ("The file cannot be accessed by the system"); move those folders aside first.
    Get-Process -Name 'Docker Desktop', 'com.docker.*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    $stamp = Get-Date -Format 'yyyyMMddHHmmss'
    foreach ($dir in "$env:LOCALAPPDATA\Docker\run", "$env:LOCALAPPDATA\docker-secrets-engine") {
        if (Test-Path $dir) { Rename-Item $dir ('{0}.stale-{1}' -f (Split-Path $dir -Leaf), $stamp) -ErrorAction SilentlyContinue }
    }
    Start-Process $desktop
    if (-not (Wait-For { Test-Docker } 240)) { Write-Host 'Docker 4 分鐘內沒有起來。'; exit 1 }
}

Write-Host '正在啟動資料庫...'
supabase start *> $null
if (-not (Wait-For { Test-Port 54322 } 240)) { Write-Host '資料庫 4 分鐘內沒有起來。'; exit 1 }
exit 0
