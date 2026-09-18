"""§14 portfolio deployment: add M1t/M1s/M1m charts beside the live M1 arm.

The live M1 chart is NOT modified (it runs pinned and byte-verified). The
three new charts are clones of chart01 with a unique id, the arm's tag and
mode in the expert inputs — every other byte identical to the certified
chart. Each clone is identity-checked against its own repo preset BEFORE
the terminal starts. Terminal is stopped flat during the deploy.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import v28_sweep_runner as R                      # noqa: E402
import morning_status as ms                       # noqa: E402

DF = Path(R.data_folder_for_terminal())
CHARTS = DF / "MQL5" / "Profiles" / "Charts" / "Default"
SRC = CHARTS / "chart01.chr"

ARMS = [  # (tag, mode, chart file) — M1 stays on chart01, untouched
    ("M1t", 2, "chart02.chr"),
    ("M1s", 5, "chart03.chr"),
    ("M1m", 6, "chart04.chr"),
]

print("=== §14 portfolio deploy ===")

# --- gate 1: every paper book flat ------------------------------------------
arms = R.inventory_arms(str(DF))
flat, bad = R.verify_all_flat(arms)
gpath = DF / "MQL5" / "Files" / "MIDASTOUCH_paper_XAUUSDmicro_M1.csv"
gold = R.ledger_flatness(str(gpath)) if gpath.exists() else {"flat": True}
print(f"flat-check: {len(arms)} inventoried arm(s), gold M1 flat={gold['flat']}")
if not (flat and gold["flat"]):
    print("ABORT: not flat — refusing to stop the terminal")
    sys.exit(4)

# --- gate 2: pause the watchdog ---------------------------------------------
marker = REPO / "scripts" / ".midas_watchdog_paused"
was_paused = marker.exists()
if not was_paused:
    marker.write_text("portfolio deploy\n")
    print("watchdog paused")
else:
    print("watchdog already paused (marker pre-existing; will NOT lift it)")

# --- stop the terminal --------------------------------------------------------
pids = R.terminal_pids_exact()
if pids:
    print(f"stopping terminal (pids {pids})")
    if not R.stop_terminal(pids):
        print("ABORT: stop failed")
        sys.exit(5)

# --- clone the charts ----------------------------------------------------------
src_txt = SRC.read_text(encoding="utf-16")
src_id = int(re.search(r"^id=(\d+)", src_txt, re.M).group(1))

try:
    for i, (tag, mode, fname) in enumerate(ARMS, 1):
        t = src_txt
        t = re.sub(r"^id=\d+", f"id={src_id + i}", t, count=1, flags=re.M)
        t = re.sub(r"^InpArmTag=\S*$", f"InpArmTag={tag}", t, count=1, flags=re.M)
        t = re.sub(r"^InpMode=\d+$", f"InpMode={mode}", t, count=1, flags=re.M)
        out = CHARTS / fname
        if out.exists():
            bak = out.with_suffix(".chr.pre_deploy")
            os.replace(out, bak)
            print(f"  {fname}: pre-existing, backed up -> {bak.name}")
        out.write_bytes(t.encode("utf-16"))

        # --- gate 3: identity vs the arm's own preset, BEFORE relaunch ---
        from midas_watchdog import preset_for_tag
        ident = ms.preset_identity(t, preset_for_tag(tag))
        if ident["verdict"] != "OK":
            print(f"ABORT: {fname} ({tag}) identity {ident['verdict']}: "
                  f"{ident['drift']} {ident['missing']} {ident['extra']}")
            sys.exit(6)
        print(f"  {fname}: {tag} mode={mode} -> preset identity OK "
              f"({ident['n_keys']} inputs byte-identical)")
finally:
    if not was_paused:
        pass  # pause lifted manually after verification, per §12 discipline

print("charts deployed; relaunching terminal")
R.relaunch_terminal()
print("deploy complete — verify the four boot banners, then resume the watchdog")
