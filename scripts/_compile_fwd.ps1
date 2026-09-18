param([Parameter(Mandatory=$true)][string]$Source,
      [Parameter(Mandatory=$true)][string]$TerminalHash)
$ErrorActionPreference = 'Stop'
$termDir = Join-Path $env:APPDATA "MetaQuotes\Terminal\$TerminalHash"
$rel = Join-Path 'MQL5\Experts\MITEMSHUB_AI' (Split-Path $Source -Leaf)
$dst = Join-Path $termDir $rel
New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
Copy-Item $Source $dst -Force
$log = Join-Path $env:TEMP ("compile_" + (Split-Path $Source -Leaf) + ".log")
$me = 'C:\Program Files\MetaTrader 5 Terminal\metaeditor64.exe'
$p = Start-Process -FilePath $me -ArgumentList "/compile:`"$dst`"","/log:`"$log`"" -Wait -PassThru
Get-Content $log | Select-Object -Last 6
$ex5 = $dst -replace '\.mq5$', '.ex5'
if ((Test-Path $ex5) -and ((Get-Item $ex5).LastWriteTime -ge (Get-Item $dst).LastWriteTime)) {
    Write-Host "GATE PASS: fresh .ex5 at $ex5"
    exit 0
} else {
    Write-Host "GATE FAIL: no fresh .ex5"
    exit 3
}
