param([Parameter(Mandatory=$true)][string]$TerminalHash)
$ErrorActionPreference = 'Stop'
$termDir = Join-Path $env:APPDATA "MetaQuotes\Terminal\$TerminalHash"
$repo    = Join-Path $PSScriptRoot '..\V75MacroEngine.mq5'
$v75Dir  = Join-Path $termDir 'MQL5\Experts\V75MacroEngine'
$target  = Join-Path $v75Dir 'V75MacroEngine.mq5'
$log     = Join-Path $env:TEMP "v75_compile_$TerminalHash.log"
$me      = 'C:\Program Files\MetaTrader 5 Terminal\metaeditor64.exe'

if (-not (Test-Path $v75Dir)) { New-Item -ItemType Directory -Path $v75Dir -Force | Out-Null }
Copy-Item $repo $target -Force

if (Test-Path $log) { Remove-Item $log -Force }
$proc = Start-Process -FilePath $me -ArgumentList "/compile:`"$target`" /log:`"$log`"" -Wait -PassThru

if (Test-Path $log) {
    Get-Content $log | Select-Object -Last 2
    if ((Get-Content $log | Select-Object -Last 3 | Out-String) -notmatch 'Result: 0 errors') {
        Write-Host "COMPILE FAILED for $TerminalHash"; exit 2
    }
} else { Write-Host 'NO LOG'; exit 2 }

$ex5 = Join-Path $v75Dir 'V75MacroEngine.ex5'
if ((Test-Path $ex5) -and ((Get-Item $ex5).LastWriteTime -ge (Get-Item $target).LastWriteTime)) {
    Write-Host "GATE PASS: fresh .ex5 in $TerminalHash"
} else { Write-Host "GATE FAIL for $TerminalHash"; exit 3 }
