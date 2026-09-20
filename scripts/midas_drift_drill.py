"""Tabletop drill: preset-drift incident on a throwaway fixture.

Everything external is redirected: the "terminal data folder" is a sandbox
copy, the watchdog's stop/relaunch are stubs, its state/records go to the
sandbox, and [3b] discovery points at the sandbox via TERM_ROOT. The real
terminal, chart, ledger, and watchdog state are never touched — the driver
asserts the real chart is byte-unchanged at the end.

Phases:
  A  chart inputs tampered, but the RUNNING EA still booted pinned
     (banner clean) -> [3b] screams, watchdog says NONE. Layer asymmetry.
  B  the EA reboots onto the tampered chart (journal banner now drifted)
     -> watchdog DRIFT leg: stop -> re-splice -> relaunch (stubs; the
     splice itself is the real certified code, applied to the fixture).
  C  fresh pinned boot + fresh heartbeat -> RECOVERED, counter reset,
     [3b] back to OK. The full loop, end to end.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

SB = REPO / "artifacts" / "_tt_sandbox"
shutil.rmtree(SB, ignore_errors=True)
for d in ("MQL5/Logs", "MQL5/Files", "MQL5/Profiles/Charts/Default"):
    (SB / d).mkdir(parents=True)

REAL_DF = Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / \
    "49E0383CD680D7AAEC56888AFA08F49E"
CHR_REAL = next(f for f in (REAL_DF / "MQL5/Profiles/Charts").glob("*/*.chr")
                if "MidastouchAI" in f.read_text(encoding="utf-16", errors="replace"))
REAL_CHR_BYTES = CHR_REAL.read_bytes()          # containment proof, end of drill

BANNER = ("[MIDAS1.10]MIDASTOUCH started | mode={mode} | symbol=XAUUSD (GOLD-OK) | "
          "macro=H4+H1 EMA20 | trigger=M15 BB(20,2.0)/RSI(14) | SL=2.0xATR(H1) TP=2.0R "
          "timeout=720min | session={sess:02d}-20 UTC | spreadcap=1.5%stop | risk=1.00% | "
          "execution=PAPER | exec-model=PERTICK | NEWS-FILTER=OFF (calendar pending)")


def seed_chart(mode: int, sess: int) -> None:
    t = CHR_REAL.read_text(encoding="utf-16", errors="replace")
    t = re.sub(r"^InpMode=\d+", f"InpMode={mode}", t, flags=re.M)
    t = re.sub(r"^InpSessionStartHour=\d+", f"InpSessionStartHour={sess}", t, flags=re.M)
    (SB / "MQL5/Profiles/Charts/Default/chart01.chr").write_bytes(t.encode("utf-16"))


def seed_journal(mode: int, sess: int) -> None:
    line = f"L\t0\t10:00:00.000\tMidastouchAI (XAUUSD,M15)\t{BANNER.format(mode=mode, sess=sess)}\n"
    (SB / "MQL5/Logs/20260917.log").write_text(line, encoding="utf-16")


def seed_ledger() -> None:
    p = SB / "MQL5/Files/MIDASTOUCH_paper_XAUUSD_M1.csv"
    p.write_text("ERA,MIDAS1.10,1789651864,pertick-fills\nEQ,50.00\nEQ,50.00\n")
    os.utime(p, (time.time(), time.time()))     # fresh heartbeat


import midas_watchdog as wd                     # noqa: E402
import morning_status as ms                     # noqa: E402

# --- sandbox the watchdog's every external effect ----------------------------
wd.data_folder_for_terminal = lambda: str(SB)
wd.STATE_PATH = str(SB / "watchdog_state.json")
wd.LAST_PATH = str(SB / "watchdog_last.json")
STOPS: list[list[int]] = []
LAUNCHES: list[str] = []
wd.terminal_pids_exact = lambda: [424242]                     # fake PID
wd.stop_terminal = lambda pids: (STOPS.append(list(pids)), True)[1]
wd.relaunch_terminal = lambda: LAUNCHES.append("relaunch")
# --- sandbox [3b] discovery ---------------------------------------------------
ms.TERM_ROOT = str(SB.parent)

print(f"TABLETOP DRIFT DRILL — sandbox {SB}")
print("  real terminal: untouched | real watchdog state: untouched | "
      "stop/relaunch: stubbed | splice/parsers/banners: the real code\n")


def wd_leg(label: str) -> dict:
    r = wd.check()
    print(f"[watchdog] {label}")
    print(f"    action={r['action']}")
    if r.get("drift"):
        print("    drift : " + "; ".join(r["drift"]))
    if r.get("problems"):
        print("    probs : " + "; ".join(map(str, r["problems"])))
    print(f"    state : {json.dumps(r['state'])}")
    return r


def ms_leg(label: str) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ms.print_midas_section()
    out = buf.getvalue().strip()
    print(f"[3b] {label}")
    for ln in out.splitlines():
        print("    " + ln)
    return out


print("=" * 74)
seed_chart(mode=2, sess=12)                     # the 09:57 incident signature
seed_journal(mode=0, sess=6)                    # running EA booted pinned
seed_ledger()
print("INJECT: chart inputs flipped to InpMode=2 / InpSessionStartHour=12;")
print("        journal still carries the pinned boot (EA loaded before tamper)\n")
ms_leg("phase A — chart tampered, running EA still pinned")
wd_leg("phase A — banner (last boot) is clean")

print("=" * 74)
print("INJECT: the EA reboots onto the tampered chart — journal now drifted\n")
seed_journal(mode=2, sess=12)
r = wd_leg("phase B — watchdog config-drift leg fires")
assert r["action"] == "DRIFT" and STOPS and LAUNCHES
print(f"    stubs : stop_terminal{STOPS[-1]}, relaunch x{len(LAUNCHES)}")
baks = list(SB.glob("MQL5/Profiles/Charts/Default/*.bak_watchdog_*"))
print(f"    splice: backup kept -> {baks[-1].name if baks else 'NONE'}")

print("=" * 74)
print("INJECT: remediated world — fresh pinned boot, fresh heartbeat\n")
seed_journal(mode=0, sess=6)
seed_ledger()
wd_leg("phase C — recovery poll")
ms_leg("phase C — [3b] after the auto-remediation")

print("=" * 74)
fixed = preset = None
import set_chart_preset as scp
txt = scp.read_chr(SB / "MQL5/Profiles/Charts/Default/chart01.chr")
m = re.search(r"^InpMode=(\d+)", txt, re.M)
fixed = m.group(1)
import morning_status as ms2
preset = ms2.preset_identity(txt)
print(f"FINAL: fixture chart InpMode={fixed}, preset-identity verdict={preset['verdict']}")
assert CHR_REAL.read_bytes() == REAL_CHR_BYTES, "REAL CHART WAS TOUCHED"
print("CONTAINMENT: real chart byte-identical to pre-drill — no real surface touched")
