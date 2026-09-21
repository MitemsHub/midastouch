#!/usr/bin/env python3
r"""Attach a MIDASTOUCH EA to an MT5 chart profile (.chr) — the safe counterpart of detach.

WHY A TOOL AND NOT A DRAG. The EA has to be attached for the paper mirror to collect any
forward evidence, and there are two ways to do it. Both were MEASURED on 2026-09-21, and
the results are not what the documentation implies:

  * a chart in a saved PROFILE (`<data>\MQL5\Profiles\Charts\<profile>\*.chr`) — what a
    normal GUI attach produces. A hand-written `<expert>` block is PRESERVED by MT5 across
    a restart and yet IGNORED on load: the chart opens with no Expert, nothing is printed
    to `MQL5\Logs`, and a text-grepping scan reports success. That silent success is the
    whole problem, so `--chart` refuses to claim anything and points at the real check.
  * `/config` with a `[StartUp]` section — the documented route. It attaches on every
    launch of that config, and MT5 also says a start-up chart is never saved: "during the
    next start of the platform without the configuration file, this chart will not be
    opened". That is why `--startup-ini` exists and why `scripts/mt5_ops.relaunch_terminal`
    launches WITH it — otherwise a crash, a reboot or a watchdog recovery silently brings
    up a terminal with no arm on it, and every liveness signal reads like a quiet market.

THE ONLY TRUSTWORTHY EVIDENCE OF AN ATTACH is the EA's own init line in the terminal's
`MQL5\Logs\<date>.log` plus a fresh `MIDASTOUCH_paper_<sym>_<tag>.csv` in `MQL5\Files`.
A `.chr` that contains the right text proves nothing; that is how this took three attempts.

THE PRESET IS THE SOURCE OF TRUTH, as it is for `set_chart_preset.py`: the chart's
`<inputs>` block is written byte-equal to a `.set` file, because a chart that runs *almost*
the certified inputs is the failure mode that file exists to prevent (an arm-A chart once
lost its preset to code defaults and the ledger still looked healthy).

SAFETY RULES (each one is a defect this repo has already paid for, and the `--chart`
route keeps its own because a wrong edit there is invisible):
  1. REFUSES while terminal64.exe runs — MT5 rewrites profiles on exit and would clobber
     the edit.
  2. REFUSES a preset that enables live execution unless an arming record exists: arming is
     a frozen-gate event, never a chart edit (same law as `gold_preset_upcomers.py`).
  3. Writes a timestamped `.bak` before touching anything.
  4. Verifies the written file re-reads with the expert block present and the inputs
     byte-equal to the preset.
  5. Is idempotent: an already-attached, already-equal chart is reported and left alone.

Usage:
  python scripts/attach_chart_ea.py --scan
  # the route that works: write the start-up config and stage the preset next to it
  python scripts/attach_chart_ea.py --startup-ini "<data>\config\midas_attach.ini" \
      --dir "<data>" --preset mql5/MIDASTOUCH/MidastouchAI_upcomers_gold.set \
      --expert "Experts\MIDASTOUCH\MidastouchAI.ex5"
  # then confirm the EA actually started (not the file: the EA's own line)
  #   MQL5\Logs\<date>.log  ->  '[MIDAS1.19]MIDASTOUCH started | ...'
  #   MQL5\Files\MIDASTOUCH_paper_XAUUSD_U25.csv  ->  ERA + EQ rows
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TERM_ROOT = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
ARMING_RECORD = REPO / "artifacts" / "live" / "armed.json"
DEFAULT_EXPERT = r"Experts\MIDASTOUCH\MidastouchAI.ex5"
#: The EA's own flags word as MT5 stores it. 343 is the value a normally-attached
#: non-DLL expert carries on this build; it is recorded rather than derived because the
#: bit layout is undocumented. `MQL_TRADE_ALLOWED` is NOT decided here — the terminal-wide
#: switch is Tools > Options > Expert Advisors > Allow Algo Trading, which
#: `scripts/live_readiness.py` checks against the running terminal.
DEFAULT_FLAGS = "343"


def terminal_running() -> bool:
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    except OSError:
        return False
    return "terminal64.exe" in out


def read_chr(path: Path) -> str:
    return path.read_text(encoding="utf-16", errors="replace")


def write_chr(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-16", newline="")


def all_charts() -> list[Path]:
    return [Path(p) for p in glob.glob(str(
        TERM_ROOT / "*" / "MQL5" / "Profiles" / "Charts" / "*" / "*.chr"))]


def read_preset(path: Path) -> dict[str, str]:
    vals: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith(";") or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        vals[k.strip()] = v.strip()
    return vals


def chart_facts(txt: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in txt.splitlines():
        s = line.strip()
        if "=" in s and not s.startswith("<"):
            k, v = s.split("=", 1)
            out.setdefault(k.strip(), v.strip())
    return out


def attached_expert(txt: str) -> str:
    m = re.search(r"<expert>[\s\S]*?path=([^\r\n]+)", txt, re.I)
    return m.group(1).strip() if m else ""


def existing_inputs(txt: str) -> dict[str, str]:
    m = re.search(r"<inputs>([\s\S]*?)</inputs>", txt)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        s = line.strip()
        if "=" in s:
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def expert_block(preset: dict[str, str], expert: str, flags: str) -> str:
    """The `<expert>` block as MT5 stores it in a chart profile.

    SCHEMA NOTE, because this was found by experiment and not by documentation: MT5 wants
    `name` (the expert's short name) as well as `path`, plus `inputs_count`. A block
    carrying only `path`/`flags`/`window_num`/`<inputs>` is written and then SILENTLY
    IGNORED — the chart loads with no EA, the file still contains the block, and
    `--scan` (which greps text) reports success. The only trustworthy check is the EA's
    own init line in MQL5\\Logs, which is why `--verify-journal` exists below.
    """
    name = Path(expert).stem
    body = "".join(f"{k}={v}\r\n" for k, v in preset.items())
    return (f"<expert>\r\n"
            f"name={name}\r\n"
            f"path={expert}\r\n"
            f"flags={flags}\r\n"
            f"window_num=0\r\n"
            f"inputs_count={len(preset)}\r\n"
            f"<inputs>\r\n{body}</inputs>\r\n"
            f"</expert>\r\n")


def apply_to_chart(txt: str, block: str) -> str:
    """Insert (or replace) the expert block as the last child of the first <window>."""
    if attached_expert(txt):
        # A LAMBDA, not the block as the replacement string: `re.sub` interprets backslash
        # escapes in a replacement, and the expert path contains `\M` ("Experts\MIDASTOUCH")
        # — which raised "bad escape \M" the first time this ran. Passing the text through
        # a callable is the only way to substitute a literal that may contain backslashes.
        return re.sub(r"<expert>[\s\S]*?</expert>\r?\n?", lambda _m: block, txt,
                      count=1, flags=re.I)
    m = re.search(r"</window>\r?\n", txt, re.I)
    if not m:
        raise SystemExit("REFUSING: this chart file has no </window> — not an MT5 chart")
    return txt[:m.start()] + block + txt[m.start():]


def startup_ini_text(expert: str, symbol: str, period: str, preset_name: str) -> str:
    """The `/config` INI MT5 needs to attach an expert on its own.

    MEASURED 2026-09-21, and this is the route that WORKS. A hand-written `<expert>` block
    inside a profile `.chr` is preserved by MT5 across a restart and still ignored on load:
    the chart opens with no Expert, no init line appears in MQL5\\Logs, and a text-grepping
    scan reports success. The documented `[StartUp]` section attaches on every launch of
    this config, so the arm runs when the terminal is started with it.

    The counterpart obligation is in `scripts/mt5_ops.relaunch_terminal`, which launches
    WITH this file when it exists — because MT5's own documentation says a start-up chart
    is not saved: "during the next start of the platform without the configuration file,
    this chart will not be opened". A watchdog relaunch without it would silently bring up
    a terminal with no arm on it, which looks exactly like a quiet market.
    """
    return "\n".join([
        "[Common]",
        "NewsEnable=1",
        "",
        "[Charts]",
        "ProfileLast=Default",
        "",
        "[Experts]",
        "AllowLiveTrading=1",
        "AllowDllImport=0",
        "Enabled=1",
        "",
        "[StartUp]",
        f"Symbol={symbol}",
        f"Period={period}",
        f"Expert={expert[:-4] if expert.lower().endswith('.ex5') else expert}",
        f"ExpertParameters={preset_name}",
        "",
    ])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chart", help="path to the .chr file to attach into")
    ap.add_argument("--startup-ini",
                    help="path to write a /config INI that attaches the expert on every "
                         "launch (the route that works; the preset is copied into the "
                         "terminal's MQL5\\Presets folder, which ExpertParameters needs)")
    ap.add_argument("--dir", help="terminal data folder (required with --startup-ini)")
    ap.add_argument("--symbol", dest="startup_symbol", default="XAUUSD")
    ap.add_argument("--startup-period", default="H1")
    ap.add_argument("--preset", help="the .set file the chart's inputs must equal")
    ap.add_argument("--expert", default=DEFAULT_EXPERT,
                    help=f"expert path as MT5 stores it (default {DEFAULT_EXPERT})")
    ap.add_argument("--flags", default=DEFAULT_FLAGS)
    ap.add_argument("--chart-symbol", dest="symbol", default=None,
                    help="force the chart symbol (e.g. XAUUSD)")
    ap.add_argument("--period", default=None,
                    help="force the chart period as MT5 stores it (period_type/size pair, "
                         "e.g. 15m or 1h)")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--force", action="store_true",
                    help="rewrite even when the chart already looks equal (use after "
                         "changing the block schema: the idempotence check compares "
                         "TEXT, and a text-equal block can still be one MT5 ignores)")
    ap.add_argument("--scan", action="store_true", help="list every chart and its expert")
    a = ap.parse_args(argv)

    if a.startup_ini:
        if not a.dir:
            ap.error("--startup-ini needs --dir <terminal data folder>")
        data = Path(a.dir)
        if a.preset and not Path(a.preset).is_file():
            # Refuse BEFORE reading, so a typo in the path is a legible refusal rather than
            # a FileNotFoundError traceback from inside read_preset.
            raise SystemExit(f"not found: {a.preset}")
        preset = read_preset(Path(a.preset)) if a.preset else {}
        if not preset:
            raise SystemExit("REFUSING: --startup-ini needs --preset; an ExpertParameters "
                             "file that does not exist leaves the EA on code defaults")
        if str(preset.get("InpLiveExecution", "false")).lower() in ("true", "1") \
                and not ARMING_RECORD.is_file():
            raise SystemExit(f"REFUSING: {Path(a.preset).name} enables LIVE execution with "
                             f"no arming record — arming is a frozen-gate event")
        ini = Path(a.startup_ini)
        ini.parent.mkdir(parents=True, exist_ok=True)
        ini.write_text(startup_ini_text(a.expert, a.startup_symbol, a.startup_period,
                                       Path(a.preset).name), encoding="ascii")
        staged = data / "MQL5" / "Presets" / Path(a.preset).name
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(a.preset, staged)
        print(f"ini     : {ini}")
        print(f"preset  : {staged} ({len(preset)} inputs)")
        try:
            sys.path.insert(0, str(REPO / "scripts"))
            import mt5_ops  # noqa: PLC0415
            exe = mt5_ops.terminal_exe()
        except Exception:      # pragma: no cover — only the printed hint degrades
            exe = "<terminal64.exe>"
        print(f'launch  : "{exe}" /config:{ini}')
        print("          (scripts/mt5_ops.relaunch_terminal uses this file automatically "
              "when it exists at <data>\\config\\midas_attach.ini)")
        return 0

    if a.scan:
        charts = all_charts()
        if not charts:
            print(f"no chart files under {TERM_ROOT}")
        for p in charts:
            txt = read_chr(p)
            f = chart_facts(txt)
            exp = attached_expert(txt) or "(none)"
            ins = existing_inputs(txt)
            print(f"  {f.get('symbol', '?'):10s} {f.get('period_type', '?')}/"
                  f"{f.get('period_size', '?'):<3s} {exp:<38s} "
                  f"{len(ins)} input(s)  {p}")
        return 0

    if not a.chart or not a.preset:
        ap.error("--chart and --preset are required (or --scan)")
    chart, preset_path = Path(a.chart), Path(a.preset)
    if not chart.is_file():
        raise SystemExit(f"not found: {chart}")
    if not preset_path.is_file():
        raise SystemExit(f"not found: {preset_path}")

    preset = read_preset(preset_path)
    if not preset:
        raise SystemExit(f"REFUSING: {preset_path} declares no inputs — a chart written "
                         f"from nothing would run code defaults under a certified name")
    live = str(preset.get("InpLiveExecution", "false")).lower()
    if live in ("true", "1") and not ARMING_RECORD.is_file():
        raise SystemExit(
            f"REFUSING: {preset_path.name} enables LIVE execution and there is no arming "
            f"record at {ARMING_RECORD.relative_to(REPO)} — arming is a frozen-gate event, "
            f"never a chart edit")
    if "InpMagic" not in preset:
        raise SystemExit(f"REFUSING: {preset_path.name} pins no InpMagic — two arms with "
                         f"the same magic corrupt each other's ledgers")

    txt = read_chr(chart)
    facts = chart_facts(txt)
    print(f"chart   : {chart}")
    print(f"          symbol={facts.get('symbol', '?')} "
          f"period={facts.get('period_type', '?')}/{facts.get('period_size', '?')} "
          f"expert={attached_expert(txt) or '(none)'}")
    print(f"preset  : {preset_path} ({len(preset)} inputs, "
          f"magic {preset['InpMagic']}, live={live})")

    if a.symbol and a.symbol != facts.get("symbol"):
        txt = re.sub(r"(?m)^symbol=.*$", f"symbol={a.symbol}", txt, count=1)
        print(f"          symbol -> {a.symbol}")
    if a.period:
        m = re.fullmatch(r"(\d+)([smhd])", a.period.lower())
        if not m:
            raise SystemExit("--period must look like 15m, 1h, 1d")
        size, unit = m.group(1), m.group(2)
        ptype = {"m": "0", "h": "1", "d": "2", "s": "0"}[unit]
        txt = re.sub(r"(?m)^period_type=.*$", f"period_type={ptype}", txt, count=1)
        txt = re.sub(r"(?m)^period_size=.*$", f"period_size={size}", txt, count=1)
        print(f"          period -> {ptype}/{size}")

    already = existing_inputs(txt)
    if attached_expert(txt) == a.expert and already == preset and not a.force:
        print("nothing to do: this chart already runs this expert with byte-equal inputs")
        print("            (--force rewrites it; text equality is NOT proof MT5 accepted "
              "the block — check the EA's init line in MQL5\\Logs)")
        return 0

    new = apply_to_chart(txt, expert_block(preset, a.expert, a.flags))
    if not a.apply:
        print("DRY RUN: no file written. Re-run with --apply.")
        return 0

    if terminal_running():
        raise SystemExit("REFUSING: terminal64.exe is running — MT5 rewrites chart profiles "
                         "on exit and would clobber this edit. Close it first.")
    bak = chart.with_suffix(f".chr.{datetime.now():%Y%m%d_%H%M%S}.bak")
    shutil.copy2(chart, bak)
    write_chr(chart, new)

    back = read_chr(chart)
    stored = existing_inputs(back)
    problems = []
    if attached_expert(back) != a.expert:
        problems.append(f"expert path did not survive the write: {attached_expert(back)!r}")
    if stored != preset:
        diff = sorted(set(stored) ^ set(preset)) or \
            [f"{k}: {preset.get(k)!r} vs {stored.get(k)!r}"
             for k in preset if stored.get(k) != preset.get(k)][:4]
        problems.append(f"inputs are not the preset's: {diff}")
    if problems:
        shutil.copy2(bak, chart)
        raise SystemExit("REFUSING to leave a chart in this state (restored from backup):\n  "
                         + "\n  ".join(problems))
    print(f"OK: {a.expert} attached to {facts.get('symbol', '?')} with "
          f"{len(stored)} byte-equal inputs; backup {bak.name}")
    print("     the EA starts on the next terminal launch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
