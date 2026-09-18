# ============================================================
# sync-mt5.ps1 — Sync MQL5 files to ALL MT5 terminal directories
# ============================================================
# Project repo is the single source of truth.
# Edit .mq5 / .set files in mql5/MITEMSHUB_AI/, then run this script.
# ============================================================

param(
    [switch]$SetOnly,
    [switch]$Mq5Only,
    [switch]$AllowWip,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\mql5\MITEMSHUB_AI")).Path
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$MT5Base = "$env:APPDATA\MetaQuotes\Terminal"

# Collect every MQL5 directory (Common + every terminal hash)
$mql5Dirs = @()
$mql5Dirs += Join-Path $MT5Base "Common\MQL5"
Get-ChildItem -Path $MT5Base -Directory | ForEach-Object {
    $mql5 = Join-Path $_.FullName "MQL5"
    if (Test-Path $mql5) { $mql5Dirs += $mql5 }
}
$mql5Dirs = $mql5Dirs | Select-Object -Unique

$synced = 0
$pruned = 0
$termCount = 0
$deployFailures = @()

# --------------------------------------------------------
# DEPLOY GATE (fail-closed) — scripts/deploy_manifest.txt
# The 2026-09-13 incident: a routine sync deployed an uncommitted,
# non-functional WIP engine (MitemshubAI v27.00) over the certified paper
# arms; it emitted nothing but its init line and froze both arms for ~2
# days. "Repo is the source of truth" means the WORKTREE at run time — so
# this gate pins each EA by sha256. A source that does not match its
# manifest pin is NOT copied and NOT compiled into any terminal; the
# deployed copy is left untouched and protected from the prune pass.
# Deploy WIP deliberately: -AllowWip - and only after the WIP has passed the
# telemetry-liveness check (see below).
# --------------------------------------------------------
$manifestPath = Join-Path $PSScriptRoot "deploy_manifest.txt"
# -AllowWip is not a bare human assertion: before a mismatching source may
# deploy over the arms, it must have PROVEN itself alive somewhere else.
# scripts/check_wip_liveness.py (pre-registered 2026-09-15) records evidence
# from a NON-ARM staging terminal: a version-bound init banner in the journal,
# post-init processing lines (the inverse of the banner-then-silence signature
# that froze the arms on 2026-09-13), telemetry written after the banner, and
# a sha256 binding of the deployed source/binary to the exact worktree bytes.
# The verify pass re-checks that artifact against the CURRENT worktree bytes,
# so any edit after validation re-locks the deploy.
$livenessScript = Join-Path $PSScriptRoot "check_wip_liveness.py"
$gatedSkip    = @{}   # manifest rel path (lowercase, /-separated) -> pinned version
$gatePins     = 0
if (-not (Test-Path $manifestPath)) {
    $deployFailures += "DEPLOY GATE: scripts/deploy_manifest.txt is missing - refusing to deploy anything (fail-closed). Restore the manifest, or read it and re-pin deliberately."
} else {
    foreach ($line in Get-Content $manifestPath) {
        $t = $line.Trim()
        if ($t -eq "" -or $t.StartsWith("#")) { continue }
        $p = $t.Split("|")
        if ($p.Count -ne 3) {
            $deployFailures += "DEPLOY GATE: malformed manifest line: $t"
            continue
        }
        $gatePins++
        $rel = $p[0].Trim().ToLower() -replace '\\', '/'
        $abs = Join-Path $RepoRoot ($p[0].Trim() -replace '/', '\')
        if (-not (Test-Path $abs)) {
            # Pinned source absent from the worktree: nothing to copy, but
            # protect the deployed copy from the prune pass and say why.
            $gatedSkip[$rel] = $p[1].Trim()
            $deployFailures += "DEPLOY GATE: pinned source missing from worktree: $($p[0]) (pin $($p[1].Trim()))"
            continue
        }
        $actual = (Get-FileHash -Algorithm SHA256 -Path $abs).Hash.ToLower()
        if ($actual -ne $p[2].Trim().ToLower()) {
            if ($AllowWip) {
                # The bypass itself is gated: the WIP must have recorded,
                # verifiable telemetry-liveness evidence for THESE bytes.
                $verifyOk = $false
                $verifyOut = @()
                try {
                    # default mode IS verify: re-checks the recorded evidence
                    # artifact against the CURRENT worktree bytes
                    $verifyOut = @(& python $livenessScript --src $abs 2>&1)
                    $verifyOk = ($LASTEXITCODE -eq 0)
                } catch {
                    $verifyOut = @("liveness checker could not run: $($_.Exception.Message)")
                }
                if ($verifyOk) {
                    Write-Host "DEPLOY GATE BYPASSED (-AllowWip): $($p[0]) does not match manifest pin $($p[1].Trim()) - deploying worktree copy." -ForegroundColor Yellow
                    $verifyOut | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
                } else {
                    $gatedSkip[$rel] = $p[1].Trim()
                    Write-Host "DEPLOY GATE: $($p[0]) does not match manifest pin $($p[1].Trim()) and -AllowWip is REFUSED: no valid telemetry-liveness evidence for these bytes." -ForegroundColor Red
                    $verifyOut | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
                    $deployFailures += "DEPLOY GATE: -AllowWip refused for $($p[0]) - stage the WIP on a NON-ARM terminal (49E0), compile in place, wait one bar interval, then: python scripts/check_wip_liveness.py --collect --src $($p[0])"
                }
            } else {
                $gatedSkip[$rel] = $p[1].Trim()
                Write-Host "DEPLOY GATE: $($p[0]) does not match manifest pin $($p[1].Trim()) - it will NOT be copied or compiled. Deploy deliberately with -AllowWip after the telemetry-liveness check passes (scripts/check_wip_liveness.py)." -ForegroundColor Red
            }
        } else {
            Write-Host "DEPLOY GATE: $($p[0]) matches manifest pin $($p[1].Trim()) - deploy allowed." -ForegroundColor DarkGray
        }
    }
}

# True when this ProjectDir-relative file is deploy-denied (skip copy /
# compile / prune for it). Manifest paths under mql5/MITEMSHUB_AI map onto
# the mirror tree root, hence the second key form.
function Test-DeployGated([string]$relToProject) {
    if ($gatedSkip.Count -eq 0) { return $false }
    $norm = $relToProject.ToLower() -replace '\\', '/'
    return ($gatedSkip.ContainsKey($norm) -or $gatedSkip.ContainsKey("mql5/mitemshub_ai/$norm"))
}

if ($DryRun) {
    Write-Host ""
    Write-Host "DRY RUN - no files copied, compiled, or pruned." -ForegroundColor Cyan
    Write-Host "Deploy gate: $gatePins pin(s) evaluated, $($gatedSkip.Count) denied."
    $gatedSkip.GetEnumerator() | Sort-Object Key | ForEach-Object {
        Write-Host "  DENY  $($_.Key) (pin $($_.Value))" -ForegroundColor Red
    }
    $wouldMirror = (Get-ChildItem -Path $ProjectDir -Recurse -File |
        Where-Object { -not (Test-DeployGated $_.FullName.Substring($ProjectDir.Length + 1)) }).Count
    Write-Host "  Would mirror $wouldMirror file(s) from mql5/MITEMSHUB_AI into each terminal + Common."
    if (-not $gatedSkip.ContainsKey('v75macroengine.mq5')) {
        Write-Host "  Would copy+compile V75MacroEngine.mq5 into each terminal."
    } else {
        Write-Host "  V75MacroEngine: DENIED - left untouched in every terminal." -ForegroundColor Red
    }
    if ((-not (Test-DeployGated 'MitemshubAI.mq5')) -and (-not $SetOnly)) {
        Write-Host "  Would compile MitemshubAI.mq5 in each terminal."
    } else {
        Write-Host "  MitemshubAI: DENIED - left untouched in every terminal." -ForegroundColor Red
    }
    if ($deployFailures.Count -gt 0) {
        Write-Host "Gate failures:" -ForegroundColor Red
        $deployFailures | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        exit 1
    }
    exit 0
}

# Repo-relative paths — the prune pass compares terminal files against this list.
$repoFiles = Get-ChildItem -Path $ProjectDir -Recurse -File | ForEach-Object {
    $_.FullName.Substring($ProjectDir.Length + 1)
}

foreach ($mql5Dir in $mql5Dirs) {
    $setsDir    = Join-Path $mql5Dir "Profiles\Sets"
    $setsMitem  = Join-Path $mql5Dir "Profiles\Sets\MITEMSHUB_AI"
    $expertsDir = Join-Path $mql5Dir "Experts"
    $mitemDir   = Join-Path $mql5Dir "Experts\MITEMSHUB_AI"
    $presetsDir = Join-Path $mql5Dir "Presets"
    $tag        = Split-Path (Split-Path $mql5Dir) -Leaf

    foreach ($dir in @($setsDir, $setsMitem, $expertsDir, $mitemDir, $presetsDir)) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    # Mirror the FULL EA source tree (mq5 + mqh includes + subfolders + .set)
    # into Experts\MITEMSHUB_AI — compiling root-only *.mq5 against stale/missing
    # includes produced the v26.13 TickFadeConfirm undeclared-identifier build
    # failure, and flat duplicates in Experts\ root caused the "MetaEditor
    # still shows v21.1" stale-build trap. The tree is the single deployed copy.
    # Files denied by the deploy gate are skipped entirely: the terminal's
    # existing source and binary are never overwritten with WIP.
    Get-ChildItem -Path $ProjectDir -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($ProjectDir.Length + 1)
        if (Test-DeployGated $rel) { return }
        # A compiled binary is the artifact of its source. When the source is
        # deploy-denied, its binary is equally WIP: mirroring it would overwrite
        # the deployed certified binary (Copy-Item preserves the source's old
        # mtime), which prune 2b would then delete as stale — exactly the
        # restore-then-delete loop hit on 2026-09-14 with a zombie v27 .ex5
        # sitting in the worktree. Skip binaries of gated sources.
        if ($_.Extension -eq ".ex5") {
            $srcRel = $rel -replace "\.ex5$", ".mq5"
            if (Test-DeployGated $srcRel) { return }
        }
        $dest = Join-Path $mitemDir $rel
        $destParent = Split-Path $dest -Parent
        if (-not (Test-Path $destParent)) {
            New-Item -ItemType Directory -Path $destParent -Force | Out-Null
        }
        Copy-Item $_.FullName $dest -Force
        $synced++
    }

    if (-not $Mq5Only) {
        Get-ChildItem -Path $ProjectDir -Filter "*.set" -File | ForEach-Object {
            Copy-Item $_.FullName $setsDir -Force
            Copy-Item $_.FullName $setsMitem -Force
            Copy-Item $_.FullName $presetsDir -Force
            $synced++
        }
    }

    # --------------------------------------------------------
    # Compile pass — the CLI build must happen here, inside the
    # terminal tree, because MetaEditor only emits a fresh .ex5
    # when the source it compiles lives under a terminal MQL5
    # folder. Compiling the repo copy produced the "0 errors but
    # no binary" trap. After the mirror above, the deployed tree
    # is byte-identical to the repo, so compiling it is the same
    # as compiling the repo.
    # --------------------------------------------------------
    if (Test-DeployGated 'MitemshubAI.mq5') {
        Write-Host "MitemshubAI NOT compiled [$tag] - deploy gate denied (deployed build left untouched)." -ForegroundColor Red
    } elseif (-not $SetOnly) {
        $metaEditor = "C:\Program Files\MetaTrader 5 Terminal\metaeditor64.exe"
        if (Test-Path $metaEditor) {
            $compileTarget = Join-Path $mitemDir "MitemshubAI.mq5"
            $compileLog = Join-Path $env:TEMP "mitemshub_compile_$pid.log"
            $compileArgs = "/compile:`"$compileTarget`" /log:`"$compileLog`""
            $proc = Start-Process -FilePath $metaEditor -ArgumentList $compileArgs -Wait -PassThru
            # metaeditor64.exe returns 1 even when the log says
            # "Result: 0 errors" — the exit code is not a reliable
            # failure signal. Trust the log and the resulting binary:
            # a fresh .ex5 (or a 0-error log) means success; the build
            # gate below still catches any missing/stale binary.
            $compileOk = $false
            if (Test-Path $compileLog) {
                $logTail = Get-Content $compileLog -Tail 3 | Out-String
                if ($logTail -match "Result: 0 errors") { $compileOk = $true }
            } elseif ($proc.ExitCode -eq 0) { $compileOk = $true }
            if (-not $compileOk) {
                $deployFailures += "[$tag] COMPILE FAILED: metaeditor64.exe exited $($proc.ExitCode) for MitemshubAI.mq5"
                if (Test-Path $compileLog) {
                    Get-Content $compileLog | Select-Object -Last 5 | ForEach-Object {
                        $deployFailures += "  log: $_"
                    }
                }
            }
        } else {
            $deployFailures += "[$tag] MetaEditor not found at $metaEditor - cannot auto-compile"
        }
    }

    # --------------------------------------------------------
    # Prune pass — remove files the repo no longer has, so the
    # terminals can never resurrect stale copies by themselves.
    # --------------------------------------------------------

    # 1) Orphaned sources/presets inside the mirrored tree (deleted from repo).
    Get-ChildItem -Path $mitemDir -Recurse -File |
        Where-Object { $_.Extension -in ".mqh", ".mq5", ".set" } |
        Where-Object { $repoFiles -notcontains $_.FullName.Substring($mitemDir.Length + 1) } |
        Where-Object { -not (Test-DeployGated $_.FullName.Substring($mitemDir.Length + 1)) } |
        ForEach-Object {
            Remove-Item $_.FullName -Force
            $pruned++
        }

    # 2) Orphaned compiled binaries: a .ex5 whose .mq5 no longer exists in the
    #    repo tree can never be rebuilt from source — it is a zombie build.
    Get-ChildItem -Path $mitemDir -Recurse -File -Filter "*.ex5" |
        Where-Object {
            $srcRel = $_.FullName.Substring($mitemDir.Length + 1) -replace "\.ex5$", ".mq5"
            ($repoFiles -notcontains $srcRel) -and (-not (Test-DeployGated $srcRel))
        } |
        ForEach-Object {
            Remove-Item $_.FullName -Force
            $pruned++
        }

    # 2b) Stale compiled binaries: a .ex5 older than its .mq5 can never be the
    #     current build — the terminal would silently keep running the old
    #     code (the "MetaEditor still shows v21.1" trap class). Delete the
    #     stale binary so it cannot accumulate or be reattached; the build
    #     gate below then reports the live EA as NOT BUILT until recompiled.
    #     A deploy-gated EA's binary is NEVER stale-pruned: when the source is
    #     denied, the deployed pair (source AND binary) is intentionally frozen.
    #     NOTE: the gate MUST run in a Where-Object filter. Inside
    #     ForEach-Object, `return` only skips one script-block invocation — it
    #     does not stop the pipeline — which on 2026-09-14 deleted the gated
    #     arms' binaries and left the running EAs unable to survive a restart.
    Get-ChildItem -Path $mitemDir -Recurse -File -Filter "*.ex5" |
        Where-Object { -not (Test-DeployGated $_.FullName.Substring($mitemDir.Length + 1)) } |
        Where-Object {
            $src = [IO.Path]::ChangeExtension($_.FullName, ".mq5")
            (Test-Path $src) -and ((Get-Item $_.FullName).LastWriteTime -lt (Get-Item $src).LastWriteTime)
        } |
        ForEach-Object {
            Remove-Item $_.FullName -Force
            $pruned++
        }

    # 3) Flat Experts\ root leftovers: the script no longer deploys there, so
    #    any MitemshubAI* binary/preset sitting in the root is stale by design
    #    (the "MetaEditor still shows v21.1" trap). Other EAs are untouched.
    Get-ChildItem -Path $expertsDir -File -Filter "MitemshubAI*" |
        Where-Object { $_.Extension -in ".ex5", ".mq5", ".set" } |
        ForEach-Object {
            Remove-Item $_.FullName -Force
            $pruned++
        }

    # --------------------------------------------------------
    # V75MacroEngine deploy/compile/gate — same pattern as the live EA
    # above: the repo root copy is the single source of truth, the
    # compile runs inside the terminal tree (the "0 errors but no
    # binary" trap applies to this EA identically), and the build gate
    # below catches missing or stale binaries so the terminal can never
    # silently run an old build.
    # --------------------------------------------------------
    $repoV75 = Join-Path $RepoRoot "V75MacroEngine.mq5"
    if ($gatedSkip.ContainsKey('v75macroengine.mq5') -and (Test-Path $repoV75)) {
        Write-Host "V75MacroEngine NOT deployed [$tag] - deploy gate denied (worktree does not match manifest pin; deployed build left untouched)." -ForegroundColor Red
    } elseif (Test-Path $repoV75) {
        $v75Dir = Join-Path $mql5Dir "Experts\V75MacroEngine"
        if (-not (Test-Path $v75Dir)) {
            New-Item -ItemType Directory -Path $v75Dir -Force | Out-Null
        }
        Copy-Item $repoV75 $v75Dir -Force

        if (-not $SetOnly) {
            $metaEditorV75 = "C:\Program Files\MetaTrader 5 Terminal\metaeditor64.exe"
            if (Test-Path $metaEditorV75) {
                $v75Target = Join-Path $v75Dir "V75MacroEngine.mq5"
                $v75Log = Join-Path $env:TEMP "v75macro_compile_$pid.log"
                $procV75 = Start-Process -FilePath $metaEditorV75 -ArgumentList "/compile:`"$v75Target`" /log:`"$v75Log`"" -Wait -PassThru
                # Exit code is not a reliable failure signal (see note above);
                # trust the log like the MitemshubAI gate does.
                if ((Test-Path $v75Log) -and ((Get-Content $v75Log -Tail 3 | Out-String) -match "Result: 0 errors")) {
                    Write-Host "V75MacroEngine compiled OK [$tag]." -ForegroundColor DarkGray
                } else {
                    $deployFailures += "[$tag] V75MacroEngine compile FAILED (exit $($procV75.ExitCode))"
                    if (Test-Path $v75Log) {
                        Get-Content $v75Log | Select-Object -Last 5 | ForEach-Object {
                            $deployFailures += "  log: $_"
                        }
                    }
                }
            } else {
                $deployFailures += "[$tag] MetaEditor not found - cannot compile V75MacroEngine"
            }
        }

        # Build gate for V75MacroEngine (mirrors the live-EA gate above).
        $v75Mq5 = Join-Path $v75Dir "V75MacroEngine.mq5"
        $v75Ex5 = Join-Path $v75Dir "V75MacroEngine.ex5"
        if (-not (Test-Path $v75Ex5)) {
            $deployFailures += "[$tag] V75MacroEngine NOT BUILT: V75MacroEngine.ex5 is missing"
        } elseif ((Get-Item $v75Ex5).LastWriteTime -lt (Get-Item $v75Mq5).LastWriteTime) {
            $deployFailures += "[$tag] V75MacroEngine STALE: .ex5 ($((Get-Item $v75Ex5).LastWriteTime.ToString('yyyy-MM-dd HH:mm'))) is older than its .mq5 - recompile"
        }
    }

    $termCount++

    # --------------------------------------------------------
    # Build gate — the live EA must have a fresh .ex5 after sync.
    # A missing or stale binary here means the terminal would run
    # an old build (the "MetaEditor still shows v21.1" trap class).
    # Only the LIVE EA (root MitemshubAI.mq5 + its includes) is
    # gated; Tests\*.mq5 scripts are compiled on demand.
    # --------------------------------------------------------
    $liveMq5 = Join-Path $mitemDir "MitemshubAI.mq5"
    $liveEx5 = Join-Path $mitemDir "MitemshubAI.ex5"
    if (-not (Test-Path $liveMq5)) {
        $deployFailures += "[$tag] live source missing: Experts\MITEMSHUB_AI\MitemshubAI.mq5"
    } elseif (-not (Test-Path $liveEx5)) {
        if (Test-DeployGated 'MitemshubAI.mq5') {
            $deployFailures += "[$tag] LIVE EA NOT BUILT: MitemshubAI.ex5 is missing while its deploy is gated - the terminal cannot (re)load the EA. Restore: compile the deployed source in place, or re-pin the manifest and sync."
        } else {
            $deployFailures += "[$tag] LIVE EA NOT BUILT: MitemshubAI.ex5 is missing"
        }
    } elseif (Test-DeployGated 'MitemshubAI.mq5') {
        # Deploy-gated with a binary present: the deployed source/binary pair
        # is intentionally untouched, so its staleness is not a sync failure.
    } else {
        # Stale check scoped to the live build's actual inputs (MitemshubAI.mq5
        # + its includes). Other top-level .mq5 variants (e.g. MitemshubAI_v28.mq5
        # research EAs) do not build this binary and must not trip it.
        $newestSrc = @((Get-Item $liveMq5)) + @(Get-ChildItem -Path $mitemDir -Recurse -File -Include *.mqh |
            Where-Object { $_.FullName -notmatch '\\Tests\\' }) |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($null -ne $newestSrc -and (Get-Item $liveEx5).LastWriteTime -lt $newestSrc.LastWriteTime) {
            $deployFailures += "[$tag] LIVE EA STALE: MitemshubAI.ex5 ($((Get-Item $liveEx5).LastWriteTime.ToString('yyyy-MM-dd HH:mm'))) is older than $($newestSrc.Name) ($($newestSrc.LastWriteTime.ToString('yyyy-MM-dd HH:mm')))"
        }
    }
}

Write-Host "Synced $synced file(s) to $termCount MT5 instance(s)." -ForegroundColor Yellow
Write-Host "Pruned $pruned orphaned file(s) not present in the repo." -ForegroundColor Yellow
if ($gatedSkip.Count -gt 0) {
    Write-Host "Deploy gate: $($gatedSkip.Count) pinned EA(s) DENIED and left untouched in every terminal: $(($gatedSkip.Keys | Sort-Object) -join ', ')" -ForegroundColor Red
}

if ($deployFailures.Count -gt 0) {
    Write-Host ""
    Write-Host "DEPLOY FAILED - $($deployFailures.Count) failure(s):" -ForegroundColor Red
    $deployFailures | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    exit 1
}

if (Test-DeployGated 'MitemshubAI.mq5') {
    Write-Host "Build gate passed for all deployed EAs (MitemshubAI deploy-gated: its deployed binary is untouched, not gated)." -ForegroundColor Green
} else {
    Write-Host "Build gate passed: MitemshubAI.ex5 is present and up-to-date in all instances." -ForegroundColor Green
}
Write-Host "Restart MT5 or recompile the EA for changes to take effect." -ForegroundColor DarkYellow
