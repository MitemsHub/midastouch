"""The house MT5 Strategy Tester driver — headless `/config` runs, engine-agnostic.

Drives the real MT5 Strategy Tester headlessly — the same proven path used by
every validation in this repo (terminal B, /config INI with an explicit
[TesterInputs] section, real-tick model, UTF-16 report + append-only agent
journal) — and returns the metrics the caller asserts on. It was extracted for
the V75MacroEngine regression gate and that history is why the `V75_TESTER_*`
environment variables below keep their old names; nothing in this module is
specific to that engine, and `midas_parity.py` drives the gold EA through it.

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

It needs the local MT5 surface. `V75_TESTER_TERMINAL` / `V75_TESTER_DATA`
override the launch target and its data folder (still under their historical
names). When they are unset, the LIVE terminal is resolved by account identity
(`scripts/mt5_ops.py`, the same resolver the readiness check uses) rather than
from a remembered path.

MEASURED DEFECT, 2026-09-20: the unsetting path used to default to the RETIRED
install (the `MitemshubMT5_B` portable executable and the data folder whose id
begins `49E0383C`, the old portable XAUUSDmicro terminal). A probe pass launched
through those defaults stopped the
live terminal, wrote its config into the retired data folder and started the
retired executable, which produced no tester run, no report and no journal line —
a silent no-op that looks exactly like "the tester refused the pass". `run_pass`
now REFUSES that mismatch instead of inheriting it.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: The install this repo historically validated against. Kept only so the env
#: overrides can still reproduce old passes; never used as a silent default.
HISTORICAL_EXE = Path(r"C:\Users\USER\AppData\Local\MitemshubMT5_B\terminal64.exe")
HISTORICAL_DATA = Path(r"C:\Users\USER\AppData\Roaming\MetaQuotes\Terminal"
                       r"\49E0383CD680D7AAEC56888AFA08F49E")


def live_terminal_paths() -> tuple[Path, Path] | None:
    """(exe, data folder) of the terminal holding the active account, or None.

    Account identity, not a path: the registry says which account is active and the
    resolver finds the install running it. None means "could not tell" — which is not
    the same as "the historical one", and callers must not treat it as such.
    """
    try:
        if str(REPO / "scripts") not in sys.path:
            sys.path.insert(0, str(REPO / "scripts"))
        import mt5_ops as _ops  # noqa: PLC0415  (deliberately lazy: tests import this file)
        exe, folder = _ops.terminal_exe(), _ops.data_folder_for_terminal()
        if exe and folder:
            return Path(exe), Path(folder)
    except Exception:  # noqa: BLE001 — no MT5 surface here is a legitimate state
        pass
    return None


def _resolve(name: str, live_index: int, historical: Path) -> Path:
    override = os.environ.get(name)
    if override:
        return Path(override)
    live = live_terminal_paths()
    return live[live_index] if live else historical


TERMINAL_EXE = _resolve("V75_TESTER_TERMINAL", 0, HISTORICAL_EXE)
TERMINAL_DATA = _resolve("V75_TESTER_DATA", 1, HISTORICAL_DATA)


def assert_live_terminal() -> None:
    """Refuse a pass aimed at a terminal that is not the one holding the account.

    An honest fallback would be a silent one: the pass would write its config into a
    retired data folder and report nothing, and "no report" would read as a tester
    failure rather than as the wrong target. So this raises, naming the fix.
    """
    if os.environ.get("V75_TESTER_DATA"):
        return  # explicit override: the operator chose the target
    live = live_terminal_paths()
    if live is None:
        raise RuntimeError(
            "cannot resolve the live MT5 terminal (scripts/mt5_ops.py found no install "
            "holding the active account), and the historical defaults belong to the "
            "retired one — set V75_TESTER_DATA/V75_TESTER_TERMINAL explicitly to run a "
            "pass on purpose")
    if Path(live[1]) != Path(TERMINAL_DATA):
        raise RuntimeError(
            f"this module is aimed at {TERMINAL_DATA}, but the account lives in "
            f"{live[1]} — refusing to write a tester config into a retired data "
            f"folder (re-import this module, or set V75_TESTER_DATA explicitly)")
#: The sizing basis every simulated pass runs on. This account's evaluation size, not the
#: Deriv-era 10,000: `midas_parity` overrides Deposit too, and a default that disagrees
#: with the harness is a pass nobody can attribute.
DEPOSIT = 25000.0
PASS_TIMEOUT_S = 420

# --- the tick model the pass ACTUALLY used ---------------------------------
#
# MT5's [Tester] Model values, and only one of them is compatible with this
# program's evidence standard. A `Model=4` request ("every tick based on real
# ticks") is silently DOWNGRADED by the terminal to generated ticks when the local
# tick cache does not cover the window — the agent journal says so in passing and
# the report's History Quality reads 0%. That downgrade changes what the run
# proves: parity here is a per-tick model, so a generated-tick pass is not
# comparable evidence, and accepting it is how a certification gets recorded that
# nobody can reproduce.
#
# 2026-09-20, the second half of the same lesson. The `oos` parity pass declared
# Model=4 and the agent answered
#
#     Ticks: XAUUSD : real ticks begin from 2026.09.04 00:00:00
#
# for a window that started 2026.04.01 — five of its five and a half months were
# GENERATED, and the phrase "real ticks" inside that line matched the old
# `\breal ticks\b` evidence regex, so the guard called the pass REAL and let it
# through. MT5's vocabulary separates full coverage from partial coverage, and a
# partial-coverage line is a downgrade *relative to the window that was asked for*,
# which is why `detect_tick_model` now takes the window start and why every other
# statement MT5 writes when it fabricates ticks is named here:
#
#   "no real ticks, every tick generation used"           → fabricated
#   "real ticks begin from <date>"  (after the window)    → fabricated before <date>
#   "real ticks absent/discarded for N minutes ..."       → fabricated for those bars
#   "generating based on real ticks"                      → the tick store is the SOURCE,
#                                                          not proof the window is covered
#
# The asymmetry is deliberate: not certifying a pass that was denied its ticks costs
# a re-run and a readable message; certifying one is unrecoverable evidence.
TICK_MODEL_NAMES = {
    "0": "every tick (generated from the M1 series)",
    "1": "1 minute OHLC",
    "2": "open prices only",
    "3": "math calculations",
    "4": "every tick based on real ticks",
}
#: Declared models whose meaning REQUIRES real ticks to be present.
REAL_TICK_MODEL_CODES = frozenset({"4"})

#: The earliest date this venue serves REAL gold ticks for, in the tester's own date
#: frame, MEASURED from the agent journal on 2026-09-20:
#:     Ticks: XAUUSD : real ticks begin from 2026.09.04 00:00:00
#: It is the binding constraint on any per-tick claim made about this account: a window
#: that reaches further back than this cannot be certified on real ticks at all, and
#: `midas_parity.WINDOW_SPECS["tickcov"]` is scoped to it. If the venue deepens its
#: tick history this constant is the one place to re-derive (and the window with it).
TICK_COVERAGE_START = "2026.09.04"

_NO_REAL_TICKS = re.compile(r"no real ticks", re.I)
_GENERATION_USED = re.compile(r"every tick generation used", re.I)
_TICKS_NOT_USED = re.compile(r"real ticks (?:absent|discarded) for", re.I)
_REAL_TICKS_PARTIAL = re.compile(r"real ticks begin from\s+(\d{4}\.\d{2}\.\d{2})", re.I)
_GENERATING_FROM_REAL = re.compile(r"generating based on real ticks", re.I)
_REAL_TICKS = re.compile(r"\breal ticks\b", re.I)
_HISTORY_QUALITY = re.compile(r"History Quality:\s*(\d+)\s*%", re.I)


class TickModelMismatch(RuntimeError):
    """The pass ran under a different tick model from the one it declared."""

#: The defaults a pass inherits when the caller overrides nothing.
#:
#: THEY USED TO DESCRIBE A CLOSED PROGRAM (`V75MacroEngine` on `Volatility 75 Index`,
#: M30, $10,000, 1:100 — the Deriv era). That is not a harmless leftover, and 2026-09-21
#: showed why: a caller that launched this repo's gold EA through `run_pass` without
#: overriding them got a tester config naming an instrument this venue does not offer, so
#: no pass started at all and the run looked like a slow machine for the whole 420 s
#: timeout. Two of these values (`Deposit`, `Leverage`) also disagreed with what
#: `midas_parity` pins, so the same run could have silently used the wrong sizing basis.
#: A default that cannot run is worse than no default: point them at the only venue this
#: program has, on the basis this account actually holds, in the window whose ticks are
#: real (see TICK_COVERAGE_START — Model=4 outside it is downgraded, and the tick-model
#: guard refuses rather than certifying generated ticks).
_BASE_TESTER_INI = {
    "Expert": r"MIDASTOUCH\MidastouchAI",
    "Symbol": "XAUUSD",
    "Period": "M15",
    "Model": "4",                      # every tick based on real ticks
    "FromDate": "2026.09.07",          # inside the venue's real-tick coverage
    "ToDate": "2026.09.08",
    "Deposit": str(int(DEPOSIT)),
    "Currency": "USD",
    "Leverage": "1000",                # margin only: sizing is risk-percent
    "Visual": "0",
    "ShutdownTerminal": "1",
    "Report": "",                      # filled per pass
    "ReplaceReport": "1",
}


def report_path(tag: str) -> Path:
    return TERMINAL_DATA / f"V75_regress_{tag}.htm"


def report_text(tag: str) -> str:
    """The tester report's own bytes (UTF-16, as MT5 writes them)."""
    return report_path(tag).read_bytes().decode("utf-16", "ignore")


def appended_text(snaps: dict[Path, int]) -> str:
    """Every journal byte appended since `snaps`, plus any log this run created.

    Same offset discipline as :func:`parse_journal_segments`: reading whole logs
    would attribute an earlier pass's tick-model line to this one.
    """
    chunks: list[str] = []
    for log, size in snaps.items():
        start = size - (size % 2)          # never slice a UTF-16 code unit in half
        try:
            chunks.append(log.read_bytes()[start:].decode("utf-16-le", "ignore"))
        except OSError:
            continue
    today = datetime.now().strftime("%Y%m%d")
    for root in _tester_roots():
        for log in root.glob(f"Agent-*/logs/{today}.log"):
            if log not in snaps:                       # created by this run
                try:
                    chunks.append(log.read_bytes().decode("utf-16-le", "ignore"))
                except OSError:
                    continue
    return "\n".join(chunks)


def _substitution_statement(journal: str) -> str:
    """The first journal line that states ticks were NOT used, or ''.

    All three shapes mean the same thing to this program: the terminal fabricated
    part or all of the tick stream, so a per-tick comparison on those bars compares
    against a path nobody traded.
    """
    for line in journal.splitlines():
        if (_NO_REAL_TICKS.search(line) or _GENERATION_USED.search(line)
                or _TICKS_NOT_USED.search(line)):
            return line.strip()
    return ""


def _tick_date(stamp: str | None) -> datetime | None:
    """A tester date ('2026.04.01' or '2026.04.01 00:00') → datetime, or None."""
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp.strip()[:10], "%Y.%m.%d")
    except ValueError:
        return None


def detect_tick_model(journal: str, report: str,
                      window_from: str | None = None) -> tuple[str, str]:
    """What tick model the pass actually used → ('real'|'generated'|'unknown', why).

    `window_from` is the pass's own FromDate, and it is what turns MT5's
    partial-coverage statement ("real ticks begin from <date>") into a verdict: the
    ticks are real only if the cache reaches at or before the window the pass
    declared. Without it a partial statement cannot be shown to cover the pass, so
    it is reported as GENERATED rather than waved through — the guard's whole job is
    that neither a downgrade nor an unproven claim becomes a recorded pass.

    The journal is consulted first because it states the substitution in plain words;
    the report's History Quality is the numeric corroboration and the fallback. Pure
    text in, verdict out, so it is assertable without a terminal.
    """
    line = _substitution_statement(journal)
    if line:
        return "generated", f"journal: ...{line[-80:]}"
    m = _REAL_TICKS_PARTIAL.search(journal)
    if m:
        covers_from, starts = _tick_date(m.group(1)), _tick_date(window_from)
        if starts is None:
            return "generated", (f"journal: real ticks begin from {m.group(1)}, but no window "
                                 f"start was declared to compare it against")
        if covers_from is not None and covers_from <= starts:
            return "real", (f"journal: real ticks from {m.group(1)}, at or before the window "
                             f"start {window_from}")
        unticked = f"{abs((starts - covers_from).days)} day(s) of it" if covers_from else "part of it"
        return "generated", (f"journal: real ticks begin from {m.group(1)}, but the window starts "
                              f"{window_from} — {unticked} ran on generated ticks")
    m = _HISTORY_QUALITY.search(report)
    if m:
        pct = int(m.group(1))
        return (("real" if pct >= 100 else "generated"),
                f"report: History Quality {pct}% real ticks")
    for line in journal.splitlines():
        # "generating based on real ticks" is the tester announcing its SOURCE, and it
        # is written for a partial-coverage run as readily as a covered one — it is not
        # a statement that this window's ticks exist.
        if _REAL_TICKS.search(line) and not _GENERATING_FROM_REAL.search(line):
            return "real", f"journal: {line.strip()[-80:]}"
    return "unknown", "no tick-model statement found in the journal or the report"


def assert_declared_tick_model(snaps: dict[Path, int], tag: str,
                               declared_model: str,
                               window_from: str | None = None) -> tuple[str, str]:
    """Refuse a pass whose actual tick model differs from the one it declared.

    A declared real-tick model that silently ran on generated ticks is refused, and
    so is an UNKNOWN model: not knowing which ticks a certification ran on is the
    same defect as knowing they were the wrong ones. `window_from` is the FromDate
    the pass declared, so a partial tick cache is judged against the window it was
    supposed to cover. Callers that never ask for real ticks are unaffected — the
    check is about a request being honoured, not about which model is best.
    """
    verdict, evidence = detect_tick_model(appended_text(snaps), report_text(tag), window_from)
    if declared_model in REAL_TICK_MODEL_CODES and verdict != "real":
        raise TickModelMismatch(
            f"tester pass '{tag}' declared Model={declared_model} "
            f"({TICK_MODEL_NAMES.get(declared_model, '?')}) but ran on {verdict.upper()} "
            f"ticks ({evidence}). This program's parity model is per-tick, so the pass "
            f"is not comparable evidence and is refused rather than recorded. Either "
            f"populate the local tick cache for this window, or re-declare the model "
            f"deliberately and re-decide what the pass is evidence for.")
    return verdict, evidence


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


def config_dirs() -> list[Path]:
    """Where a ``/config`` INI may be written, best first.

    The install folder is deliberately LAST and usually unusable. The Upcomers
    terminal is installed to ``C:\\Program Files\\MetaTrader 5``, where a normal
    user cannot create files, so the first live parity attempt (2026-09-20) died
    with::

        PermissionError: [Errno 13] '...\\Program Files\\MetaTrader 5\\config\\...ini'

    The data folder is the right home anyway: it is per-install rather than shared
    by every instance of a given build, and it is where the era that actually
    produced parity artifacts kept its tester INIs (``<data>/config/midas_parity.ini``,
    2026-09-16). A portable install collapses the two into one, so the order costs
    nothing.
    """
    out: list[Path] = []
    for root in (TERMINAL_DATA, TERMINAL_EXE.parent):
        cfg = Path(root) / "config"
        if cfg not in out:
            out.append(cfg)
    return out


def write_config_ini(filename: str, text: str) -> Path:
    """Write an INI where the terminal can read it; return the path written.

    Each candidate is tried with a REAL write rather than an ``os.access`` probe:
    on Windows an access check against ``C:\\Program Files\\...`` can report
    writable and the write then fails anyway — which is precisely the failure this
    replaces. When no candidate works it refuses and names every one of them with
    its error, because a pass that cannot write its INI must never look like a pass
    that ran.
    """
    errors: list[str] = []
    for cfg in config_dirs():
        try:
            cfg.mkdir(parents=True, exist_ok=True)
            ini = cfg / filename
            ini.write_text(text, encoding="ascii")
            return ini
        except OSError as exc:
            errors.append(f"{cfg}: {exc}")
    raise RuntimeError(
        "cannot write a /config INI anywhere this terminal could read it — the pass "
        "would otherwise fail only AFTER the live terminal had been stopped:\n"
        + "\n".join(f"  - {e}" for e in errors))


def run_pass(tag: str, tester_inputs: dict[str, str], timeout_s: int = PASS_TIMEOUT_S,
             dates: tuple[str, str] = ("2026.07.01", "2026.09.10"),
             expert: str = r"V75MacroEngine\V75MacroEngine",
             wait_for_research_line: bool = False,
             model: str | None = None) -> dict:
    """Run one tester pass and return (report, journal) metrics.

    `expert` selects the compiled EA (relative to MQL5\\Experts) and defaults to this
    repo's gold engine; historical runners pass the program they are reproducing
    explicitly (`midas_parity` does). Everything else comes from `_BASE_TESTER_INI`, so a
    caller that overrides nothing gets THIS venue on THIS account's basis — see the note
    there for why that is a requirement and not a convenience.

    `model` overrides the tick model for a pass that is deliberately NOT certifying
    intrabar fills — a bar-replay comparison on a window the venue has no real ticks for.
    It is passed through rather than made quiet, because `assert_declared_tick_model`
    below judges the pass against what it declared: a caller that re-declares the model is
    stating what the pass is evidence for, and the artifact keeps saying it.
    """
    assert tester_inputs, "explicit [TesterInputs] required (input-cache gotcha)"
    assert_live_terminal()
    base = {**_BASE_TESTER_INI, "Expert": expert,
            "FromDate": dates[0], "ToDate": dates[1],
            "Report": f"V75_regress_{tag}"}
    if model is not None:
        base["Model"] = str(model)
    lines = ["[Tester]"]
    lines += [f"{k}={v}" for k, v in base.items()]
    lines += ["", "[TesterInputs]"] + [f"{k}={v}" for k, v in tester_inputs.items()]
    ini_path = write_config_ini(f"v75_regress_{tag}.ini", "\n".join(lines) + "\n")

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

    # The pass is not a pass until it can say which ticks it ran on.
    tick_used, tick_evidence = assert_declared_tick_model(snaps, tag, str(base["Model"]),
                                                          window_from=base["FromDate"])
    return {
        "report": parse_report(tag),
        "journal": parse_journal_segments(snaps, tag=tag),
        "tick_model": {"declared": str(base["Model"]), "used": tick_used,
                       "evidence": tick_evidence},
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
