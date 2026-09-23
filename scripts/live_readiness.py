#!/usr/bin/env python3
"""LIVE READINESS — a go/no-go check for the Upcomers account, in one command.

Answers the only question that matters before a session: *is every precondition for
trading actually satisfied right now?* Each line is measured against the running
terminal, not read from a document, and the exit code is non-zero unless every
precondition holds.

It deliberately reports the ARMING gate as its own leg and does not treat "OFF" as a
failure to be fixed. Arming requires a walk-forward PASS record; nothing has one, and
no amount of readiness elsewhere substitutes for it. The distinction this tool exists
to preserve:

  1. **Operational readiness** — terminal connected, correct account, AutoTrading on,
     symbols resolvable, market open. These can be made true today.
  2. **Authorisation** — a validated configuration and an operator arming act. These
     cannot be manufactured, and a system that confuses (1) with (2) will trade an
     unvalidated signal the moment it is technically capable of doing so.

Usage:
  python scripts/live_readiness.py                # full check
  python scripts/live_readiness.py --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from midas_prop.execution.prop_execution import (  # noqa: E402
    ArmingGate,
    GateCriteria,
)

SYMBOL = "XAUUSD"

#: The task that supervises the arm. Named for the ARM, not for a paper run: MEASURED
#: 2026-09-22, its predecessor (`MitemshubPaperSupervisor`) was interactive-logon-only, so
#: the arm was unguarded for 407 consecutive minutes in the middle of a night while the
#: task itself reported Ready.
SUPERVISOR_TASK = "MIDASTOUCH Arm Supervisor"

#: MT5's SYMBOL_FILLING_MODE bits, named so the check reads as what it is.
FILLING_FOK = 1
FILLING_IOC = 2

#: The EA's own geometry, mirrored for the probe: `InpSlAtrMult` and `InpSlAtrMult * InpTpMult`
#: from the preset the arm runs, plus its `InpDeviationPoints`. The probe asks whether the
#: VENUE accepts an order of this shape; it is not a second sizing engine.
PROBE_SL_ATR_MULT = 2.0
PROBE_TP_R = 2.0
PROBE_DEVIATION_POINTS = 20

#: Retcodes that mean the venue declined to even consider the request, as opposed to
#: refusing the order's shape. Neither is a pass: an unasked question is not an answer.
RETCODE_DONE = 0
RETCODE_MARKET_CLOSED = 10018
RETCODE_TRADE_DISABLED = 10017
RETCODE_ALGO_DISABLED = 10027
UNDECIDED_RETCODES = (RETCODE_MARKET_CLOSED, RETCODE_TRADE_DISABLED, RETCODE_ALGO_DISABLED)


def filling_verdict(mode: int) -> tuple[bool, str]:
    """(ok, detail) for a symbol's supported filling modes.

    The EA sends through CTrade, whose `FillingCheck(symbol)` prefers FOK when the symbol
    lists it and otherwise IOC — and sets INVALID_FILL, sending nothing, when the symbol
    lists NEITHER. So the question is not "does the venue support my favourite mode" but
    "can the EA's own resolver reach a supported one", and that is what this mirrors.

    MEASURED 2026-09-21: this venue's XAUUSD reports filling_mode=0x2 (IOC only) while
    CTrade's constructor defaults to FOK. The default never reaches the wire because
    FillingCheck rewrites it per symbol — read out of the installed `Trade.mqh`, not
    assumed — which is exactly why the mode has to be re-checked every run rather than
    proven once by hand.
    """
    if mode & FILLING_FOK and mode & FILLING_IOC:
        return True, "FOK+IOC supported; CTrade resolves to FOK"
    if mode & FILLING_IOC:
        return True, "IOC only; CTrade resolves to IOC (its FOK default must not reach the wire)"
    if mode & FILLING_FOK:
        return True, "FOK only; CTrade resolves to FOK"
    return False, (f"neither FOK nor IOC is listed (filling_mode=0x{mode:X}) — CTrade's "
                   f"resolver fails and no order is ever sent")


def h1_atr_closed(mt5, symbol: str, period: int = 14) -> float:
    """Wilder ATR(period) on CLOSED H1 bars, or 0.0 when the series is not readable.

    `start=1` skips the forming bar: an ATR taken from a bar that is still moving is not the
    value the EA would size on, and the probe must ask about the order the arm would send.
    """
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 1, period + 30)
    if rates is None or len(rates) < period + 2:
        return 0.0
    tr = []
    for i in range(1, len(rates)):
        hi, lo, pc = float(rates[i]["high"]), float(rates[i]["low"]), float(rates[i - 1]["close"])
        tr.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    atr = sum(tr[:period]) / period
    for t in tr[period:]:
        atr = (atr * (period - 1) + t) / period
    return atr


def accept_check(mt5, symbol: str, *, atr: float, min_lot: float,
                 volume_step: float) -> tuple[bool | None, str]:
    """Ask the VENUE to price and margin a real min-lot order. SEND NOTHING.

    WHY THIS IS A GATE AND NOT A PARAGRAPH IN A CHANGELOG. On 2026-09-21 the order path was
    proven by hand, once: `order_check` returned retcode 0 with $241.76 of margin on a
    0.01-lot gold order. A hand proof decays — the venue can change its filling mode, the
    account can lose its trade permissions, and the next person to ask "does it work" would
    have to remember how it was done and repeat it. This is that proof, run every time.

    `order_check` is read-only BY CONSTRUCTION: MT5 prices the request against the server and
    returns retcode/margin without placing anything. There is no `order_send` in this file and
    a test pins its absence.

    Three answers, not two:
      * `True`  — the venue ACCEPTED the request (retcode 0).
      * `False` — the venue refused its shape (wrong filling mode, bad volume, bad stops).
      * `None`  — the venue could not be asked (market closed, trading disabled). This is not
                  a pass and not a failure; it is an unconfirmed check, and it renders WARN.
    """
    lots = max(min_lot, volume_step if volume_step > 0 else min_lot)
    stop = atr * PROBE_SL_ATR_MULT
    if stop <= 0:
        return None, "no ATR — the probe cannot size a stop, so no request was built"
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None or not getattr(tick, "ask", 0):
        return None, "no tick/spec — the venue could not be asked"
    ask = float(tick.ask)
    digits = int(getattr(info, "digits", 2))
    request = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lots,
        "type": mt5.ORDER_TYPE_BUY, "price": ask,
        "sl": round(ask - stop, digits), "tp": round(ask + stop * PROBE_TP_R, digits),
        "deviation": PROBE_DEVIATION_POINTS, "type_filling": mt5.ORDER_FILLING_IOC,
        "comment": "readiness probe (never sent)",
    }
    try:
        chk = mt5.order_check(request)
    except Exception as exc:                          # pragma: no cover — bridge failure
        return None, f"order_check raised {type(exc).__name__}: {exc}"
    if chk is None:
        return None, f"order_check returned None (last_error {mt5.last_error()}) — UNCONFIRMED"
    rc = int(chk.retcode)
    if rc == RETCODE_DONE:
        return True, (f"venue ACCEPTED a {lots:g}-lot buy, stop ${stop:.2f} "
                      f"({PROBE_SL_ATR_MULT:g}xATR), margin ${float(chk.margin):,.2f} — "
                      f"nothing was sent")
    if rc in UNDECIDED_RETCODES:
        return None, (f"the venue could not be asked now (retcode {rc}: "
                      f"{getattr(chk, 'comment', '')}) — UNCONFIRMED, not a pass")
    return False, (f"venue REFUSED the order shape: retcode {rc} "
                   f"({getattr(chk, 'comment', '')}) — a signal would be rejected here")


ARM_PATH = ROOT / "artifacts" / "live" / "armed.json"
VALIDATION_PATH = ROOT / "artifacts" / "live" / "validation_record.json"
ACCOUNTS_JSON = ROOT / "configs" / "mt5" / "accounts.json"

#: The EA whose binary a chart loads, and the record `scripts/compile_midas.py --deploy`
#: writes at the moment it produces it (see the leg below for why a record and not a
#: re-computation).
EA_SOURCE = ROOT / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
EA_EX5_NAME = "MidastouchAI.ex5"
BUILD_RECORD = ROOT / "artifacts" / "midas_build.json"


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def deployed_build_state(source: Path, deployed: list[Path],
                         record: Path | None = None) -> tuple[str, str]:
    """Is the binary a chart would load the one this SOURCE produces?

    Returns `("ok" | "stale" | "unconfirmed", detail)`. Three states, not two, and the
    third is the point: a build whose provenance cannot be checked must not render green,
    which is the same four-state discipline `add()` uses everywhere else here.

    WHY THIS LEG EXISTS. A chart loads whatever `.ex5` sits in the Experts tree. On
    2026-09-20 the terminal held a 20:17 build while the 23:02 source compiled clean at a
    different size, and the only symptom was a byte count in a log line — so every pin in
    this repo could describe a build that was not the one running. Timestamps alone catch
    an OLD binary; they cannot catch one REPLACED after the fact, and MetaEditor is not
    bit-reproducible, so the recorded pair is the only available provenance.
    """
    if not source.is_file():
        return "stale", f"the EA source is missing from the tree ({source})"
    missing = [str(p) for p in deployed if not p.is_file()]
    if missing:
        return "stale", (f"no binary where a chart loads it: {', '.join(missing)} — "
                          f"attach would load nothing, or a build from another tree")
    if record is not None and record.is_file():
        try:
            entry = json.loads(record.read_text(encoding="utf-8"))["targets"].get(
                source.stem)
        except (OSError, ValueError, KeyError, TypeError):
            return "unconfirmed", (f"the build record at {record} cannot be read, so the "
                                   f"deployed build's provenance is UNKNOWN")
        if not entry:
            return "stale", (f"the build record at {record} has no entry for "
                             f"{source.stem}")
        now_src = _sha256(source)
        if entry.get("source_sha256") and now_src != entry["source_sha256"]:
            return "stale", (f"the deployed build belongs to a DIFFERENT source: source "
                             f"{now_src[:8]} vs deployed-from "
                             f"{entry['source_sha256'][:8]} — re-run "
                             f"scripts/compile_midas.py --deploy")
        want = entry.get("ex5_sha256", "")
        for p in deployed:
            if want and _sha256(p) != want:
                return "stale", (f"{p.name} is not the binary that was compiled: ex5 "
                                 f"{_sha256(p)[:8]} vs recorded {want[:8]}")
        return "ok", (f"{source.stem}: source {now_src[:8]} == the source the deployed "
                       f"binary was built from ({len(deployed)} copy(s) hash-checked)")
    # No record: timestamps are all we have, and they only prove the ORDER of writes.
    newest_bin = max(p.stat().st_mtime for p in deployed)
    if source.stat().st_mtime > newest_bin:
        return "stale", (f"the deployed binary predates its source (source newer by "
                         f"{(source.stat().st_mtime - newest_bin) / 60:.0f} min) and "
                         f"there is no build record — re-run "
                         f"scripts/compile_midas.py --deploy")
    return "unconfirmed", (f"no build record at {record or '-'}: the binary is NEWER than "
                           f"the source, but that is not proof it was built from it"
                           f" (the compiler is not bit-reproducible) — run "
                           f"scripts/compile_midas.py --deploy")


#: THE BUILD THE SOURCE DEFINES. The EA states it in two places that are pinned equal to
#: each other (`tests/test_midas_hud.py`: `#property version` == `#define APP_VERSION`), and
#: the same string is what the EA appends in the `ERA` row it writes at every init — which
#: is the only reason the build a CHART is running can be read from outside the terminal.
APP_VERSION_RE = re.compile(r'^\s*#define\s+APP_VERSION\s+"([^"]+)"', re.M)

#: The arm's ledger name, as the EA's own `PaperFile()` builds it. Derived here rather than
#: globbed, so the leg reads the book of the arm the ARMING record names and not a retired
#: tag's leftover file.
ARM_LEDGER_TMPL = "MIDASTOUCH_paper_{symbol}_{tag}.csv"


def source_build_tag(source: Path) -> str | None:
    """The build tag the SOURCE defines, or None when it states none.

    None is a real answer and not a default: a source with no `APP_VERSION` cannot be
    compared with a chart, and inventing a tag from a filename, a timestamp or a compiled
    size is exactly how a leg goes green on nothing. It mirrors `deployed_build_state`'s
    refusal to guess provenance the compiler cannot prove.
    """
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = APP_VERSION_RE.search(text)
    return m.group(1) if m else None


def last_era_stamp(ledger: Path) -> tuple[str, int] | None:
    """`(tag, epoch)` off the LAST well-formed `ERA,<tag>,<epoch>,<note>` row, or None.

    The LAST one, because the EA appends that row at every init: a chart is running the
    build it last initialised into. A short row is SKIPPED rather than read generously —
    an `ERA` line with no tag is not a statement about a build, and parsing one as `""`
    would compare two empty strings and pass, which is the failure mode this file keeps
    learning about.
    """
    try:
        fh = ledger.open(encoding="utf-8", errors="replace")
    except OSError:
        return None
    last: tuple[str, int] | None = None
    with fh:
        for line in fh:
            parts = line.strip().split(",")
            if len(parts) < 3 or parts[0] != "ERA" or not parts[1]:
                continue
            try:
                last = (parts[1], int(parts[2]))
            except ValueError:
                continue            # a malformed stamp is not a stamp; the one above stands
    return last


def _stamp_text(epoch: int, now: datetime, off: int | None = None) -> str:
    """An `ERA` epoch rendered in UTC, with the venue offset applied and printed.

    LEDGER EPOCHS ARE SERVER-STAMPED (`TimeCurrent()`), so reading one with a UTC
    converter prints a plausible time two hours out — the whole-offset error this repo has
    already paid for once. The offset used is printed beside the answer so the reader never
    has to trust the subtraction, and `off` lets a caller hand in the ARM'S OWN recorded
    offset instead of today's (see `init_offset_min`).
    """
    off = venue_offset_min(now) if off is None else off
    utc = datetime.fromtimestamp(epoch - off * 60, tz=timezone.utc)
    age_min = (now - utc).total_seconds() / 60.0
    return f"{utc:%m-%d %H:%M}Z, {age_min:.0f} min ago (server +{off}min)"


#: How far a binary may postdate the chart's own init and still count as the same event.
#: The `ERA` epoch resolves to one second and the offset is applied by hand, so a deploy
#: followed immediately by a relaunch can legitimately land inside the same minute. The
#: margin is a MINUTE, not an hour: the failure this leg exists for was a deploy ~4 minutes
#: after the init, and a tolerance wide enough to swallow that would swallow the finding.
INIT_ORDER_TOLERANCE_S = 60

#: `STATE_OFF_UNKNOWN` in the EA: the two clocks disagree, so no offset may be named. It is
#: an assertion of NOT KNOWING, and reading it as a number would put a 166-hour error into
#: every conversion that used it.
STATE_OFF_UNKNOWN = -9999


def init_offset_min(ledger: Path) -> int | None:
    """The offset the ARM ITSELF recorded at the init the `ERA` row belongs to, or None.

    The `STATE` row written right after that `ERA` row carries `off_min` — the offset the
    EA measured with `TimeTradeServer() - TimeGMT()` at that moment. Converting the `ERA`
    epoch with TODAY'S measured offset is right almost always and an hour wrong across a
    DST step; using the arm's own reading removes the assumption instead of documenting it.
    None when the row predates v1.27 (no tail), when the offset is the not-knowing
    sentinel, or when it is outside ±14 h — the caller then falls back to the measured one.
    """
    try:
        fh = ledger.open(encoding="utf-8", errors="replace")
    except OSError:
        return None
    last_era_line = -1
    lines: list[str] = []
    with fh:
        for i, line in enumerate(fh):
            lines.append(line)
            if line.startswith("ERA,"):
                last_era_line = i
    for line in lines[last_era_line + 1:]:
        parts = [p for p in line.strip().split(",") if not p.startswith("cfg=")]
        if not parts or parts[0] != "STATE":
            continue
        # ONLY the init row: it is the one written beside the ERA row, so its offset is the
        # offset that stamps THAT epoch. A later STATE row could belong to a different era of
        # the venue's clock, which is the thing being avoided. The tail is the LAST FIVE
        # fields (`sig_ct,hour_utc,vol_ratio,news,off_min`) and it rides inside the row's
        # existing `%s`, so a v1.26 row — which has no tail at all — is skipped by length
        # rather than read as an offset by position.
        if len(parts) < 19:
            return None
        try:
            off = int(parts[-1])
        except ValueError:
            return None
        if off == STATE_OFF_UNKNOWN or abs(off) > 14 * 60:
            return None
        return off
    return None


def armed_arm_tag() -> str:
    """The arm tag the arming record names, or `""` when nothing is armed.

    Read through `mt5_ops.arming_state` — the one reader for "are we live?" — so this leg
    and the watchdog cannot disagree about which book is the live one.
    """
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import mt5_ops  # noqa: PLC0415
        return str(mt5_ops.arming_state(str(ROOT)).get("arm") or "")
    except Exception:      # noqa: BLE001 — an unreadable record is not a crash here
        return ""


def running_ledgers(term_data: Path | None, tag: str) -> list[Path]:
    """The ledgers of charts that are RUNNING here — the armed arm's first.

    NOT "every MIDASTOUCH ledger in Files/". A retired arm's book, or the parity harness's
    own tagged file, sits in that folder for the rest of the program's life; a leg that
    read them would fail forever over a chart nobody started. So the armed arm's book is
    DERIVED from its tag, and a machine with no arming record falls back to the arms this
    install actually attaches (start-up config + chart profiles), which is the same
    discovery `morning_status` and the watchdog use.
    """
    if term_data is None:
        return []
    files = term_data / "MQL5" / "Files"
    if tag:
        return [files / ARM_LEDGER_TMPL.format(symbol=SYMBOL, tag=tag)]
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import mt5_ops  # noqa: PLC0415
        arms = (list(mt5_ops.startup_attached_arms(str(term_data)))
                + list(mt5_ops.inventory_arms(str(term_data))))
    except Exception:      # noqa: BLE001
        return []
    out: list[Path] = []
    for arm in arms:
        p = Path(str(arm.get("ledger") or ""))
        if str(p) and p not in out:
            out.append(p)
    return out


def deploy_stamp(chart_binary: Path | None,
                 record: Path | None = None) -> float | None:
    """When the current deploy happened, from the two records that can say — the LATER one.

    BOTH, because each is blind to a different case. `scripts/compile_midas.py --deploy`
    copies with `shutil.copy2`, so the deployed file carries the SCRATCH build's mtime: a
    compile that finished before a chart's init and was copied after it would read as older
    than the init — as in step — while the file really was replaced underneath a running
    expert. The build record's `utc` is written after the copies, so it sees that case; and
    a HAND copy that never touches the script is seen only by the mtime. Neither reading is
    an identity check — that is the hash leg's job, above — they are ordering evidence.
    """
    stamps: list[float] = []
    if chart_binary is not None and chart_binary.is_file():
        stamps.append(chart_binary.stat().st_mtime)
    if record is not None and record.is_file():
        try:
            iso = str(json.loads(record.read_text(encoding="utf-8")).get("utc") or "")
            stamps.append(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
        except (OSError, ValueError, TypeError, AttributeError):
            pass          # no usable stamp from the record; the mtime above still speaks
    return max(stamps) if stamps else None


def running_build_state(source: Path, ledgers: list[Path], *,
                        terminal_checked: bool,
                        chart_binary: Path | None = None,
                        deploy_record: Path | None = None) -> tuple[str, str]:
    """Is the build the CHART is running the build this SOURCE defines?

    Returns `("ok" | "stale" | "unconfirmed", detail)`.

    WHY THIS LEG EXISTS, MEASURED 2026-09-22. The leg above answers "is the binary a chart
    WOULD load the one this source produces", and after a certified deploy it answered YES
    while the arm's own ledger still said `ERA,MIDAS1.26,…`. Replacing the `.ex5` did NOT
    re-initialise a **start-up-attached** expert: no re-init line in the terminal's
    journal, no new `ERA` row, fifteen minutes, market open. A green build leg and a chart
    one build behind are therefore two different facts, and only the second one is a chart
    trading the wrong binary. This leg reads the chart's OWN statement — the `ERA` row the
    EA appends at every init — because that is the only place the running build says what
    it is, and it is the same word a human reads on the chart.

    AND THE OTHER DIRECTION, which the version comparison alone cannot see: a chart can be
    initialised into the RIGHT version and still not be the file on disk, because the file
    was replaced afterwards. The arm's statement covers the binary that existed at its init
    and nothing that came later. When `chart_binary` (the copy a chart loads) was written
    AFTER that init, the running chart CANNOT be that binary — a process does not start
    from a file written after it — so the version leg would be reading a fact about a file
    nobody is running. That case arises when source was edited and redeployed without a
    version bump, which is exactly the discipline the pins cannot enforce; it is a FAIL
    because the same fix applies (re-initialise the expert, after which the version
    comparison is authoritative again), and because a live-money chart whose provenance
    cannot be vouched for is the state this file exists to refuse rather than to tolerate.
    """
    want = source_build_tag(source)
    if not want:
        return "unconfirmed", (f"{source.name} states no APP_VERSION, so the build a chart "
                               f"is running cannot be compared with it")
    if not terminal_checked:
        return "unconfirmed", ("no running terminal: the charts' own ERA rows cannot be "
                               "read, so the build they are running is UNKNOWN — the repo "
                               "copy is a record, not a chart")
    if not ledgers:
        return "unconfirmed", ("no arm ledger to read: nothing here names a chart this "
                               "install is running, so the build it runs is UNKNOWN rather "
                               "than in step")
    now = datetime.now(timezone.utc)
    binary_written = deploy_stamp(chart_binary, deploy_record)
    in_step: list[str] = []
    behind: list[str] = []
    superseded: list[str] = []
    silent: list[str] = []
    for path in ledgers:
        seen = last_era_stamp(path)
        if seen is None:
            silent.append(path.name)
            continue
        tag, epoch = seen
        # The arm's own recorded offset when it has one (v1.27+), today's measured one
        # otherwise: see `init_offset_min` for why that is not the same thing.
        off = init_offset_min(path)
        when = _stamp_text(epoch, now, off)
        if tag != want:
            behind.append(f"{path.stem} is running {tag} (last init {when})")
            continue
        if binary_written is not None:
            init_utc = epoch - (venue_offset_min(now) if off is None else off) * 60
            if binary_written > init_utc + INIT_ORDER_TOLERANCE_S:
                wrote = datetime.fromtimestamp(binary_written, tz=timezone.utc)
                superseded.append(
                    f"{path.stem} initialised into {tag} at {when}, but the deploy that "
                    f"produced the binary a chart loads is stamped {wrote:%m-%d %H:%M}Z — "
                    f"after that init, so the chart is running an EARLIER binary of the same "
                    f"version (source edited and redeployed without a version bump, or the "
                    f"build recompiled and re-deployed). Behaviour may be identical; what is "
                    f"proven is the ordering: the chart's own statement does not cover the "
                    f"file on disk")
                continue
        in_step.append(f"{path.stem} is running {tag} (last init {when})")
    if behind:
        return "stale", (f"the CHART is not running the deployed build: {'; '.join(behind)} "
                         f"against this source's {want} — so the binary on disk is not what "
                         f"trades. Re-initialise the expert on it (relaunch the terminal "
                         f"WITH its attach config, e.g. mt5_ops.relaunch_terminal(), or the "
                         f"registered stop-copy-verify-relaunch in scripts/midas_deploy_v118.py)")
    if superseded:
        return "stale", (f"the chart is not running the binary that exists: {'; '.join(superseded)}. "
                         f"Re-initialise the expert so its own statement covers the file "
                         f"(relaunch the terminal WITH its attach config, e.g. "
                         f"mt5_ops.relaunch_terminal(), or the registered "
                         f"stop-copy-verify-relaunch in scripts/midas_deploy_v118.py); after "
                         f"that, the version this leg reads is the version that trades")
    if in_step:
        return "ok", "the running chart names the build this source defines: " + \
                      "; ".join(in_step)
    return "unconfirmed", (f"no ERA row yet in {', '.join(silent)}: the arm has not "
                           f"initialised into a build, so which one it would run is UNKNOWN")


#: The gold week as this venue trades it, in UTC. MEASURED, not assumed: the daily
#: break and the Friday close are in docs/MIDASTOUCH_GOLD_PLAYBOOK.md §4 (gold is 24/5,
#: ~1h break around 21:00-22:00 UTC, weekend closed, flat over the weekend by policy).
GOLD_OPEN_HOUR_UTC = 22        # Sunday 22:00 UTC the week begins
GOLD_CLOSE_HOUR_UTC = 21       # Friday 21:00 UTC the week ends


def _last_sunday(year: int, month: int) -> datetime:
    """00:00 UTC on the last Sunday of a month (the EU DST rule's anchor)."""
    d = datetime(year, month, 1, tzinfo=timezone.utc) + timedelta(days=31)
    d = d.replace(day=1) - timedelta(days=1)          # last day of `month`
    return (d - timedelta(days=(d.weekday() + 1) % 7)).replace(
        hour=0, minute=0, second=0, microsecond=0)


def venue_offset_min(now: datetime) -> int:
    """The venue's server clock, in minutes ahead of UTC, at `now`.

    MEASURED, 2026-09-20: the tester's bar epochs sit **+60** through January-March and
    **+120** from April (docs/DATA_SCOPE_AND_CLOCK_20260920.md), a single step at the EU
    DST boundary — the server runs on Central European time. Without this, every reading
    taken from a server-stamped epoch is wrong by two hours, in a direction nobody
    notices: a fresh tick reports an age of -120 min and a closed market can report as
    open.

    The parity contract still derives its own pin per window from the venue's own bars
    and REFUSES when it is not constant — that stricter reading stays the authority for
    anything certified. This rule exists so the live checks read the same clock.
    """
    dst_start = _last_sunday(now.year, 3) + timedelta(hours=1)    # 01:00 UTC
    dst_end = _last_sunday(now.year, 10) + timedelta(hours=1)     # 01:00 UTC
    return 120 if dst_start <= now < dst_end else 60


def gold_session(now: datetime) -> tuple[bool, str]:
    """Is gold trading at `now` (UTC), and why — one rule, stated once.

    Sun 22:00 -> Fri 21:00, with a ~1h daily break 21:00-22:00 on Mon-Thu. The schedule
    is what makes the tick reading meaningful, and vice versa: a live tick inside a
    closed session is a data problem, not an opportunity.
    """
    wd, hh = now.weekday(), now.hour          # Monday=0 .. Sunday=6
    if wd == 5:
        return False, "weekend (Friday 21:00 -> Sunday 22:00 UTC)"
    if wd == 6:                                # Sunday
        return (True, "open (week) at %02d:00 UTC" % hh) if hh >= GOLD_OPEN_HOUR_UTC \
            else (False, "weekend, opens today %02d:00 UTC" % GOLD_OPEN_HOUR_UTC)
    if wd == 4 and hh >= GOLD_CLOSE_HOUR_UTC:  # Friday from the close
        return False, "weekend (closed from Friday %02d:00 UTC)" % GOLD_CLOSE_HOUR_UTC
    if hh == GOLD_CLOSE_HOUR_UTC:              # the daily break, Mon-Thu
        return False, "daily break (%02d:00-%02d:00 UTC)" % (GOLD_CLOSE_HOUR_UTC,
                                                             GOLD_OPEN_HOUR_UTC)
    return True, "open (Sun %02d:00 -> Fri %02d:00 UTC)" % (GOLD_OPEN_HOUR_UTC,
                                                            GOLD_CLOSE_HOUR_UTC)


def next_gold_open(now: datetime) -> datetime:
    """When the next session starts, or `now` itself when one is already running.

    MEASURED DEFECT, 2026-09-20: this returned the next *Sunday* unconditionally, so at
    Sunday 22:27 UTC — 27 minutes into the week — it printed "next gold open in 167.5h",
    a week away. Under time pressure that is the most dangerous wrong answer this tool can
    give, so the open-hour boundary is now part of the rule rather than an afterthought.
    """
    open_now, _ = gold_session(now)
    if open_now:
        return now
    if now.weekday() == 6:                     # Sunday before the open
        return now.replace(hour=GOLD_OPEN_HOUR_UTC, minute=0, second=0, microsecond=0)
    if now.weekday() in (0, 1, 2, 3):          # Mon-Thu inside the daily break
        return now.replace(hour=GOLD_OPEN_HOUR_UTC, minute=0, second=0, microsecond=0)
    days = (6 - now.weekday()) % 7             # Friday from the close, or Saturday
    return (now + timedelta(days=days)).replace(
        hour=GOLD_OPEN_HOUR_UTC, minute=0, second=0, microsecond=0)


def _scheduled_task_target(name: str) -> tuple[Path | None, str]:
    """The file a scheduled task would actually run, or (None, reason).

    Three outcomes are kept distinct on purpose: a path, "no such task", and "could not
    ask". Collapsing the last two would render an unanswerable check as a pass, which is
    the exact defect this repo audits elsewhere.
    """
    import re
    import subprocess

    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-ScheduledTask -TaskName '{name}').Actions | "
             "ForEach-Object { $_.Execute + ' ' + $_.Arguments }"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    text = (out.stdout or "").strip()
    if out.returncode != 0 or not text:
        return None, "not registered"
    m = re.search(r'"([^"]+\.(?:cmd|bat|exe|ps1))"', text) or \
        re.search(r"(\S+\.(?:cmd|bat|exe|ps1))", text)
    if not m:
        return None, f"no runnable path in the action ({text!r})"
    return Path(m.group(1)), ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", action="store_true",
                    help="do not touch the MT5 bridge at all; forces the "
                         "terminal-unavailable refusal (for machines with no "
                         "terminal, and for scripts/refusal_sweep.py)")
    args = ap.parse_args()

    if args.offline:
        # NOTE --offline is NOT equivalent to an empty %APPDATA%: the MT5 python
        # bridge locates a RUNNING terminal independently of %APPDATA%, so pointing
        # APPDATA at an empty directory does not stop this script connecting. That
        # was measured on 2026-09-19 and is why an explicit flag is the only way to
        # force the refusal path.
        print("TERMINAL UNAVAILABLE: --offline was requested", file=sys.stderr)
        print("REFUSING: readiness cannot be assessed without the terminal. A "
              "readiness report produced from no terminal would be a verdict about "
              "a source that was never read.", file=sys.stderr)
        return 3

    now = datetime.now(timezone.utc)
    term_data: Path | None = None
    checks: list[tuple[str, bool, str]] = []
    report: dict = {"utc": now.isoformat(timespec="seconds"),
                    "weekday": now.strftime("%A")}

    def add(name: str, ok: bool, detail: str, *, blocking: bool = True) -> None:
        """Record one check as (name, ok, detail, blocking).

        Four states, not two, because two of them are routinely conflated:

        * **PASS** — measured and satisfied.
        * **FAIL** — measured and unsatisfied, and it blocks.
        * **WARN** — could NOT be confirmed. This is NOT a pass. A check that
          cannot reach an answer must not render green, which is the whole defect
          class this repo audits elsewhere (see `docs/VERDICT_PROVENANCE_AUDIT_20260919.md`).
        * **OFF** — a known, deliberate, non-blocking state: the arming switch.
        """
        checks.append((name, ok, detail, blocking))
        if not ok and blocking:
            report.setdefault("failures", []).append(name)

    # ---- 1. operational -------------------------------------------------- #
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:
        add("MetaTrader5 module", False, f"not installed: {exc}")
        mt5 = None

    if mt5 is not None:
        if not mt5.initialize():
            add("terminal connection", False,
                f"mt5.initialize() failed, code {mt5.last_error()}")
        else:
            ti = mt5.terminal_info()
            ai = mt5.account_info()
            add("terminal connection", ti is not None,
                f"build {getattr(ti, 'build', '?')} @ {getattr(ti, 'path', '?')}")
            if ti is not None and getattr(ti, "data_path", ""):
                # The running terminal's OWN data folder, so the binary checked below is
                # the one a chart here would load — not the one a sibling install holds.
                term_data = Path(str(ti.data_path))
            if ti is not None:
                add("AutoTrading enabled", bool(ti.trade_allowed),
                    "Tools > Options > Expert Advisors > Allow Algo Trading"
                    if not ti.trade_allowed else "allowed")
                add("terminal connected", bool(ti.connected),
                    "disconnected from the server" if not ti.connected else "connected")
            if ai is None:
                add("account logged in", False, "account_info() returned None")
            else:
                report["account"] = {"login": int(ai.login), "server": ai.server,
                                     "company": getattr(ai, "company", ""),
                                     "currency": ai.currency,
                                     "equity": float(ai.equity),
                                     "balance": float(ai.balance),
                                     "leverage": int(ai.leverage),
                                     "trade_allowed": bool(ai.trade_allowed),
                                     "trade_expert": bool(ai.trade_expert)}
                add("account logged in", True,
                    f"{int(ai.login)} @ {ai.server} "
                    f"({getattr(ai, 'company', '?')})")
                expected = None
                if ACCOUNTS_JSON.is_file():
                    try:
                        reg = json.loads(ACCOUNTS_JSON.read_text(encoding="utf-8"))
                        act = reg.get("active", {})
                        # The key is 'account'; 'login' is accepted as a fallback so a
                        # registry written in the other convention still compares.
                        expected = act.get("account") or act.get("login")
                    except (OSError, ValueError):
                        expected = None
                if expected is None:
                    add("account matches the registry", False,
                        f"NO USABLE REGISTRY at {ACCOUNTS_JSON.name}: the terminal's "
                        f"account ({int(ai.login)}) cannot be confirmed as the one "
                        f"we intend to trade. Not a pass — an unconfirmed check.",
                        blocking=False)
                else:
                    add("account matches the registry",
                        int(ai.login) == int(expected),
                        f"terminal {int(ai.login)} vs registry {expected}")
                add("expert trading allowed on the account", bool(ai.trade_expert),
                    "the SERVER side of algo trading is off"
                    if not ai.trade_expert else "allowed")

            info = mt5.symbol_info(SYMBOL)
            tick = mt5.symbol_info_tick(SYMBOL)
            if info is None:
                add(f"{SYMBOL} available", False,
                    "symbol not found — check the suffix on this server")
            else:
                add(f"{SYMBOL} available", True,
                    f"{getattr(info, 'description', '')} "
                    f"spread {info.spread} pts, min lot {info.volume_min:g}")
                if tick is not None:
                    # The venue stamps epochs on ITS clock, so the raw difference is the
                    # server offset, not an age. Convert with the measured offset before
                    # judging freshness — otherwise a live tick reads as "-120 min ago"
                    # and a stale one can round to zero.
                    off_min = venue_offset_min(now)
                    tick_utc = (datetime.fromtimestamp(float(tick.time), tz=timezone.utc)
                                - timedelta(minutes=off_min))
                    age = (now - tick_utc).total_seconds()
                    sched_open, why = gold_session(now)
                    live = age < 900
                    report["tick"] = {"bid": float(tick.bid), "ask": float(tick.ask),
                                      "venue_offset_min": off_min,
                                      "tick_utc": tick_utc.isoformat(timespec="seconds"),
                                      "age_seconds": round(age),
                                      "session": why}
                    add("market open (live tick)", sched_open and live,
                        f"feed {'live' if live else 'STALE'} "
                        f"(last tick {age / 60:.0f} min ago, venue clock "
                        f"UTC{off_min // 60:+d}) | schedule: {why}")
                else:
                    add("market open (live tick)", False, "no tick available")

                # ---- 1a-order-path. CAN THIS ARM PLACE AN ORDER AT ALL? ----------#
                #
                # MEASURED 2026-09-21, the day the first live proof was done by hand: a
                # 0.01-lot XAUUSD request was ACCEPTED by the venue (retcode 0, $241.76 of
                # margin) and the arm's own filling mode had to be settled by reading the
                # installed Trade.mqh. Both facts were true and neither was checked by
                # anything that runs on a schedule — so "does it work" depended on someone
                # remembering. These two legs are that proof, made routine.
                ok_fill, detail_fill = filling_verdict(int(getattr(info, "filling_mode", 0)))
                add("symbol filling mode is usable", ok_fill, detail_fill)
                report["filling"] = {"mode": int(getattr(info, "filling_mode", 0)),
                                    "usable": ok_fill, "detail": detail_fill}
                atr_h1 = h1_atr_closed(mt5, SYMBOL)
                if atr_h1 <= 0:
                    add("order path accept-check (min lot, nothing sent)", None,
                        "no ATR(H1) from the terminal feed — the venue could not be asked "
                        "about an order of this shape: UNCONFIRMED, not a pass",
                        blocking=False)
                else:
                    ok_acc, detail_acc = accept_check(
                        mt5, SYMBOL, atr=atr_h1,
                        min_lot=float(getattr(info, "volume_min", 0.01)),
                        volume_step=float(getattr(info, "volume_step", 0.01)))
                    # blocking only when the venue REFUSED the shape (False): an
                    # unconfirmed check (None) must not stop the arm, and must not pass.
                    add("order path accept-check (min lot, nothing sent)", ok_acc, detail_acc,
                        blocking=(ok_acc is False))
                    report["order_path"] = {"atr_h1": round(atr_h1, 4),
                                           "sl_atr_mult": PROBE_SL_ATR_MULT,
                                           "accepted": ok_acc, "detail": detail_acc}

    # ---- 1b. the supervisor: registered, UNATTENDED, and able to run --------- #
    #
    # FOUR QUESTIONS, AND ONLY THE FIRST ONE WAS ASKED BEFORE 2026-09-22.
    #
    # A Task Scheduler entry embeds an ABSOLUTE path, so renaming this folder leaves the
    # task pointing at a directory that no longer exists. It then fires on schedule and
    # fails every time — which looks exactly like "nothing to report", because a task
    # that cannot start writes no log line either. That is the same defect class as the
    # stale VPS hosting record audited on 2026-09-19: a marker whose mere presence, or
    # whose stale content, keeps asserting an arrangement that has ended.
    #
    # MEASURED 2026-09-22 — the path check passed and the arm was still unguarded for most
    # of a night. `MitemshubPaperSupervisor` was Ready, pointed inside this repo, and ran
    # with `logon=Interactive`, i.e. only while a human was signed in: 54 passes in 25.3 h
    # where a 20-minute cadence owes 76, ZERO passes in the 01:00-06:00 UTC hours, one gap
    # of 407 minutes. So "registered" is not the property that matters:
    #
    #   1. does the action resolve to a file inside THIS repo?          (the old check)
    #   2. would it still run at 03:00 with nobody signed on?           (unattended.py)
    #   3. can THIS HOST hold it — or does the schedule evaporate when the lid shuts?
    #                                                                  (host_power.py)
    #   4. has a gap already been recorded and not acknowledged?        (live_coverage.py)
    #
    # (2) and (3) block, because both are machine faults this program can fix, and the
    # difference between them is the whole lesson: (2) says the schedule is wrong, (3)
    # says the machine is. A logon-only task now FAILS the readiness review instead of
    # rendering green beside a live arm.
    task_name = SUPERVISOR_TASK
    task_path, task_err = _scheduled_task_target(task_name)
    if task_err == "not registered":
        add(f"scheduled task target", False,
            f"{task_name} is not registered: nothing is supervising the arm. Register "
            f"it with scripts/install_paper_task.ps1 -Apply.", blocking=True)
    elif task_err:
        add(f"scheduled task target", None,
            f"{task_name}: could not be queried ({task_err}) — the supervisor's schedule "
            f"is UNCONFIRMED, not absent", blocking=False)
    elif task_path is None:
        add(f"scheduled task target", False,
            f"{task_name} is not registered: nothing is supervising the arm. Register it "
            f"with scripts/install_paper_task.ps1 -Apply.", blocking=True)
    else:
        inside = ROOT in task_path.parents or task_path.parent == ROOT
        add(f"scheduled task target", inside and task_path.is_file(),
            f"{task_name} -> {task_path}" if inside and task_path.is_file() else
            (f"STALE: {task_name} points at {task_path}, which is outside {ROOT} "
             f"or no longer exists. Re-run scripts/install_paper_task.ps1 -Apply."
             if not inside else f"target missing: {task_path}"),
            blocking=not (inside and task_path.is_file()))

    try:
        import unattended as _unattended  # noqa: PLC0415 — one reader for this question
        ok_un, detail_un = _unattended.verify_task(task_name)
        report["supervisor_unattended"] = {"ok": ok_un, "task": task_name,
                                           "detail": detail_un}
        add("supervisor runs unattended", ok_un, detail_un, blocking=True)
    except Exception as exc:      # noqa: BLE001 — unreadable is never a pass
        report["supervisor_unattended"] = {"ok": None, "error": str(exc)}
        add("supervisor runs unattended", None,
            f"the task definition could not be read ({exc}): UNCONFIRMED, not a pass",
            blocking=False)

    try:
        import host_power as _power  # noqa: PLC0415
        posture, p_err = _power.read_posture()
        if posture is None:
            report["host_power"] = {"ok": None, "error": p_err}
            add("host can hold supervision overnight", None,
                f"the power posture could not be read ({p_err}): UNCONFIRMED",
                blocking=False)
        else:
            # Three states, because the middle one is real: a host with nothing measured
            # WRONG that this program still cannot certify from powercfg alone (S0 Low
            # Power Idle: whether a wake timer wakes it, and whether the unreadable lid
            # policy suspends it, are not observable here). It renders WARN and does not
            # block — the thing that promotes it is one measured night, not a setting —
            # while a measured defect (wake timers off, a standing sleep timer) still
            # blocks, because that one has a fix.
            hv = posture["verdict"]
            report["host_power"] = {"ok": hv == "hold", "verdict": hv, **posture}
            add("host can hold supervision overnight",
                True if hv == "hold" else (None if hv == "unverified" else False),
                "; ".join(posture["problems"]) if posture["problems"] else
                (f"wake timers {posture['wake_timers']}, sleep/hibernate never, "
                 f"sleep states: {posture['sleep_states']}"),
                blocking=(hv == "cannot"))
    except Exception as exc:      # noqa: BLE001
        report["host_power"] = {"ok": None, "error": str(exc)}
        add("host can hold supervision overnight", None,
            f"the power posture could not be read ({exc}): UNCONFIRMED",
            blocking=False)

    try:
        import live_coverage as _cover  # noqa: PLC0415
        line = _cover.alarm_line()
        st = _cover.alarm_state()
        report["heartbeat_alarm"] = {"present": st.get("present", False),
                                     "current": st.get("current", False),
                                     "kind": st.get("kind"), "detail": st.get("detail")}
        if st.get("present"):
            add("no unacknowledged heartbeat gap", not st.get("current"),
                f"{line} — acknowledge with scripts/live_coverage.py --ack once the "
                f"night it describes has been read",
                blocking=bool(st.get("current")))
        else:
            # An absent check must still be REPORTED: a leg that disappears when the
            # state is clean reads as a leg that was never asked, which is the defect
            # this tool exists to catch.
            add("no unacknowledged heartbeat gap", True,
                "none outstanding (the rule is applied on every supervision pass; "
                "scripts/live_coverage.py --prereg states it)", blocking=False)
    except Exception as exc:      # noqa: BLE001
        report["heartbeat_alarm"] = {"present": None, "error": str(exc)}
        add("no unacknowledged heartbeat gap", None,
            f"the alarm record could not be read ({exc}): UNCONFIRMED", blocking=False)

    # ---- 1c. the deployed EA build ---------------------------------------- #
    #
    # Everything else here can be true while a chart runs an engine nobody pinned: the
    # source is the description, the .ex5 is what executes, and nothing in between is
    # automatic. So the binary's provenance is a readiness leg, not a footnote.
    deployed_bins = [ROOT / "mql5" / "MIDASTOUCH" / EA_EX5_NAME]
    if term_data is not None:
        deployed_bins.append(term_data / "MQL5" / "Experts" / "MIDASTOUCH" / EA_EX5_NAME)
    build_state, build_detail = deployed_build_state(EA_SOURCE, deployed_bins, BUILD_RECORD)
    if term_data is None:
        # The repo copy is the record; the TERMINAL copy is what a chart loads. Checking
        # one and calling it confirmed would be exactly the kind of green this repo audits
        # out, so an unchecked terminal downgrades an otherwise clean build to WARN.
        build_state = "ok" if build_state == "stale" else "unconfirmed"
        build_detail += (" | the terminal's Experts tree could NOT be checked (no running "
                         "terminal): the repo copy is not what a chart loads")
    report["build"] = {"state": build_state, "detail": build_detail,
                       "checked": [str(p) for p in deployed_bins]}
    add("deployed EA build matches its source", build_state == "ok", build_detail,
        blocking=(build_state == "stale"))

    # ---- 1d. the RUNNING build: what the chart is actually executing -------- #
    #
    # 1c asks whether a chart WOULD load the right binary. This asks whether the chart IS
    # on it, which is a different question and — measured 2026-09-22 — had a different
    # answer from it: a certified binary in step with its source, and an arm whose own ERA
    # row still named the previous build. Blocking FAIL when a chart can be READ and
    # disagrees (that chart is trading a binary nobody certified); WARN when it cannot be
    # read, because an unasked question is not a pass.
    run_bins = running_ledgers(term_data, armed_arm_tag())
    run_state, run_detail = running_build_state(
        EA_SOURCE, run_bins, terminal_checked=term_data is not None,
        # The TERMINAL's copy, i.e. the file a chart here loads — not the repo's record of
        # it. The ordering question is about the file the running expert came from.
        chart_binary=(deployed_bins[-1] if term_data is not None else None),
        deploy_record=BUILD_RECORD)
    report["running_build"] = {"state": run_state, "detail": run_detail,
                              "source_tag": source_build_tag(EA_SOURCE),
                              "ledgers": [str(p) for p in run_bins]}
    add("the CHART runs the deployed build", run_state == "ok", run_detail,
        blocking=(run_state == "stale"))

    # ---- 2. authorisation ------------------------------------------------ #
    # TWO QUESTIONS, TWO ANSWERS (2026-09-21). `ArmingGate` answers "may the PYTHON
    # execution path trade?" — it wants a `validation_record.json`, and it is still OFF.
    # The operator's record answers "has the account holder authorised the EA to trade?"
    # They were conflated here, and the result was the worst possible report on a live
    # arm: after the operator override this script printed "NOT AUTHORISED" while the
    # EA was placing real orders on 1428765. Execution is the operator's; EVIDENCE is
    # the gate's; each is reported as itself below.
    gate = ArmingGate(arm_path=ARM_PATH, validation_path=VALIDATION_PATH,
                      criteria=GateCriteria())
    arming = gate.evaluate()
    report["python_execution_gate"] = {"armed": arming.armed,
                                       "reasons": list(arming.reasons)}
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import mt5_ops  # noqa: PLC0415 — one reader for "are we live?"
        state = mt5_ops.arming_state(str(ROOT))
    except Exception as exc:      # pragma: no cover — unreadable record, never a crash
        state = {"armed": False, "override": False, "arm": "",
                 "summary": f"arming state unreadable: {exc}"}
    arming_armed = bool(state["armed"])
    arming_override = bool(state["override"])
    report["arming"] = {"armed": arming_armed, "override": arming_override,
                        "arm": state.get("arm", ""), "summary": state["summary"],
                        "python_gate": arming.armed}
    # Authorisation is never a blocking machine failure: a machine cannot be fixed into
    # being authorised.
    add("operator authorisation", arming_armed, state["summary"], blocking=False)
    add("python execution gate", arming.armed,
        "; ".join(arming.reasons)[:180], blocking=False)
    add("operator arming file present", ARM_PATH.is_file(),
        str(ARM_PATH) if ARM_PATH.is_file() else f"absent ({ARM_PATH})",
        blocking=False)
    add("validation record present", VALIDATION_PATH.is_file(),
        str(VALIDATION_PATH) if VALIDATION_PATH.is_file()
        else "absent — nothing has passed the walk-forward gate", blocking=False)

    # ---- 2b. does the evidence the record cites describe THIS strategy? --- #
    # A verdict about a different strategy is not evidence for this arm, and until
    # 2026-09-21 nothing here checked. `artifacts/live/armed.json` cites
    # `artifacts/gold_wfo.json` — a walk-forward whose only trigger axis is an M15 EMA stack,
    # with no Bollinger or RSI anywhere in the engine that wrote it — while the EA trades a
    # BB(20,2.0)/RSI(14) trigger. The two rules agree on the same bar and direction 3.4% of the
    # time, so the cited verdict is about a different strategy. Silence is the failure mode
    # here, which is why an UNDISCLOSED mismatch BLOCKS while a recorded one is named and
    # passes: what is being prevented is the presentation, not the operator's decision.
    family = gate.evidence_family()
    report["evidence_family"] = family
    family_ok = family["state"] in ("match", "disclosed-mismatch", "no-arm-record")
    add("evidence describes this strategy", family_ok, family["reason"][:230],
        blocking=(family["state"] == "mismatch"))

    # ---- 3. market hours, stated so nobody has to guess ------------------- #
    nxt = next_gold_open(now)
    hours = (nxt - now).total_seconds() / 3600.0
    report["next_gold_open_utc"] = nxt.isoformat(timespec="minutes")
    report["hours_to_open"] = round(hours, 1)

    # ---- verdict ---------------------------------------------------------- #
    auth_names = {"operator authorisation", "python execution gate",
                  "operator arming file present",
                  "validation record present", "account matches the registry"}
    blocking = [c for c in checks if c[1] is False and c[3]]
    operational_ok = not blocking
    verdict = (("AUTHORISED_BY_OPERATOR_OVERRIDE" if arming_override else "READY_TO_TRADE")
               if operational_ok and arming_armed else
               "OPERATIONALLY_READY_BUT_NOT_AUTHORISED" if operational_ok else
               "NOT_READY")
    report["verdict"] = verdict

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0 if operational_ok else 1

    print(f"=== LIVE READINESS — {now:%Y-%m-%d %H:%M UTC} ({now:%A}) ===")
    print()
    for name, ok, detail, is_blocking in checks:
        if ok:
            mark = "PASS"
        elif not is_blocking:
            mark = "OFF " if name == "python execution gate" else "WARN"
        else:
            mark = "FAIL"
        print(f"  [{mark}] {name:<38} {detail}")
    print()
    if arming_override:
        print(f"  authorisation: ARMED BY OPERATOR OVERRIDE ({state.get('arm', '?')}) — real "
              f"orders are being placed. NO validation record exists: this is the "
              f"account holder's decision on a FAILED gate, not a strategy that passed.")
    if family["state"] in ("mismatch", "disclosed-mismatch", "unknown"):
        print(f"  evidence: {family['reason']}")
    elif arming_armed:
        print("  authorisation: ARMED — a recorded validation plus the operator's act.")
    else:
        print("  authorisation: NOT ARMED — the venue gate is a separate condition from "
              "machine readiness, and it is the only one that cannot be fixed by "
              "configuring anything.")
    print()
    if hours <= 0.0:
        print(f"  market: OPEN — gold trades Sun 22:00 -> Fri 21:00 UTC "
              f"(daily break {GOLD_CLOSE_HOUR_UTC:02d}:00-{GOLD_OPEN_HOUR_UTC:02d}:00)")
    else:
        print(f"  market: closed — next gold open {nxt:%Y-%m-%d %H:%M} UTC "
              f"({hours:.1f}h away)")
    print()
    if verdict == "AUTHORISED_BY_OPERATOR_OVERRIDE":
        print("VERDICT: AUTHORISED BY OPERATOR OVERRIDE — TRADING, NOT VALIDATED.")
        print("  Real orders go out at the preset's declared risk. The walk-forward gate")
        print("  did not pass and no validation record exists; see artifacts/live/armed.json")
        print("  for the numbers the override was taken on, and what would retire it.")
        if family["state"] == "disclosed-mismatch":
            print("  AND the gate it cites measured a DIFFERENT STRATEGY — the record says so;")
            print("  see docs/GOLD_WFO_EA_VERDICT_20260921.md for the walk-forward of the")
            print("  rule this arm actually trades (also NOT VALIDATED).")
    elif verdict == "READY_TO_TRADE":
        print("VERDICT: READY TO TRADE.")
    elif verdict == "OPERATIONALLY_READY_BUT_NOT_AUTHORISED":
        print("VERDICT: OPERATIONALLY READY, NOT AUTHORISED.")
        print("  Everything the venue requires of the machine is satisfied. What is")
        print("  missing is a strategy that has passed the walk-forward gate, and")
        print("  that is not something this script can arrange.")
    else:
        print("VERDICT: NOT READY.")
        for n in report.get("failures", []):
            print(f"  blocking: {n}")
    # The evidence refusal is its own statement, and it is NOT a machine fault: the terminal,
    # the account, the build and the market can all be perfect while this fails, because what
    # fails is a practice — citing another strategy's verdict as this arm's evidence. Saying
    # so explicitly keeps "NOT READY" from being misread as "the arm is not trading".
    if family["state"] == "mismatch":
        print()
        print("REFUSAL: the arming record cites a verdict about a DIFFERENT STRATEGY and does")
        print("  not say so, so it is refused as this arm's evidence. This is not a machine")
        print("  fault — the operational legs above are unchanged by it, and the arm keeps")
        print("  trading on the operator's override. What it refuses is the presentation.")
        print("  To clear it: cite a walk-forward of the EA's own rule (artifacts/gold_wfo_ea.json")
        print("  exists and is NOT VALIDATED either), or record the mismatch in the arming")
        print(f"  record under 'gate_family_mismatch': {family['reason'][:150]}")
    return 0 if operational_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
