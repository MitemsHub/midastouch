"""Strategy Tester runner for the V75MacroEngine regression gate (tier 3).

Drives the real MT5 Strategy Tester headlessly — the same proven path used by
every validation in this repo (terminal B, /config INI with an explicit
[TesterInputs] section, real-tick model, UTF-16 report + append-only agent
journal) — and returns the metrics the gate asserts on.

Hard-won gotchas encoded here:
  * [TesterInputs] must ALWAYS be explicit: an INI without it silently reuses
    the agent's last cached input set instead of the compiled defaults.
  * The EA's init-time "Exit manager: ..." print is the identity
    discriminator between what you asked to run and what actually ran.
  * The agent log is append-only: snapshot file sizes before launching and
    parse only the appended bytes, so runs never read each other's lines.
  * A /config launch against an ALREADY-RUNNING terminal is a silent
    single-instance no-op (2026-09-15 /portable, 2026-09-16 10:22 retry):
    run_pass now fast-fails on it instead of burning the full timeout.

Opt-in tier: set V75_TESTER_TESTS=1 (needs the local MT5 surface; two passes
take ~3 minutes on the 71-day real-tick window that lives fully in the local
tick cache).
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

TERMINAL_EXE = Path(os.environ.get(
    "V75_TESTER_TERMINAL",
    r"C:\Users\USER\AppData\Local\MitemshubMT5_B\terminal64.exe",
))
TERMINAL_DATA = Path(os.environ.get(
    "V75_TESTER_DATA",
    r"C:\Users\USER\AppData\Roaming\MetaQuotes\Terminal"
    r"\49E0383CD680D7AAEC56888AFA08F49E",
))
DEPOSIT = 10000.0
PASS_TIMEOUT_S = 420

_BASE_TESTER_INI = {
    "Expert": r"V75MacroEngine\V75MacroEngine",
    "Symbol": "Volatility 75 Index",
    "Period": "M30",
    "Model": "4",                      # every tick based on real ticks
    "FromDate": "2026.07.01",          # 71-day window, fully in local tick cache
    "ToDate": "2026.09.10",
    "Deposit": str(int(DEPOSIT)),
    "Currency": "USD",
    "Leverage": "100",
    "Visual": "0",
    "ShutdownTerminal": "1",
    "Report": "",                      # filled per pass
    "ReplaceReport": "1",
}


def report_path(tag: str) -> Path:
    return TERMINAL_DATA / f"V75_regress_{tag}.htm"


def _tester_roots() -> list[Path]:
    appdata = os.environ.get("APPDATA", str(TERMINAL_DATA.parents[1]))
    return [Path(appdata) / "MetaQuotes" / "Tester" / TERMINAL_DATA.name]


def journal_paths() -> list[Path]:
    """Today's agent log(s) across the tester roots."""
    today = datetime.now().strftime("%Y%m%d")
    out: list[Path] = []
    for root in _tester_roots():
        out += sorted(root.glob(f"Agent-*/logs/{today}.log"))
    return out


def journal_snapshots() -> dict[Path, int]:
    """Byte size of today's agent log(s) before a launch (offset anchors)."""
    return {log: log.stat().st_size for log in journal_paths()}


def journal_has_tag(tag: str, snaps: dict[Path, int] | None = None) -> bool:
    """Did the journal gain `RESEARCH_RESULT tag=<tag>` *since* `snaps`?

    The offset is what makes this correct. Tags are derived from deterministic
    experiment ids, so a re-run reuses the tag of an earlier pass in the same
    journal; an unscoped search finds that older line, the wait returns at once,
    and the delta-based parse then reports "no RESEARCH_RESULT line captured"
    while the registry silently keeps the report-based fallback.
    """
    marker = f"RESEARCH_RESULT tag={tag} "
    for log in journal_paths():
        offset = (snaps or {}).get(log, 0)
        try:
            if marker in log.read_bytes()[offset:].decode("utf-16-le", "ignore"):
                return True
        except OSError:
            continue
    return False


def _terminal_running() -> bool:
    """Is the tester terminal's process currently alive?

    Matched on the full executable path (case-insensitive), so the other MT5
    installs on this machine (FB9A, MitemshubMT5_C) never false-positive.
    """
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
         "Where-Object {$_.ExecutablePath} | ForEach-Object {$_.ExecutablePath})"],
        capture_output=True, text=True, timeout=30,
    ).stdout
    want = os.path.normcase(str(TERMINAL_EXE))
    return any(os.path.normcase(ln.strip()) == want for ln in out.splitlines())


def _wait_terminal_exit(timeout_s: float) -> bool:
    """True once the terminal is NOT running, waiting up to `timeout_s`.

    The tester self-exits after each pass (ShutdownTerminal=1) but teardown
    can lag the report by a few seconds; a pass-to-pass launch must not be
    condemned for that. Observed full passes run ~15 s, so 30 s is generous.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        if not _terminal_running():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(2.0)


def run_pass(tag: str, tester_inputs: dict[str, str], timeout_s: int = PASS_TIMEOUT_S,
             dates: tuple[str, str] = ("2026.07.01", "2026.09.10"),
             expert: str = r"V75MacroEngine\V75MacroEngine",
             wait_for_research_line: bool = False) -> dict:
    """Run one tester pass and return (report, journal) metrics.

    `expert` selects the compiled EA (relative to MQL5\\Experts). The default
    is the V75MacroEngine regression target; the V28 research engine passes
    "MITEMSHUB_AI\\MitemshubAI_v28".
    """
    assert tester_inputs, "explicit [TesterInputs] required (input-cache gotcha)"
    ini_path = TERMINAL_EXE.parent / "config" / f"v75_regress_{tag}.ini"
    base = {**_BASE_TESTER_INI, "Expert": expert,
            "FromDate": dates[0], "ToDate": dates[1],
            "Report": f"V75_regress_{tag}"}
    lines = ["[Tester]"]
    lines += [f"{k}={v}" for k, v in base.items()]
    lines += ["", "[TesterInputs]"] + [f"{k}={v}" for k, v in tester_inputs.items()]
    ini_path.write_text("\n".join(lines) + "\n", encoding="ascii")

    report = report_path(tag)
    report.unlink(missing_ok=True)
    snaps = journal_snapshots()

    # Single-instance fast-fail (2026-09-16: costed one 900 s timeout when the
    # direct-launch retry hit a live terminal). A /config launch against an
    # already-running terminal is a silent no-op — no report, no agent journal
    # — so fail here, with the fix in the message, instead of at timeout.
    if not _wait_terminal_exit(30.0):
        raise RuntimeError(
            f"terminal64.exe ({TERMINAL_EXE}) is already running — a /config "
            f"launch would be a silent single-instance no-op. Stop the terminal "
            f"first (its paper arm's ledger read + confirmed flat), then rerun: "
            f"see V28_RESEARCH_PROTOCOL.md §2 terminal-host precondition and "
            f"scripts/mt5_ops.py, which enforces the stop/flat-check/"
            f"sweep/relaunch discipline end to end.")

    subprocess.Popen([str(TERMINAL_EXE), f"/config:{ini_path}"])

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if report.exists():
            break
        time.sleep(3)
    else:
        tail = _diagnostic_tail(snaps)
        raise TimeoutError(f"tester pass '{tag}' produced no report in {timeout_s}s\n{tail}")
    # OnTester() runs at the very end of the pass and prints the
    # RESEARCH_RESULT line, which can land after the report file exists. Wait
    # (bounded) for that line rather than racing it — an EA that reports its own
    # whole-run R is the identity check, so a silent miss is not acceptable.
    deadline = time.monotonic() + (20 if wait_for_research_line else 0)
    while True:
        time.sleep(2 if wait_for_research_line else 3)
        if not wait_for_research_line or journal_has_tag(tag, snaps) or time.monotonic() >= deadline:
            break

    return {
        "report": parse_report(tag),
        "journal": parse_journal_segments(snaps, tag=tag),
    }


def _diagnostic_tail(snaps: dict[Path, int]) -> str:
    parts = []
    for log, size in snaps.items():
        try:
            text = log.read_bytes()[size:].decode("utf-16-le", "ignore")
            parts.append(text[-2000:])
        except OSError:
            continue
    return "\n".join(parts) if parts else "(no agent journal found)"


def parse_report(tag: str) -> dict:
    """Deals table of the UTF-16 tester report."""
    text = report_path(tag).read_bytes().decode("utf-16", "ignore")
    deals = []
    for row in re.findall(r"<tr[^>]*>((?:<td[^>]*>.*?</td>\s*)+)</tr>", text, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if (len(cells) >= 12 and re.match(r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}", cells[0])
                and re.match(r"^\d+$", cells[1])):
            deals.append(cells)

    def num(s: str) -> float:
        try:
            return float(s.replace(" ", ""))
        except ValueError:
            return 0.0

    entries = [d for d in deals if d[4] == "in"]
    exits = [d for d in deals if d[4] in ("out", "in/out")]
    trade_pnls = [num(d[10]) for d in exits]
    pnl = sum(num(d[10]) for d in exits)
    gross_win = sum(num(d[10]) for d in exits if num(d[10]) > 0)
    gross_loss = abs(sum(num(d[10]) for d in exits if num(d[10]) <= 0))
    return {
        "fills": len(entries),
        "exits": len(exits),
        "pnl": pnl,
        "pf": gross_win / gross_loss if gross_loss else float("inf"),
        "sl_hits": sum(1 for d in exits if len(d) > 12 and d[12].startswith("sl ")),
        "tp_hits": sum(1 for d in exits if len(d) > 12 and d[12].startswith("tp")),
        "entries_on_bar_open": all(d[0].endswith(":00") for d in entries),
        "trade_pnls": trade_pnls,
        # Simulated date, entry/exit, price, profit and reason per deal. The
        # report is the only source of *simulated* timestamps (the journal is
        # wall-clock), so any sub-period has to be sliced from here.
        "deals": deals,
    }


def pair_trades(deals: list[list[str]]) -> list[dict]:
    """Pair a parsed deals table into per-trade records.

    MT5 lists the entry deal ('in', direction = trade direction) followed by
    its exit deal ('out'/'in/out', direction = opposite side), so a single
    sequential pass pairs them. Money/R analysis that needs "which side was
    the trade on" must use the entry deal: the exit deal's direction is the
    closing side, which is why the naive 'exit direction = trade direction'
    split inverts the answer.
    """
    out: list[dict] = []
    pending: tuple[str, str, float] | None = None   # (side, entry_time, entry_price)
    for d in deals:
        try:
            price = float(d[6].replace(" ", "") or 0)
        except ValueError:
            price = 0.0
        if d[4] == "in":
            pending = (d[3], d[0], price)
        elif d[4] in ("out", "in/out") and pending:
            try:
                pnl = float(d[10].replace(" ", "") or 0)
            except ValueError:
                pnl = 0.0
            out.append({"side": pending[0], "entry_time": pending[1],
                        "entry_price": pending[2], "exit_time": d[0],
                        "exit_price": price, "pnl": pnl})
            pending = None
    return out


def split_sides(deals: list[list[str]]) -> dict:
    """Money split of a deals table by trade direction (from the entry deal)."""
    trades = pair_trades(deals)
    sides = ("buy", "sell")
    return {
        s: [t["pnl"] for t in trades if t["side"] == s]
        for s in sides
    } | {"all": trades}


def report_inputs(tag: str, keys: tuple[str, ...]) -> dict[str, str]:
    """Values the report itself records for `keys` (the run's own input dump).

    This is the authoritative check on what a pass actually ran with: the INI's
    [TesterInputs] can be merged with the agent's cached set, so only the report
    (or the EA's init-time identity print) proves the effective config.
    """
    text = report_path(tag).read_bytes().decode("utf-16", "ignore")
    plain = re.sub(r"<[^>]+>", " ", text)
    out: dict[str, str] = {}
    for key in keys:
        m = re.search(re.escape(key) + r"\s*=\s*([\w.]+)", plain)
        out[key] = m.group(1) if m else "?"
    return out


def report_stats(tag: str) -> dict[str, str]:
    """The report's Results block as label -> value (label and value on
    consecutive lines). Includes MT5's own drawdowns and `OnTester result`,
    which is the direct evidence of what OnTester() returned for the run."""
    text = report_path(tag).read_bytes().decode("utf-16", "ignore")
    plain = re.sub(r"<[^>]+>", "\n", text)
    plain = re.sub(r"\n{2,}", "\n", plain)
    lines = [l.strip() for l in plain.splitlines() if l.strip()]
    out: dict[str, str] = {}
    for i, line in enumerate(lines[:-1]):
        if line.endswith(":"):
            key = line[:-1]
            if key not in out:
                out[key] = lines[i + 1]
    return out


def parse_journal_segments(snaps: dict[Path, int], tag: str | None = None) -> dict:
    """Parse the journal bytes appended since the snapshots were taken.

    The append-only offset read is the primary path, but it can miss a line when
    the agent flushes late or the log rotates mid-run. When `tag` is given and
    no RESEARCH_RESULT line was found, fall back to a tag-addressed scan of the
    whole log — the tag is unique per pass, so the fallback is unambiguous.
    """
    chunks = []
    for log, size in snaps.items():
        # The agent journal is UTF-16, so an odd byte offset would slice a code
        # unit in half and garble the whole tail. Anchor on an even boundary.
        start = size - (size % 2)
        chunks.append(log.read_bytes()[start:].decode("utf-16-le", "ignore"))
    today = datetime.now().strftime("%Y%m%d")
    for root in _tester_roots():
        for log in root.glob(f"Agent-*/logs/{today}.log"):
            if log not in snaps:                       # log created by this run
                chunks.append(log.read_bytes().decode("utf-16-le", "ignore"))
    lines = [re.sub(r"^.*?Core 1\t", "", l).strip()
             for l in "\n".join(chunks).splitlines()]

    identity = next((l.split("Exit manager: ")[-1] for l in lines if "Exit manager:" in l), "")
    if not identity:
        # v2.x engines print "V75 Macro Engine vN.NN initialized (...)" instead
        # of an Exit manager line; the init print is the run's identity either
        # way. The version token excludes the deinit line ("deinitialized"
        # contains "initialized" as a substring).
        identity = next((l[l.index("V75 Macro Engine"):].strip() for l in lines
                         if "V75 Macro Engine v" in l and " initialized" in l), "")
    research = next((l.split("RESEARCH_RESULT ", 1)[-1].strip() for l in lines
                     if "RESEARCH_RESULT" in l), "")
    if not research and tag:
        marker = f"RESEARCH_RESULT tag={tag} "
        for log in journal_paths():
            try:
                full = log.read_bytes().decode("utf-16-le", "ignore")
            except OSError:
                continue
            hit = next((l for l in full.splitlines() if marker in l), None)
            if hit:
                research = re.sub(r"^.*?Core 1\s*", "", hit)\
                    .split("RESEARCH_RESULT ", 1)[-1].strip()
                break
    tp_mode = next((l.split("TP mode: ")[-1] for l in lines if "TP mode:" in l), "")
    # The EA's own accounting reconciliation for this pass: mean per-trade risk,
    # the ratio-sum R and the money-implied R, with the bound on their gap. The
    # mean risk is the only figure that converts this pass's R back to dollars,
    # so it has to travel with the record. Newest line wins (a re-run of the same
    # experiment appends a second one).
    reconciles = [l.split("R_RECONCILE ", 1)[-1].strip() for l in lines if "R_RECONCILE " in l]
    r_values = [float(m.group(1)) for l in lines if (m := re.search(r"Trade R:\s*(-?\d+\.\d+)", l))]
    final = re.search(r"final balance ([\d.]+)", "\n".join(lines))
    return {
        "identity": identity,
        "tp_mode": tp_mode,
        "research_result": research,
        "r_reconcile": reconciles[-1] if reconciles else "",
        "mfe_summary": ([l.split("MFE_SUMMARY ", 1)[-1].strip() for l in lines
                         if "MFE_SUMMARY " in l] or [""])[-1],
        "r_values": r_values,
        "r_sum": round(sum(r_values), 2),
        "closed_marks": sum(1 for l in lines if "POSITION CLOSED" in l),
        "timeouts": sum(1 for l in lines if "TIMEOUT EXPIRED" in l),
        "sl_moves": sum(1 for l in lines if "EXIT MANAGER: SL moved" in l),
        "modify_fails": sum(1 for l in lines if "SL modify failed" in l),
        "final_balance": float(final.group(1)) if final else None,
    }
