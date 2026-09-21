"""Detach a trading EA from an MT5 chart profile (.chr) — safely.

WHY. chart04.chr in the live terminal carries a second MitemshubAI attached to
Volatility 75 with InpLiveExecution=true and the SAME magic as the arm-A paper
chart. Two same-symbol EAs in one terminal corrupt each other (all ledger/
state/telemetry files are symbol-tagged), and a live-execution V75 chart with
unvalidated inputs is a landmine. Decision (2026-09-04): DETACH — arm B
(VOL75_TP24) belongs in its own second terminal, never on this chart.

The same need recurred on 2026-09-19 when the MIDASTOUCH gold program was
parked, so the matcher accepts an explicit expert name instead of hard-coding
MitemshubAI. `--all` matches every program EA this repo deploys.

SAFETY RULES (the tool enforces all of them):
  1. REFUSES to modify any file while terminal64.exe is running — MT5 rewrites
     profiles on exit and would clobber the edit. Close MT5 first.
  2. Writes a timestamped .bak next to the file before touching it.
  3. Only strips the <expert>...</expert> block of a matched EA; the
     chart itself (symbol, layout, indicators) is untouched.
  4. Verifies the result re-parses as UTF-16 key=value with no expert block.

Usage:
  python scripts/detach_chart_ea.py --scan                            # list attached charts
  python scripts/detach_chart_ea.py --chart "<path to .chr>"          # do it
  python scripts/detach_chart_ea.py --chart "<path>" --dry-run        # preview
  python scripts/detach_chart_ea.py --chart "<path>" --match MidastouchAI
  python scripts/detach_chart_ea.py --chart "<path>" --all

KNOWN EAs (--all expands to these expert names):
  MitemshubAI     synthetic-indices multi-strategy engine
  MidastouchAI    MIDASTOUCH gold engine (paper arms + LV live)
  V75MacroEngine  V75 macro-directional arm C
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
from datetime import datetime

TERM_ROOT = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")

KNOWN_EAS = ("MitemshubAI", "MidastouchAI", "V75MacroEngine")
DEFAULT_MATCHES = ("MitemshubAI",)


def terminal_running() -> bool:
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
        return "terminal64.exe" in out
    except OSError:
        return False


def read_chr(path) -> str:
    return open(path, encoding="utf-16", errors="replace").read()


def has_expert(txt: str, names: tuple[str, ...] = DEFAULT_MATCHES) -> bool:
    """True when any of `names` is attached (by path or by chart banner)."""
    for name in names:
        if re.search(rf"path=Experts\\\\.*?{re.escape(name)}\.ex5", txt, re.I):
            return True
        if name in txt:
            return True
    return False


def matched_experts(txt: str, names: tuple[str, ...] = DEFAULT_MATCHES) -> list[str]:
    """Which of `names` appear in this chart profile (for reporting)."""
    return [n for n in names if n in txt]


def strip_expert(txt: str) -> tuple[str, bool]:
    """Remove the <expert>...</expert> block; also any stray top-level
    'descr==== ...' banner marker is left alone (harmless)."""
    new = re.sub(r"<expert>.*?</expert>\r?\n?", "", txt, flags=re.S | re.I)
    return new, new != txt


def list_attached(names: tuple[str, ...] = DEFAULT_MATCHES):
    found = []
    for chr_f in glob.glob(os.path.join(TERM_ROOT, "*", "MQL5", "Profiles", "Charts", "*", "*.chr")):
        txt = read_chr(chr_f)
        if has_expert(txt, names):
            sym = next((l[7:] for l in txt.splitlines() if l.strip().startswith("symbol=")), "?")
            found.append((chr_f, sym))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chart", help="path to the .chr file")
    ap.add_argument("--scan", action="store_true", help="list charts with a known EA attached")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--match", action="append", default=None,
                    help=f"expert name to match (repeatable); default {DEFAULT_MATCHES[0]}")
    ap.add_argument("--all", action="store_true",
                    help=f"match every known EA: {', '.join(KNOWN_EAS)}")
    args = ap.parse_args()

    if args.all:
        names = KNOWN_EAS
    elif args.match:
        names = tuple(args.match)
    else:
        names = DEFAULT_MATCHES

    if args.scan:
        rows = list_attached(KNOWN_EAS)
        if not rows:
            print("no charts with a known EA attached")
        for p, s in rows:
            txt = read_chr(p)
            print(f"  {s:26s} {','.join(matched_experts(txt, KNOWN_EAS)):<28} {p}")
        return

    if not args.chart:
        ap.error("--chart or --scan required")
    path = os.path.abspath(args.chart)
    if not os.path.exists(path):
        raise SystemExit(f"not found: {path}")
    txt = read_chr(path)
    if not has_expert(txt, names):
        print(f"none of {names} attached — nothing to do")
        return
    new, changed = strip_expert(txt)
    if not changed:
        print("expert block already absent (banner-only match?) — nothing to do")
        return
    sym = next((l[7:] for l in txt.splitlines() if l.strip().startswith("symbol=")), "?")
    if args.dry_run:
        print(f"DRY RUN: would detach {','.join(matched_experts(txt, names))} from {sym} ({path})")
        return

    if terminal_running():
        raise SystemExit("REFUSING: terminal64.exe is running — MT5 rewrites chart profiles on "
                         "exit and would clobber this edit. Close ALL MT5 terminals first, "
                         "then re-run. (This refusal is the tool's core safety feature.)")
    bak = f"{path}.bak_{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copy2(path, bak)
    open(path, "w", encoding="utf-16").write(new)
    # verify re-parse
    chk = read_chr(path)
    ok = ("<expert>" not in chk) and ("symbol=" in chk)
    print(f"{'DETACHED' if ok else 'FAILED VERIFY'}: {sym} — backup at {bak}")
    if not ok:
        print("restoring backup ...")
        shutil.copy2(bak, path)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
