"""Attach an EA to a new chart in an MT5 terminal profile (.chr writer).

Writes a fresh chartNN.chr into <data folder>/MQL5/Profiles/Charts/<profile>/
with an <expert> block (explicit inputs) so the EA loads on the next launch.

IMPORTANT (learned the hard way 2026-09-14): MT5 **silently skips** a .chr it
does not like — no journal error, no chart. A minimal hand-rolled file (few
header keys, CRLF endings) is ignored even though it re-parses fine in Python.
The only reliable approach is to DERIVE the new chart from an existing
MT5-saved .chr (any chart in the profile) and edit only:
  - id=          (unique: max existing id + 1)
  - period_size= (requested timeframe; symbol/digits/colors stay from template)
  - position_time / scale_fixed_* dropped (stale view state)
  - <object> blocks dropped (template clutter)
  - <expert> block replaced with the target EA + explicit inputs
and write UTF-16-LE **with BOM and LF line endings**, matching MT5's own output.

Safety (mirrors detach_chart_ea.py):
  1. Refuses to write while the TARGET install's terminal64.exe is running
     (MT5 rewrites profiles on exit and would clobber the edit — verified).
     Other terminals may keep running — installs are independent.
  2. Backs up an existing target file before overwrite.
  3. Verifies the written file re-parses with the expected keys and structure.

Usage:
  python scripts/attach_ea_chart.py --scan
  python scripts/attach_ea_chart.py --terminal-hash FB9A56... \
      --symbol "Volatility 75 Index" --period-min 30 \
      --expert-path "Experts\\V75MacroEngine\\V75MacroEngine.ex5" \
      --expert-name V75MacroEngine --inputs inputs.txt [--profile Default]
  (inputs file: one KEY=VALUE per line, written verbatim into <inputs>)
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


def read_utf16(path: str) -> str:
    with open(path, encoding="utf-16", errors="ignore") as fh:
        return fh.read()


def install_path_for(terminal_hash: str) -> str | None:
    origin = os.path.join(TERM_ROOT, terminal_hash, "origin.txt")
    if not os.path.exists(origin):
        return None
    return read_utf16(origin).strip().strip("\ufeff").strip("\x00").strip()


def target_install_running(install_path: str | None) -> bool:
    if not install_path:
        return False
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
          "Select-Object -ExpandProperty ExecutablePath")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True).stdout
    return install_path.lower() in out.lower()


def next_chart_path(profile_dir: str) -> tuple[str, int]:
    used = {int(m.group(1)) for f in glob.glob(os.path.join(profile_dir, "chart*.chr"))
            if (m := re.match(r"chart(\d+)\.chr$", os.path.basename(f)))}
    n = 1
    while n in used:
        n += 1
    return os.path.join(profile_dir, f"chart{n:02d}.chr"), n


def unique_chart_id(profile_dir: str) -> int:
    ids = []
    for f in glob.glob(os.path.join(profile_dir, "chart*.chr")):
        m = re.search(r"^id=(\d+)", read_utf16(f), re.M)
        if m:
            ids.append(int(m.group(1)))
    return (max(ids) + 1) if ids else 1275669099


def build_chart_from_template(template_path: str, symbol: str, period_min: int,
                              expert_name: str, expert_path: str,
                              inputs_lines: list[str]) -> str:
    """Derive a new .chr from an MT5-saved template, editing only what must change."""
    txt = read_utf16(template_path).replace("\ufeff", "")
    lines = txt.splitlines()

    out: list[str] = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s == "<object>":                      # drop saved-object clutter
            while i < len(lines) and lines[i].strip() != "</object>":
                i += 1
            i += 1
            continue
        if s.startswith("id="):
            out.append(f"id={unique_chart_id(os.path.dirname(template_path))}")
        elif s.startswith("period_size="):
            out.append(f"period_size={period_min}")
        elif (s.startswith("position_time=") or s.startswith("scale_fixed_min=")
              or s.startswith("scale_fixed_max=")):
            pass                                  # stale view state
        elif s.startswith("objects="):
            out.append("objects=0")
        else:
            out.append(lines[i])
        i += 1

    text = "\n".join(out) + "\n"

    expert_block = "\n".join(
        ["<expert>",
         f"name={expert_name}",
         f"path={expert_path}",
         "expertmode=1",
         "<inputs>",
         *inputs_lines,
         "</inputs>",
         "</expert>"]) + "\n"
    text = re.sub(r"<expert>.*?</expert>\n", lambda m: expert_block, text, flags=re.S)

    return "\ufeff" + text                        # UTF-16-LE + BOM, LF endings


def scan() -> None:
    for f in sorted(glob.glob(os.path.join(TERM_ROOT, "*", "MQL5", "Profiles",
                                           "Charts", "*", "*.chr"))):
        txt = read_utf16(f)
        m = re.search(r"^path=(Experts\\.+?\.ex5)", txt, re.M)
        sym = next((l[7:] for l in txt.splitlines() if l.startswith("symbol=")), "?")
        if m:
            print(f"  {sym:26s} {m.group(1):50s} {f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--terminal-hash", required=False)
    ap.add_argument("--symbol", default="Volatility 75 Index")
    ap.add_argument("--period-min", type=int, default=30)
    ap.add_argument("--expert-path", required=False)
    ap.add_argument("--expert-name", required=False)
    ap.add_argument("--inputs", help="KEY=VALUE lines file (verbatim into <inputs>)")
    ap.add_argument("--profile", default="Default")
    args = ap.parse_args()

    if args.scan:
        scan()
        return

    assert args.terminal_hash and args.expert_path and args.expert_name and args.inputs
    profile_dir = os.path.join(TERM_ROOT, args.terminal_hash, "MQL5", "Profiles",
                               "Charts", args.profile)
    assert os.path.isdir(profile_dir), f"profile dir missing: {profile_dir}"

    templates = sorted(glob.glob(os.path.join(profile_dir, "chart*.chr")))
    assert templates, f"no MT5-saved .chr in {profile_dir} to use as template"
    template = templates[0]
    print(f"template (MT5-canonical): {os.path.basename(template)}")

    install = install_path_for(args.terminal_hash)
    if target_install_running(install):
        raise SystemExit(f"REFUSING: terminal64.exe of install {install} is running. "
                         "Close it first (MT5 rewrites profiles on exit).")
    print(f"target install not running: {install}")

    inputs_lines = [l.strip() for l in
                    open(args.inputs, encoding="utf-8").read().splitlines() if l.strip()]
    target, n = next_chart_path(profile_dir)
    if os.path.exists(target):
        bak = f"{target}.bak_{datetime.now():%Y%m%d_%H%M%S}"
        shutil.copy2(target, bak)
        print(f"backed up existing {target} -> {bak}")

    content = build_chart_from_template(template, args.symbol, args.period_min,
                                        args.expert_name, args.expert_path, inputs_lines)
    with open(target, "wb") as fh:
        fh.write(content.encode("utf-16-le"))

    chk = read_utf16(target)
    ok = ("<expert>" in chk and f"path={args.expert_path}" in chk
          and f"symbol={args.symbol}" in chk and args.expert_name in chk
          and "</chart>" in chk and "<window>" in chk
          and b"\r\n" not in open(target, "rb").read())
    print(f"{'WROTE' if ok else 'FAILED VERIFY'}: chart{n:02d} "
          f"({args.symbol} M{args.period_min}, {args.expert_name}) -> {target}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
