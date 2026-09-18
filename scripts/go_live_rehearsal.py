"""Go-live rehearsal — read-only dry run of GO_LIVE_CHECKLIST.md's verification steps.

    python scripts/go_live_rehearsal.py

Proves, against the LIVE terminals and repo, that every banner string and file
check on the checklist is findable and correct — without touching any EA, any
switch, or any order path. Reads only:

  * process list (terminal A running, matched by full exe path),
  * terminal journals (account authorization; arm A's latest init banner),
  * the repo LIVE preset + the deployed Common\\Presets copy (byte identity,
    live values, fleet guard),
  * scripts/verify_go_live_artifacts.py (build/preset/manifest pins).

Banner rehearsal logic: arm A runs the SAME EA build on the SAME terminal the
live attach will use, in paper mode. Every marker the checklist expects on
go-live day also appears in a paper banner — except `PAPER MODE:`, which must
be ABSENT live and is PRESENT on paper. Finding it in the paper banner proves
the discriminator is a real detector (not a string that never matches).

Writes artifacts/v75_replay/go_live_rehearsal_YYYYMMDD.json and exits 0 iff
every check passes. Never modifies terminal or repo state.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

APPDATA = os.environ.get("APPDATA", "")
FB9A = os.path.join(APPDATA, "MetaQuotes", "Terminal", "FB9A56D617EDDDFE29EE54EBEFFE96C1")
TERMINA_A_EXE = r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe"
ACCOUNT = "140778269"
REPO_LIVE_SET = os.path.join(REPO, "mql5", "MITEMSHUB_AI", "MitemshubAI_VOL75_LIVE.set")
COMMON_PRESETS = os.path.join(APPDATA, "MetaQuotes", "Terminal", "Common", "MQL5", "Presets")
OUT_DIR = os.path.join(REPO, "artifacts", "v75_replay")

LIVE_VALUES = {"InpLiveExecution": "true", "InpMagic": "7788075",
               "InpTpMult": "1.8", "InpPaperEquity": "50.0"}
FLEET_NEEDS = ("7788075", "7788100")

# Banner markers the checklist step 4 requires (regex, all must be found after
# the last Mitemshub init banner on terminal A). Marker text verified against
# the v26.40 source and the live 2026-09-15/16 journals during the first
# rehearsal — the checklist's own prose had drifted (FIT ROUTER wording,
# a phantom "State ->" line).
BANNER_MARKERS = [
    (r"MITEMSHUB AI v(\d+\.\d+) started", "build/version line"),
    (r"PAPER ledger era stamp: (\d+\.\d+)", "era stamp"),
    (r"FIT ROUTER:", "fit router / balance read"),
    (r"min-lot stop-risk \$[\d.]+.*TOLERATED", "min-lot sizing TOLERATED"),
    (r"RiskCap=20%", "risk cap line"),
    (r"WARNING: risk cap > 10%", "tiny-account warning"),
    (r"\[SELFTEST\].*OK", "engine selftest"),
    (r"GARCH ready:", "GARCH ready"),
    (r"Telemetry ->", "telemetry path"),
    (r"Cold-start catch-up", "cold-start replay complete"),
]
DISCRIMINATOR = "PAPER MODE:"


def _read_maybe_utf16(path: str) -> str:
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16-le", errors="ignore")
    return raw.decode("cp1252", errors="ignore")


def check_terminal_running() -> dict:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" "
             "| Select-Object -ExpandProperty ExecutablePath"],
            capture_output=True, text=True, timeout=30).stdout
    except Exception as e:                                   # pragma: no cover
        return {"status": "FAIL", "evidence": [f"process query failed: {e}"]}
    paths = [p.strip() for p in out.splitlines() if p.strip()]
    hit = next((p for p in paths if p.lower() == TERMINA_A_EXE.lower()), None)
    return {"status": "PASS" if hit else "FAIL",
            "evidence": [f"terminal64.exe paths: {paths}",
                         f"terminal A (FB9A install): {'FOUND ' + hit if hit else 'NOT RUNNING'}"]}


def check_account_authorized() -> dict:
    """The checklist's account precondition was API-verified 2026-09-14; the
    rehearsal proves the journal still shows THIS account authorized on
    terminal A (read-only corroboration, never a substitute for the API read)."""
    journals = sorted(glob.glob(os.path.join(FB9A, "logs", "*.log")),
                      key=os.path.getmtime, reverse=True)
    hits, scanned = [], 0
    for j in journals[:7]:                     # a week of journals is plenty
        scanned += 1
        for line in _read_maybe_utf16(j).splitlines():
            if ACCOUNT in line and ("authorized" in line or "login" in line.lower()):
                hits.append(line.strip()[:160])
        if hits:
            break
    return {"status": "PASS" if hits else "WARN",
            "evidence": hits[:3] or [f"no journal line naming account {ACCOUNT} "
                                     f"in the {scanned} newest terminal journals — "
                                     f"re-verify via account_info() on the day"]}


def check_repo_preset() -> dict:
    ev, ok = [], True
    if not os.path.exists(REPO_LIVE_SET):
        return {"status": "FAIL", "evidence": [f"missing {REPO_LIVE_SET}"]}
    vals = {}
    for line in open(REPO_LIVE_SET, encoding="utf-8", errors="replace"):
        m = re.match(r"^(Inp\w+)=(.*)$", line.strip())
        if m:
            vals[m.group(1)] = m.group(2)
    for k, want in LIVE_VALUES.items():
        got = vals.get(k)
        good = got == want
        ok &= good
        ev.append(f"{k}: {got!r} (expect {want!r}) {'OK' if good else 'MISMATCH'}")
    csv = vals.get("InpFleetMagicsCSV", "")
    fleet_ok = all(m in csv for m in FLEET_NEEDS)
    ok &= fleet_ok
    ev.append(f"fleet guard contains A/B magics: {fleet_ok} (CSV={csv[-60:]})")
    return {"status": "PASS" if ok else "FAIL", "evidence": ev}


def check_deployed_preset_copy() -> dict:
    dep = os.path.join(COMMON_PRESETS, "MitemshubAI_VOL75_LIVE.set")
    if not os.path.exists(dep):
        return {"status": "FAIL",
                "evidence": [f"deployed copy missing: {dep}"]}
    import hashlib
    h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    same = h(REPO_LIVE_SET) == h(dep)
    return {"status": "PASS" if same else "FAIL",
            "evidence": [f"repo   sha256 {h(REPO_LIVE_SET)[:16]}…",
                         f"common sha256 {h(dep)[:16]}…",
                         "byte-identical" if same else "DIFFER — redeploy before go-live"]}


def check_verify_artifacts() -> dict:
    r = subprocess.run([sys.executable, os.path.join(HERE, "verify_go_live_artifacts.py")],
                       capture_output=True, text=True, timeout=120)
    tail = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()][-4:]
    ok = "GO-LIVE ARTIFACTS: PASS" in r.stdout
    return {"status": "PASS" if ok else "FAIL", "evidence": tail}


def latest_banner() -> tuple[list[str], str] | tuple[None, str]:
    """Arm A's Mitemshub banner evidence on terminal A: the newest journal that
    contains an init banner, from that day's FIRST init to EOF. A late-day
    reload can leave a partial banner (header printed, warmup lines never
    reached before the day ended), so the rehearsal aggregates the day's EA
    activity — the on-the-day operator check still reads the FRESH banner."""
    journals = [p for p in glob.glob(os.path.join(FB9A, "MQL5", "Logs", "*.log"))
                if os.path.splitext(os.path.basename(p))[0].isdigit()]   # date-named journals
    if not journals:
        return None, "no Experts journals under FB9A MQL5\\Logs"
    journals.sort(key=os.path.getmtime, reverse=True)
    for j in journals:
        text = _read_maybe_utf16(j)
        lines = text.splitlines()
        starts = [i for i, l in enumerate(lines) if re.search(r"MITEMSHUB AI v\d+\.\d+ started", l)]
        if starts:
            return lines[starts[0]:], (f"{os.path.basename(j)} line {starts[0] + 1} "
                                       f"({len(starts)} init banner(s) that day)")
    return None, f"no Mitemshub init banner in the newest {len(journals)} journal(s)"


def _repo_app_version() -> str | None:
    """The repo's certified APP_VERSION (injectable in offline tests)."""
    src = open(os.path.join(REPO, "mql5", "MITEMSHUB_AI", "MitemshubAI.mq5"),
               encoding="utf-8", errors="replace").read()
    m = re.search(r'#define APP_VERSION\s+"([\d.]+)"', src)
    return m.group(1) if m else None


def check_banner_strings() -> dict:
    block, where = latest_banner()
    if block is None:
        return {"status": "FAIL", "evidence": [where]}
    ev = [f"banner source: {where}"]
    ok = True
    for pat, name in BANNER_MARKERS:
        m = None
        for line in block:
            m = re.search(pat, line)
            if m:
                break
        found = m is not None
        ok &= found
        detail = m.group(0)[:100] if m else "NOT FOUND"
        ev.append(f"{'OK ' if found else 'MISS'} {name}: {detail}")
    # the checklist precondition is about the NEWEST banner (the build an
    # operator would see on the day), not the day's first reload
    vers = re.findall(r"MITEMSHUB AI v(\d+\.\d+) started", "\n".join(block))
    ver = vers[-1] if vers else None
    if ver is not None:
        repo_ver = _repo_app_version()
        match = ver == repo_ver
        ok &= match
        if match:
            ev.append(f"banner v{ver} vs repo APP_VERSION {repo_ver}: OK match")
        else:
            ev.append(f"banner v{ver} vs repo APP_VERSION {repo_ver}: MISMATCH — "
                      f"terminal A's deployed .ex5 is stale; run the deploy sync "
                      f"(sync-mt5.ps1, manifest-pinned v{repo_ver}) BEFORE go-live, "
                      f"then re-run this rehearsal for a fresh v{repo_ver} banner")
    paper = next((l.strip()[:120] for l in block if DISCRIMINATOR in l), None)
    ev.append(f"discriminator probe: {DISCRIMINATOR!r} line "
              f"{'PRESENT in paper banner -> absence-check is a real detector'
                    if paper else 'NOT FOUND -> the live absence-check would prove nothing'}"
              + (f" | {paper}" if paper else ""))
    ok &= paper is not None
    return {"status": "PASS" if ok else "FAIL", "evidence": ev}


def main() -> None:
    checks = {
        "terminal_a_running": check_terminal_running(),
        "account_authorized_on_terminal_a": check_account_authorized(),
        "repo_live_preset_values": check_repo_preset(),
        "deployed_preset_byte_identical": check_deployed_preset_copy(),
        "verify_go_live_artifacts": check_verify_artifacts(),
        "banner_strings_rehearsal": check_banner_strings(),
    }
    all_pass = all(c["status"] == "PASS" for c in checks.values())
    print("GO-LIVE REHEARSAL (read-only) —", datetime.now().strftime("%Y-%m-%d %H:%M"))
    for name, c in checks.items():
        print(f"\n[{c['status']}] {name}")
        for line in c["evidence"]:
            print(f"    {line}")
    print(f"\nREHEARSAL VERDICT: {'ALL CHECKS PASS' if all_pass else 'FAILURES PRESENT — see above'}")
    print("not rehearsed read-only (operator actions on the day): Algo-Trading "
          "switch ON, EA remove/re-attach with the LIVE preset, first-trade order lines.")
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"go_live_rehearsal_{datetime.now():%Y%m%d}.json")
    with open(out, "w") as f:
        json.dump({"date": datetime.now().strftime("%Y-%m-%d"),
                   "all_pass": all_pass, "checks": checks}, f, indent=1)
    print(f"artifact -> {out}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
