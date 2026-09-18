"""V28 research sweep runner — the protocol's stop → flat-check → sweep → relaunch tool.

Graduated from scripts/_tmp_v28_sweep_orchestrator.py (2026-09-16) and
registered in V28_RESEARCH_PROTOCOL.md §2 as the standard way to run
`exit-sweep`/`matrix` cells on the tester terminal, which is also a live paper
arm's host. Enforces, in order:

1. **Terminal identity** — the tester terminal is located by its executable
   path, matched exactly (the machine also runs FB9A and MitemshubMT5_C;
   a path-only `-like` match or a bare tasklist count cannot tell them apart).
2. **Ledger-flat verification** — every V75 paper arm hosted by that terminal
   (discovered from its chart profiles, same method as morning_status) must
   have zero OPEN rows without a matching CLOSE row in its ledger. This is the
   EA's own restore rule (PaperInit adopts a dangling OPEN as a live virtual
   position), so "flat" here means exactly "the EA would restore nothing".
   A ledger that cannot be read fails closed — research never proceeds on an
   unreadable paper book. Override for genuine emergencies only:
   `--i-have-verified-flat` records the override in the log and the artifact.
3. **Stop → sweep → relaunch** — the terminal is stopped, the sweep command
   runs to completion, and the terminal is ALWAYS relaunched, whatever the
   sweep's exit code (the `finally` discipline from the _tmp orchestrator).
   run_pass's own fast-fail guard is the second line of defense.

Usage (protocol §2):
    python scripts/v28_sweep_runner.py exit-sweep --survivors V28_REVERSE_BOTH --window is180
    python scripts/v28_sweep_runner.py matrix --windows wf
    python scripts/v28_sweep_runner.py status      # inventory + flatness only

The artifact JSON (artifacts/v28_research/sweep_runner_last_run.json) records
the terminal identity, every arm's flatness evidence, the override flag, the
command, the exit code, and the relaunch — so any sweep window on the paper
arms is auditable after the fact.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

TERM_EXE = os.environ.get(
    "V28_SWEEP_TERMINAL",
    r"C:\Users\USER\AppData\Local\MitemshubMT5_B\terminal64.exe")
TERM_ROOT = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")
ARTIFACT = os.path.join(REPO, "artifacts", "v28_research", "sweep_runner_last_run.json")
STOP_WAIT_S = 60          # terminal must be gone within a minute of taskkill
RELAUNCH_SETTLE_S = 20    # banner/equity restore window before we report back

# The known arm magics (morning_status.MAGICS). A chart with an unknown magic
# is still inventoried — flagged, not silently skipped.
# 2026-09-16: 7788075 is now ARM A2 (v28.10 forward build); arm A retired.
KNOWN_MAGICS = {"7788075": "A2_fwd", "7788100": "B_tp24",
                "7788125": "C_v75", "7788150": "D_fwd"}


# --- terminal identity --------------------------------------------------------

def terminal_pids_exact() -> list[int]:
    """PIDs of terminal64.exe processes whose executable path matches exactly.

    Case-insensitive full-path equality — the other MT5 installs on this
    machine (FB9A, MitemshubMT5_C) must never match.
    """
    raw = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
         "Where-Object {$_.ExecutablePath} | ForEach-Object "
         "{$_.ExecutablePath + '|' + $_.ProcessId})"],
        capture_output=True, text=True, timeout=30).stdout
    want = os.path.normcase(TERM_EXE)
    pids: list[int] = []
    for ln in raw.splitlines():
        if "|" not in ln:
            continue
        exe, _, pid = ln.strip().rpartition("|")
        if os.path.normcase(exe) == want and pid.strip().isdigit():
            pids.append(int(pid))
    return pids


def stop_terminal(pids: list[int]) -> bool:
    """Taskkill the given PIDs, then wait until none of them remain."""
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    deadline = time.monotonic() + STOP_WAIT_S
    while time.monotonic() < deadline:
        if not terminal_pids_exact():
            return True
        time.sleep(2)
    return not terminal_pids_exact()


def relaunch_terminal() -> None:
    """Relaunch the terminal detached; equity/state restore on EA init."""
    subprocess.Popen([TERM_EXE], close_fds=True)
    time.sleep(RELAUNCH_SETTLE_S)


def data_folder_for_terminal() -> str | None:
    """The tester terminal's data folder, via origin.txt (best-effort).

    origin.txt records the terminal's INSTALL DIRECTORY (e.g.
    `...\\MitemshubMT5_B`), not the exe path — so match on the directory.
    MT5 writes it UTF-16 with BOM (a utf-8 read silently garbles it into
    replacement chars — caught live on 2026-09-16).
    """
    want_dir = os.path.normcase(os.path.dirname(TERM_EXE))
    for td in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
        origin = os.path.join(td, "origin.txt")
        try:
            raw = open(origin, "rb").read()
        except OSError:
            continue
        text = raw.decode("utf-16", errors="replace") \
            if raw[:2] in (b"\xff\xfe", b"\xfe\xff") \
            else raw.decode("utf-8", errors="replace")
        install_dir = text.strip().rstrip("\\/")
        if os.path.normcase(install_dir) == want_dir:
            return td
    return None


def inventory_arms(data_folder: str | None) -> list[dict]:
    """V75 paper arms hosted by the terminal, from its chart profiles.

    Same discovery method as morning_status.terminal_inventory: every chart
    whose .chr mentions the V75 symbol and an InpMagic yields one arm entry
    with its ledger path (InpArmTag switches the EA to tagged file names).
    """
    arms: list[dict] = []
    if not data_folder:
        return arms
    for chr_f in sorted(glob.glob(os.path.join(data_folder, "MQL5", "Profiles",
                                               "Charts", "*", "*.chr"))):
        try:
            txt = open(chr_f, encoding="utf-16", errors="replace").read()
        except OSError:
            continue
        # §14 portfolio: V75 arms AND MidastouchAI gold arms share this
        # inventory — every paper book on the terminal must gate a stop.
        if "Volatility 75" in txt:
            ea_prefix, sym = "MitemshubAI", "Volatility_75_Index"
        elif "MidastouchAI" in txt:
            gm = re.search(r"^symbol=(\S+)", txt, re.M)
            if not gm:
                continue
            ea_prefix, sym = "MIDASTOUCH", gm.group(1)
        else:
            continue
        m = re.search(r"^InpMagic(?:Number)?=(\d{7})\s*$", txt, re.M)
        if not m:
            continue
        magic = m.group(1)
        tm = re.search(r"^InpArmTag=(\S+)\s*$", txt, re.M)
        tag = tm.group(1) if tm else None
        suffix = f"_{tag}" if tag else ""
        ledger = os.path.join(data_folder, "MQL5", "Files",
                              f"{ea_prefix}_paper_{sym}{suffix}.csv")
        arms.append({"magic": magic,
                     "name": KNOWN_MAGICS.get(magic, f"unknown_{magic}"),
                     "tag": tag, "chart": os.path.basename(chr_f),
                     "ledger": ledger})
    return arms


def ledger_flatness(path: str) -> dict:
    """Is this paper ledger flat? Flat = zero OPEN rows without a CLOSE.

    This mirrors the EA's own restore rule (PaperInit adopts a dangling OPEN
    as a live virtual position), so flat here means exactly "the EA would
    restore nothing on the next init". Unknown-magic rows and ERA/EQ provenance
    rows are ignored; an unreadable or corrupt ledger FAILS CLOSED (flat=False
    with a problem recorded) — research never proceeds on an unreadable book.
    """
    res: dict = {"flat": False, "open_positions": [], "problems": [],
                 "rows": 0, "era_stamps": 0, "closed": 0}
    open_rows: dict[str, tuple[str, int]] = {}
    try:
        with open(path) as f:
            for ln, line in enumerate(f, 1):
                res["rows"] += 1
                parts = line.strip().split(",")
                if not parts:
                    continue
                if parts[0] == "OPEN" and len(parts) >= 12:
                    open_rows[parts[2]] = (parts[1], ln)
                elif parts[0] == "CLOSE" and len(parts) >= 8:
                    open_rows.pop(parts[2], None)
                    res["closed"] += 1
                elif parts[0] == "ERA":
                    res["era_stamps"] += 1
                elif parts[0] == "LOPEN" and len(parts) >= 14:
                    # 2026-09-18: LIVE-grammar awareness — a dangling LOPEN is
                    # a REAL-MONEY position (14 fields per the EA v1.16
                    # writer; keyed on [2] = posid). The parity session must
                    # never stop the terminal over an open live trade.
                    open_rows[parts[2]] = (parts[1], ln)
                elif parts[0] == "LCLOSE" and len(parts) >= 6:
                    # LCLOSE pairs the LOPEN (posid at [2]) and carries R, not $.
                    open_rows.pop(parts[2], None)
                    res["closed"] += 1
    except FileNotFoundError:
        res["problems"].append("ledger missing (arm never initialized?)")
        return res
    except OSError as e:
        res["problems"].append(f"unreadable: {e}")
        return res
    except (ValueError, IndexError) as e:
        res["problems"].append(f"corrupt row: {e}")
        return res
    res["open_positions"] = [
        {"ticket": t, "epoch": e, "line": n} for t, (e, n) in open_rows.items()]
    # Fail closed on a file that carries no recognizable ledger row at all:
    # a real paper book always has an era stamp, a trade, or both. A file with
    # nothing recognizable is either not a ledger or not yet initialized —
    # never treat an unverifiable book as flat.
    if res["rows"] == 0 or (not res["closed"] and not res["era_stamps"]
                            and not res["open_positions"]):
        res["problems"].append("no recognizable ledger rows (ERA/OPEN/CLOSE/LOPEN/LCLOSE)")
        res["flat"] = False
        return res
    res["flat"] = not res["open_positions"]
    return res


def verify_all_flat(arms: list[dict]) -> tuple[bool, list[dict]]:
    """Every arm's ledger must exist and be flat. Fails closed on problems."""
    all_flat, evidence = True, []
    for arm in arms:
        f = ledger_flatness(arm["ledger"])
        arm["flatness"] = f
        evidence.append({"name": arm["name"], "magic": arm["magic"],
                         "tag": arm["tag"], "ledger": arm["ledger"], **f})
        if not f["flat"]:
            all_flat = False
    return all_flat, evidence


# --- the runner ---------------------------------------------------------------

def run_guarded(v28_args: list[str], override: bool) -> int:
    """The whole discipline: identity → flat → stop → sweep → relaunch."""
    record: dict = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "terminal": TERM_EXE,
        "command": ["v28_research.py"] + v28_args,
        "override": override,
    }

    pids = terminal_pids_exact()
    record["terminal_pids_before"] = pids

    data_folder = data_folder_for_terminal()
    record["data_folder"] = data_folder
    arms = inventory_arms(data_folder)
    record["arms"] = [{"name": a["name"], "magic": a["magic"], "tag": a["tag"],
                       "chart": a["chart"], "ledger": os.path.basename(a["ledger"])}
                      for a in arms]

    all_flat, evidence = verify_all_flat(arms)
    record["flatness"] = evidence
    unknown = [a["name"] for a in arms if a["name"].startswith("unknown_")]
    if unknown:
        record["warnings"] = [f"unknown arm magic(s) on charts: {unknown} — "
                              f"inventoried and included in the flat check"]

    if not arms:
        print("WARNING: no V75 paper arms discovered on the tester terminal's "
              "charts — the flat check has nothing to verify. Refusing "
              "(verify manually, then use --i-have-verified-flat).")
        if not override:
            finish(record, rc=2)
            return 2

    if not all_flat and not override:
        offenders = [e for e in evidence if not e["flat"]]
        print("REFUSED: the tester terminal hosts a paper arm with an OPEN "
              "position (the EA would restore it on relaunch):")
        for e in offenders:
            for o in e["open_positions"]:
                print(f"  {e['name']}: ticket {o['ticket']} opened epoch "
                      f"{o['epoch']} (ledger line {o['line']})")
        print("Close the position (or let the arm exit it), then rerun. "
              "Override only with --i-have-verified-flat and a reason.")
        finish(record, rc=2)
        return 2
    if not all_flat and override:
        record["override_reason"] = "ledger not flat; override recorded"
        print("OVERRIDE RECORDED: proceeding despite a non-flat ledger.")

    if pids:
        print(f"stopping tester terminal (pids {pids}) …", flush=True)
        if not stop_terminal(pids):
            print("ERROR: terminal did not stop; refusing to sweep.", flush=True)
            finish(record, rc=3)
            return 3
        print("terminal stopped.", flush=True)
    else:
        print("terminal not running; nothing to stop.", flush=True)

    rc = 0
    try:
        print("sweep starting:", " ".join(record["command"]), flush=True)
        rc = subprocess.call([sys.executable,
                              os.path.join(REPO, "scripts", "v28_research.py")]
                             + v28_args, cwd=REPO)
        print(f"sweep finished rc={rc}", flush=True)
    except Exception as exc:                       # relaunch must run regardless
        rc = 4
        record["sweep_error"] = repr(exc)
        print(f"sweep ERROR: {exc!r}", flush=True)
    finally:
        relaunch_terminal()
        record["relaunched"] = True
        after = terminal_pids_exact()
        record["terminal_pids_after"] = after
        print(f"terminal relaunched (pids {after}) — verify the arm banner, "
              f"virtual equity, and tagged file names in the journal.", flush=True)

    record["sweep_rc"] = rc
    finish(record, rc=rc)
    return rc


def finish(record: dict, rc: int) -> None:
    try:
        os.makedirs(os.path.dirname(ARTIFACT), exist_ok=True)
        with open(ARTIFACT, "w") as fh:
            json.dump(record, fh, indent=1)
    except OSError as e:
        print(f"WARNING: could not write artifact: {e}")
    sys.exit(rc)


def cmd_status(_: argparse.Namespace) -> None:
    """Inventory only: terminal identity, arms, flatness. Exit 1 if not flat."""
    pids = terminal_pids_exact()
    data_folder = data_folder_for_terminal()
    arms = inventory_arms(data_folder)
    all_flat, evidence = verify_all_flat(arms)
    print(f"terminal: {TERM_EXE}")
    print(f"  running: {bool(pids)} pids={pids}")
    print(f"  data folder: {data_folder}")
    if not arms:
        print("  arms: NONE discovered (charts without a V75 magic?)")
    for e in evidence:
        state = "FLAT" if e["flat"] else \
            f"OPEN x{len(e['open_positions'])} " + \
            str([o['ticket'] for o in e['open_positions']])
        probs = f" problems={e['problems']}" if e["problems"] else ""
        print(f"  {e['name']:8s} magic={e['magic']} tag={e['tag']} "
              f"rows={e['rows']} closed={e['closed']} era={e['era_stamps']} "
              f"-> {state}{probs}")
    print(f"FLAT: {all_flat}")
    sys.exit(0 if all_flat else 1)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--i-have-verified-flat", action="store_true",
                    help="override the flat check (recorded in the artifact); "
                         "for verified emergencies only")
    ap.add_argument("v28_command", nargs=argparse.REMAINDER, default=[],
                    help="arguments passed to v28_research.py (e.g. "
                         "exit-sweep --survivors V28_REVERSE_BOTH --window is180); "
                         "or 'status' to only inventory and check flatness. "
                         "REMAINDER so the subcommand's own --flags pass through "
                         "unparsed (the top parser must not eat them — a plain "
                         "nargs='*' rejects `--survivors` and cost a wasted "
                         "invocation on 2026-09-16).")
    return ap


def main() -> None:
    args = build_parser().parse_args()

    if not args.v28_command or args.v28_command == ["status"]:
        cmd_status(args)
    run_guarded(args.v28_command, args.i_have_verified_flat)


if __name__ == "__main__":
    main()
